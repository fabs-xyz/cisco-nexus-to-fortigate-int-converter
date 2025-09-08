import copy
import os
import re

# IPv4 regex: matches IPv4 patterns only (no adjacent digits)
IP_RE = re.compile(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)')


def parse_cisco_interface(input_path: str):
    print('Starting parse...')
    interface_dict_list = []
    interface_dict = None
    pending_dhcp_relay = False  # Marker in case "ip dhcp relay address" is wrapped and the IPs are on the next line

    with open(input_path, encoding='utf-8') as f:
        for line in f.readlines():
            stripped = line.strip()

            # End of block (legacy NX-OS style)
            if stripped.startswith("!"):
                if interface_dict:
                    interface_dict_list.append(copy.deepcopy(interface_dict))
                    interface_dict = None
                pending_dhcp_relay = False
                continue

            # New interface starts
            if stripped.startswith("interface"):
                if interface_dict:
                    interface_dict_list.append(copy.deepcopy(interface_dict))
                interface_dict = {'dhcp_relay_list': [], 'dhcp_relay_exists': False}
                pending_dhcp_relay = False
                parts = stripped.split()
                if len(parts) > 1 and parts[0] == "interface":
                    vlan_id = parts[1].replace("Vlan", "")
                    interface_dict['vlan_id'] = vlan_id

            elif interface_dict is not None:
                # If the previous line was "ip dhcp relay address" without IPs, expect continuation line here
                if pending_dhcp_relay:
                    ips = IP_RE.findall(stripped)
                    if ips:
                        interface_dict['dhcp_relay_exists'] = True
                        interface_dict['dhcp_relay_list'].extend(ips)
                        pending_dhcp_relay = False
                    # no "continue": this line may also carry other info

                if stripped.startswith("description"):
                    desc = stripped.replace("description", "").strip()
                    # Alias up to 25 characters
                    interface_dict['description'] = desc[:25]

                elif stripped.startswith("ip address"):
                    if stripped == "no ip address":
                        continue
                    if "/" in stripped:
                        # New syntax with CIDR
                        try:
                            ip, mask = stripped.split()[2].split("/")
                            interface_dict['ip_address'] = ip
                            interface_dict['subnet_mask'] = mask
                        except Exception:
                            pass
                    else:
                        # Legacy syntax with dotted mask
                        parts = stripped.split()
                        if len(parts) >= 4:
                            interface_dict['ip_address'] = parts[2]
                            interface_dict['subnet_mask'] = parts[3]

                elif stripped.startswith("ip helper-address") or stripped.startswith("ip dhcp relay address"):
                    # Grab all IPv4s from the (possibly wrapped) line
                    ips = IP_RE.findall(stripped)
                    if ips:
                        interface_dict['dhcp_relay_exists'] = True
                        interface_dict['dhcp_relay_list'].extend(ips)
                        pending_dhcp_relay = False
                    else:
                        # Example:
                        # ip dhcp relay address
                        #   10.1.1.10 10.1.1.20
                        pending_dhcp_relay = True

                elif stripped.startswith("standby"):
                    # Legacy HSRP syntax
                    parts = stripped.split()
                    try:
                        if parts[2] == "ip":
                            interface_dict['ip_address'] = parts[3]
                    except IndexError:
                        pass

                elif stripped.startswith("hsrp"):
                    # New HSRP block syntax – ignore details
                    continue

                elif " ip " in stripped and "hsrp" not in stripped:
                    # Try to catch secondary IP or normal IP lines
                    parts = stripped.split()
                    if len(parts) > 1 and "." in parts[1]:
                        if len(parts) > 2 and parts[2] == "secondary":
                            interface_dict['secondary'] = parts[1]
                        else:
                            interface_dict['ip_address'] = parts[1]

        # Save the last interface
        if interface_dict:
            interface_dict_list.append(interface_dict)

    print(f"Detected {len(interface_dict_list)} interfaces.")
    return interface_dict_list


def _render_dhcp_relay_list(dhcp_list):
    """Build quoted list for FortiOS output."""
    # Clean IPs (trim whitespace/quotes) and join with quotes
    return ' '.join('"{}"'.format(str(ip).strip().strip('"')) for ip in dhcp_list)


