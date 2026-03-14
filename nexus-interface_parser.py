import argparse
import copy
import os
import re
import sys

# IPv4 regex: matches IPv4 patterns only (no adjacent digits)
IP_RE = re.compile(r'(?<!\d)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?!\d)')


def validate_ipv4(ip: str) -> bool:
    """Return True if *ip* is a valid IPv4 address (each octet 0-255)."""
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def _ip_str(ip: str, mask: str) -> str:
    """Format an IP + mask as either 'a.b.c.d e.f.g.h' or 'a.b.c.d/prefix'."""
    if '.' in mask:
        return f"{ip} {mask}"
    return f"{ip}/{mask}"


def parse_cisco_interface(input_path: str):
    """Parse a Cisco Nexus interface config file and return a list of interface dicts.

    Each dict contains:
      vlan_id          – VLAN number (string)
      ip_address       – primary IPv4 address (string, optional)
      subnet_mask      – mask in dotted or CIDR prefix form (string, optional)
      description      – interface description truncated to 25 chars (string, optional)
      dhcp_relay_exists – True when DHCP relay addresses were found (bool)
      dhcp_relay_list  – list of relay server IPs (list of str)
      secondary_list   – list of secondary IPv4 addresses, each as
                         {'ip': str, 'mask': str} (list of dict)
    """
    if not os.path.isfile(input_path):
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print('Starting parse...')
    interface_dict_list = []
    interface_dict = None
    # Marker: previous line was "ip dhcp relay address" without trailing IPs
    pending_dhcp_relay = False

    with open(input_path, encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()

            # Skip blank lines
            if not stripped:
                continue

            # End of block (legacy NX-OS style uses "!" as separator)
            if stripped.startswith("!"):
                if interface_dict:
                    interface_dict_list.append(copy.deepcopy(interface_dict))
                    interface_dict = None
                pending_dhcp_relay = False
                continue

            # New interface block starts
            if stripped.startswith("interface"):
                if interface_dict:
                    interface_dict_list.append(copy.deepcopy(interface_dict))
                interface_dict = {
                    'dhcp_relay_list': [],
                    'dhcp_relay_exists': False,
                    'secondary_list': [],
                }
                pending_dhcp_relay = False
                parts = stripped.split()
                if len(parts) >= 2:
                    vlan_id = parts[1].replace("Vlan", "")
                    interface_dict['vlan_id'] = vlan_id
                continue

            # Lines outside any interface block (e.g. the parent interface name)
            if interface_dict is None:
                continue

            # Continuation line after a bare "ip dhcp relay address" (no IPs on that line)
            if pending_dhcp_relay:
                ips = [ip for ip in IP_RE.findall(stripped) if validate_ipv4(ip)]
                if ips:
                    interface_dict['dhcp_relay_exists'] = True
                    interface_dict['dhcp_relay_list'].extend(ips)
                    pending_dhcp_relay = False
                    continue

            if stripped.startswith("description"):
                desc = stripped[len("description"):].strip()
                # FortiGate alias is limited to 25 characters
                interface_dict['description'] = desc[:25]

            elif stripped == "no ip address":
                # Clears the IP — nothing to store
                pass

            elif stripped.startswith("ip address"):
                parts = stripped.split()
                is_secondary = 'secondary' in parts
                try:
                    raw = parts[2]  # either "a.b.c.d" or "a.b.c.d/prefix"
                    if '/' in raw:
                        ip, mask = raw.split('/', 1)
                    else:
                        ip = raw
                        mask = parts[3] if len(parts) >= 4 else ''
                    if validate_ipv4(ip) and mask:
                        if is_secondary:
                            interface_dict['secondary_list'].append({'ip': ip, 'mask': mask})
                        else:
                            interface_dict['ip_address'] = ip
                            interface_dict['subnet_mask'] = mask
                except (IndexError, ValueError):
                    pass

            elif stripped.startswith("ip helper-address") or stripped.startswith("ip dhcp relay address"):
                ips = [ip for ip in IP_RE.findall(stripped) if validate_ipv4(ip)]
                if ips:
                    interface_dict['dhcp_relay_exists'] = True
                    interface_dict['dhcp_relay_list'].extend(ips)
                else:
                    # IPs may be on the next continuation line, e.g.:
                    #   ip dhcp relay address
                    #     10.1.1.10 10.1.1.20
                    pending_dhcp_relay = True

            elif stripped.startswith("standby"):
                # Legacy HSRP syntax: standby <group> ip <IP> [secondary]
                parts = stripped.split()
                try:
                    if parts[2] == "ip" and validate_ipv4(parts[3]):
                        is_secondary = len(parts) > 4 and parts[4] == "secondary"
                        mask = interface_dict.get('subnet_mask', '')
                        if is_secondary:
                            interface_dict['secondary_list'].append({'ip': parts[3], 'mask': mask})
                        elif 'ip_address' not in interface_dict:
                            # Only use HSRP virtual IP when no real IP has been parsed yet
                            interface_dict['ip_address'] = parts[3]
                except IndexError:
                    pass

            elif stripped.startswith("hsrp"):
                # NX-OS inline HSRP syntax: hsrp <group> ipv4 <IP>
                parts = stripped.split()
                if len(parts) >= 4 and validate_ipv4(parts[3]):
                    if 'ip_address' not in interface_dict:
                        interface_dict['ip_address'] = parts[3]

    # Save the last interface block (no trailing "!" in some configs)
    if interface_dict:
        interface_dict_list.append(interface_dict)

    print(f"Detected {len(interface_dict_list)} interfaces.")
    return interface_dict_list


def _render_dhcp_relay_list(dhcp_list):
    """Build a space-separated quoted list of DHCP relay IPs for FortiOS."""
    return ' '.join('"' + str(ip).strip().strip('"') + '"' for ip in dhcp_list)


def _render_interface_block(interface_dict: dict, interface_name: str) -> str:
    """Render a single FortiGate 'edit … next' block for one VLAN interface."""
    vlan_id = interface_dict.get('vlan_id', 'unknown')
    ip = interface_dict.get('ip_address', '')
    mask = interface_dict.get('subnet_mask', '')
    description = interface_dict.get('description', '')
    dhcp_relay_exists = interface_dict.get('dhcp_relay_exists', False)
    dhcp_relay_list = interface_dict.get('dhcp_relay_list', [])
    secondary_list = interface_dict.get('secondary_list', [])

    if not ip or not mask:
        print(f"  Skipping VLAN {vlan_id}: missing IP address or subnet mask.")
        return ''

    lines = [
        f'edit "VL.{vlan_id}"',
        '    set vdom "root"',
    ]

    if dhcp_relay_exists:
        lines.append('    set dhcp-relay-service enable')

    lines.append(f'    set ip {_ip_str(ip, mask)}')
    lines.append('    set allowaccess ping')
    lines.append('    set status down')

    if description:
        lines.append(f'    set alias "{description}"')

    lines.append('    set device-identification enable')
    lines.append('    set role lan')

    if dhcp_relay_exists:
        lines.append(f'    set dhcp-relay-ip {_render_dhcp_relay_list(dhcp_relay_list)}')
        lines.append('    set dhcp-relay-request-all-server enable')

    lines.append(f'    set interface "{interface_name}"')
    lines.append(f'    set vlanid {vlan_id}')

    if not dhcp_relay_exists and secondary_list:
        lines.append('    set secondary-IP enable')
        lines.append('    config secondaryip')
        for idx, sec in enumerate(secondary_list, start=1):
            sec_mask = sec.get('mask') or mask  # fall back to primary mask
            lines.append(f'        edit {idx}')
            lines.append(f'            set ip {_ip_str(sec["ip"], sec_mask)}')
            lines.append('            set allowaccess ping')
            lines.append('        next')
        lines.append('    end')

    lines.append('next')
    return '\n'.join(lines) + '\n'


def create_forti_interface(interface_dict_list: list, interface_name: str,
                           output_path: str = 'output/forti_config.txt'):
    """Write the FortiGate 'config system interface' block to *output_path*."""
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('config system interface\n')
        for interface_dict in interface_dict_list:
            print(f"Processing VLAN {interface_dict.get('vlan_id', 'unknown')}")
            block = _render_interface_block(interface_dict, interface_name)
            if block:
                f.write(block)
        f.write('end\n')
    print(f"Configuration successfully created → {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Convert Cisco Nexus interface config to FortiGate CLI syntax.'
    )
    parser.add_argument(
        '--input', '-i',
        default='input/input_nexus.txt',
        help='Path to the Cisco Nexus input file (default: input/input_nexus.txt). '
             'The first line of this file is used as the FortiGate parent interface name '
             '(e.g. "ae1") unless --interface is specified.',
    )
    parser.add_argument(
        '--output', '-o',
        default='output/forti_config.txt',
        help='Path for the generated FortiGate config file (default: output/forti_config.txt).',
    )
    parser.add_argument(
        '--interface', '-n',
        default=None,
        help='FortiGate parent interface / LAG name (e.g. "ae1"). '
             'Overrides the first line of the input file.',
    )
    args = parser.parse_args()

    parsed_info = parse_cisco_interface(args.input)

    if args.interface:
        interface_name = args.interface
    else:
        with open(args.input, encoding='utf-8') as f:
            interface_name = f.readline().strip()

    create_forti_interface(parsed_info, interface_name=interface_name,
                           output_path=args.output)


if __name__ == '__main__':
    main()
