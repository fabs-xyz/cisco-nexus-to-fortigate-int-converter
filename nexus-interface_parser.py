import copy

def parse_cisco_interface(input_path: str):
    print('Start parsing...')
    interface_dict_list = []
    interface_dict = None

    with open(input_path) as f:
        for line in f.readlines():
            stripped = line.strip()
            if stripped.startswith("!"):
                # Alte NX-OS Syntax → Blockende
                if interface_dict:
                    interface_dict_list.append(copy.deepcopy(interface_dict))
                    interface_dict = None
                continue

            if stripped.startswith("interface"):
                # Neues Interface beginnt
                if interface_dict:
                    interface_dict_list.append(copy.deepcopy(interface_dict))
                interface_dict = {'dhcp_relay_list': [], 'dhcp_relay_exists': False}
                parts = stripped.split()
                if len(parts) > 1 and parts[0] == "interface":
                    vlan_id = parts[1].replace("Vlan", "")
                    interface_dict['vlan_id'] = vlan_id

            elif interface_dict is not None:
                if stripped.startswith("description"):
                    desc = stripped.replace("description", "").strip()
                    # Alias max. 25 Zeichen
                    interface_dict['description'] = desc[:25]
                elif stripped.startswith("ip address"):
                    if stripped == "no ip address":
                        continue
                    if "/" in stripped:
                        # Neue Syntax mit CIDR
                        ip, mask = stripped.split()[2].split("/")
                        interface_dict['ip_address'] = ip
                        interface_dict['subnet_mask'] = mask
                    else:
                        # Alte Syntax mit Maske
                        parts = stripped.split()
                        if len(parts) >= 4:
                            interface_dict['ip_address'] = parts[2]
                            interface_dict['subnet_mask'] = parts[3]
                elif stripped.startswith("ip helper-address"):
                    relay_ip = stripped.split()[-1]
                    interface_dict['dhcp_relay_exists'] = True
                    interface_dict['dhcp_relay_list'].append(f'"{relay_ip}"')
                elif stripped.startswith("ip dhcp relay address"):
                    relay_ip = stripped.split()[-1]
                    interface_dict['dhcp_relay_exists'] = True
                    interface_dict['dhcp_relay_list'].append(f'"{relay_ip}"')
                elif stripped.startswith("standby"):
                    # Alte HSRP Syntax
                    parts = stripped.split()
                    try:
                        if parts[2] == "ip":
                            interface_dict['ip_address'] = parts[3]
                    except IndexError:
                        pass
                elif stripped.startswith("hsrp"):
                    # Neue HSRP Block-Syntax
                    continue
                elif " ip " in stripped and "hsrp" not in stripped:
                    # Versuche, Secondary-IP oder normale IP abzufangen
                    parts = stripped.split()
                    if len(parts) > 1 and "." in parts[1]:
                        if len(parts) > 2 and parts[2] == "secondary":
                            interface_dict['secondary'] = parts[1]
                        else:
                            interface_dict['ip_address'] = parts[1]

        # Letztes Interface speichern
        if interface_dict:
            interface_dict_list.append(interface_dict)

    print(f"{len(interface_dict_list)} Interfaces erkannt.")
    return interface_dict_list


def config_dhcp_relay(interface_dict: dict, interface_name: str) -> str:
    try:
        if '.' in interface_dict['subnet_mask']:
            # Alte Syntax mit Maske
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
                set dhcp-relay-ip {' '.join(interface_dict['dhcp_relay_list'])}
                set dhcp-relay-request-all-server enable
                set interface "{interface_name}"
                set vlanid {interface_dict['vlan_id']}
            next
            """
        else:
            # Neue Syntax mit CIDR
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
                set dhcp-relay-ip {' '.join(interface_dict['dhcp_relay_list'])}
                set dhcp-relay-request-all-server enable
                set interface "{interface_name}"
                set vlanid {interface_dict['vlan_id']}
            next
            """
    except Exception as e:
        print(f'Überspringe Interface mit DHCP relay VLAN {interface_dict.get("vlan_id", "unknown")}: {e}')
        config = ''
    return config


def config_no_dhcp_relay(interface_dict: dict, interface_name: str) -> str:
    try:
        if '.' in interface_dict['subnet_mask']:
            # Alte Syntax mit Maske
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
            # Neue Syntax mit CIDR
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
        print(f'Überspringe Interface ohne DHCP relay VLAN {interface_dict.get("vlan_id", "unknown")}: {e}')
        config = ''
    return config


def create_forti_interface(interface_dict_list: list, interface_name: str):
    with open('output/forti_config.txt', 'w+') as f:
        for interface_dict in interface_dict_list:
            print(f"Verarbeite VLAN {interface_dict.get('vlan_id', 'unknown')}")
            if interface_dict['dhcp_relay_exists']:
                config = config_dhcp_relay(interface_dict, interface_name)
                f.write(config)
            else:
                config = config_no_dhcp_relay(interface_dict, interface_name)
                f.write(config)
    print("Konfiguration erfolgreich erstellt → output/forti_config.txt")


if __name__ == '__main__':
    input_file = 'input/input_nexus.txt'
    parsed_info = parse_cisco_interface(input_file)
    # Erste Zeile = Uplink
    with open(input_file) as f:
        lacp_name = f.readline().strip()
    create_forti_interface(parsed_info, interface_name=lacp_name)