def config_dhcp_relay(interface_dict: dict, interface_name: str) -> str:
    try:
        if '.' in interface_dict['subnet_mask']:
            # Legacy syntax with dotted mask
            config = f"""
            edit "VL.{interface_dict['vlan_id']}"
                set vdom "root"
                set dhcp-relay-service enable
                set ip {interface_dict['ip_address']} {interface_dict['subnet_mask']}
                set allowaccess ping
                set status down
                set alias "{interface_dict.get('description', '')}"
                set device-identification enable
                set role lan
                set dhcp-relay-ip {_render_dhcp_relay_list(interface_dict['dhcp_relay_list'])}
                set dhcp-relay-request-all-server enable
                set interface "{interface_name}"
                set vlanid {interface_dict['vlan_id']}
            next
            """
        else:
            # New syntax with CIDR
            config = f"""
            edit "VL.{interface_dict['vlan_id']}"
                set vdom "root"
                set dhcp-relay-service enable
                set ip {interface_dict['ip_address']}/{interface_dict['subnet_mask']}
                set allowaccess ping
                set status down
                set alias "{interface_dict.get('description', '')}"
                set device-identification enable
                set role lan
                set dhcp-relay-ip {_render_dhcp_relay_list(interface_dict['dhcp_relay_list'])}
                set dhcp-relay-request-all-server enable
                set interface "{interface_name}"
                set vlanid {interface_dict['vlan_id']}
            next
            """
    except Exception as e:
        print(f"Skipping interface with DHCP relay VLAN {interface_dict.get('vlan_id', 'unknown')}: {e}")
        config = ''
    return config


def config_no_dhcp_relay(interface_dict: dict, interface_name: str) -> str:
    try:
        if '.' in interface_dict['subnet_mask']:
            # Legacy syntax with dotted mask
            config = f"""
            edit "VL.{interface_dict['vlan_id']}"
                set vdom "root"
                set ip {interface_dict['ip_address']} {interface_dict['subnet_mask']}
                set allowaccess ping
                set status down
                set alias "{interface_dict.get('description', '')}"
                set device-identification enable
                set role lan
                set interface "{interface_name}"
                set vlanid {interface_dict['vlan_id']}
            """
            if 'secondary' in interface_dict.keys():
                config += f"""
                set secondary-IP enable
                    config secondaryip
                        edit 1
                            set ip {interface_dict['secondary']} {interface_dict['subnet_mask']}
                            set allowaccess ping
                        next
                    end
                """
            config += 'next\n'
        else:
            # New syntax with CIDR
            config = f"""
            edit "VL.{interface_dict['vlan_id']}"
                set vdom "root"
                set ip {interface_dict['ip_address']}/{interface_dict['subnet_mask']}
                set allowaccess ping
                set status down
                set alias "{interface_dict.get('description', '')}"
                set device-identification enable
                set role lan
                set interface "{interface_name}"
                set vlanid {interface_dict['vlan_id']}
            """
            if 'secondary' in interface_dict.keys():
                config += f"""
                set secondary-IP enable
                    config secondaryip
                        edit 1
                            set ip {interface_dict['secondary']}/{interface_dict['subnet_mask']}
                            set allowaccess ping
                        next
                    end
                """
            config += 'next\n'
    except Exception as e:
        print(f"Skipping interface without DHCP relay VLAN {interface_dict.get('vlan_id', 'unknown')}: {e}")
        config = ''
    return config


def create_forti_interface(interface_dict_list: list, interface_name: str):
    os.makedirs('output', exist_ok=True)
    with open('output/forti_config.txt', 'w+', encoding='utf-8') as f:
        for interface_dict in interface_dict_list:
            print(f"Processing VLAN {interface_dict.get('vlan_id', 'unknown')}")
            if interface_dict.get('dhcp_relay_exists'):
                config = config_dhcp_relay(interface_dict, interface_name)
                f.write(config)
            else:
                config = config_no_dhcp_relay(interface_dict, interface_name)
                f.write(config)
    print("Configuration successfully created → output/forti_config.txt")


if __name__ == '__main__':
    input_file = 'input/input_nexus.txt'
    parsed_info = parse_cisco_interface(input_file)
    # First line = uplink
    with open(input_file, encoding='utf-8') as f:
        lacp_name = f.readline().strip()
    create_forti_interface(parsed_info, interface_name=lacp_name)
