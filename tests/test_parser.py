"""Tests for nexus-interface_parser (nexus_interface_parser)."""
import importlib
import os
import sys
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Import the module under test (filename contains a hyphen)
# ---------------------------------------------------------------------------
_MODULE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'nexus-interface_parser.py'
)
_spec = importlib.util.spec_from_file_location('nexus_interface_parser', _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

parse_cisco_interface = _mod.parse_cisco_interface
create_forti_interface = _mod.create_forti_interface
_render_interface_block = _mod._render_interface_block
validate_ipv4 = _mod.validate_ipv4
_ip_str = _mod._ip_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_input(tmp_path, content: str, filename: str = 'nexus.txt') -> str:
    """Write *content* to a temp file and return its path."""
    p = tmp_path / filename
    p.write_text(textwrap.dedent(content), encoding='utf-8')
    return str(p)


# ---------------------------------------------------------------------------
# validate_ipv4
# ---------------------------------------------------------------------------

class TestValidateIpv4:
    def test_valid(self):
        assert validate_ipv4('192.168.1.1')
        assert validate_ipv4('0.0.0.0')
        assert validate_ipv4('255.255.255.255')
        assert validate_ipv4('10.0.0.1')

    def test_invalid_octet(self):
        assert not validate_ipv4('256.0.0.1')
        assert not validate_ipv4('192.168.1.999')

    def test_invalid_format(self):
        assert not validate_ipv4('not-an-ip')
        assert not validate_ipv4('192.168.1')
        assert not validate_ipv4('')


# ---------------------------------------------------------------------------
# _ip_str
# ---------------------------------------------------------------------------

class TestIpStr:
    def test_dotted_mask(self):
        assert _ip_str('192.168.1.1', '255.255.255.0') == '192.168.1.1 255.255.255.0'

    def test_cidr(self):
        assert _ip_str('10.0.0.1', '24') == '10.0.0.1/24'


# ---------------------------------------------------------------------------
# parse_cisco_interface
# ---------------------------------------------------------------------------

class TestParseCiscoInterface:
    """Unit tests for the parser."""

    def test_basic_cidr(self, tmp_path):
        src = '''\
            ae1
            interface Vlan12
             description Corp LAN
             ip address 192.168.178.2/24
             ip dhcp relay address 192.168.178.80
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        assert len(result) == 1
        iface = result[0]
        assert iface['vlan_id'] == '12'
        assert iface['ip_address'] == '192.168.178.2'
        assert iface['subnet_mask'] == '24'
        assert iface['description'] == 'Corp LAN'
        assert iface['dhcp_relay_exists'] is True
        assert iface['dhcp_relay_list'] == ['192.168.178.80']

    def test_basic_dotted_mask(self, tmp_path):
        src = '''\
            ae1
            interface Vlan10
             ip address 10.0.0.1 255.255.255.0
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        assert len(result) == 1
        iface = result[0]
        assert iface['ip_address'] == '10.0.0.1'
        assert iface['subnet_mask'] == '255.255.255.0'

    def test_secondary_ip_dotted(self, tmp_path):
        """Secondary IP should NOT overwrite the primary IP."""
        src = '''\
            ae1
            interface Vlan10
             ip address 10.0.0.1 255.255.255.0
             ip address 10.0.0.254 255.255.255.0 secondary
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        iface = result[0]
        assert iface['ip_address'] == '10.0.0.1'
        assert len(iface['secondary_list']) == 1
        assert iface['secondary_list'][0]['ip'] == '10.0.0.254'
        assert iface['secondary_list'][0]['mask'] == '255.255.255.0'

    def test_secondary_ip_cidr(self, tmp_path):
        src = '''\
            ae1
            interface Vlan10
             ip address 10.0.0.1/24
             ip address 10.0.0.254/24 secondary
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        iface = result[0]
        assert iface['ip_address'] == '10.0.0.1'
        assert iface['secondary_list'][0]['ip'] == '10.0.0.254'

    def test_multiple_secondary_ips(self, tmp_path):
        src = '''\
            ae1
            interface Vlan10
             ip address 10.0.0.1/24
             ip address 10.0.0.2/24 secondary
             ip address 10.0.0.3/24 secondary
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        iface = result[0]
        assert iface['ip_address'] == '10.0.0.1'
        ips = [s['ip'] for s in iface['secondary_list']]
        assert '10.0.0.2' in ips
        assert '10.0.0.3' in ips

    def test_hsrp_does_not_overwrite_real_ip(self, tmp_path):
        """HSRP virtual IP must not overwrite the real interface IP."""
        src = '''\
            ae1
            interface Vlan10
             ip address 10.0.0.1/24
             standby 1 ip 10.0.0.254
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        iface = result[0]
        assert iface['ip_address'] == '10.0.0.1'

    def test_hsrp_used_as_fallback_when_no_real_ip(self, tmp_path):
        """HSRP virtual IP should be used when there is no real IP configured."""
        src = '''\
            ae1
            interface Vlan10
             standby 1 ip 10.0.0.254
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        iface = result[0]
        assert iface['ip_address'] == '10.0.0.254'

    def test_hsrp_secondary_standby(self, tmp_path):
        src = '''\
            ae1
            interface Vlan10
             ip address 10.0.0.1/24
             standby 1 ip 10.0.0.200
             standby 1 ip 10.0.0.201 secondary
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        iface = result[0]
        assert iface['ip_address'] == '10.0.0.1'
        ips = [s['ip'] for s in iface['secondary_list']]
        assert '10.0.0.201' in ips

    def test_multiple_helper_addresses(self, tmp_path):
        src = '''\
            ae1
            interface Vlan20
             ip address 10.20.0.1/24
             ip helper-address 10.1.1.10
             ip helper-address 10.1.1.20
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        iface = result[0]
        assert iface['dhcp_relay_exists'] is True
        assert '10.1.1.10' in iface['dhcp_relay_list']
        assert '10.1.1.20' in iface['dhcp_relay_list']

    def test_pending_dhcp_relay_continuation(self, tmp_path):
        """IPs on the continuation line after 'ip dhcp relay address' must be captured."""
        src = '''\
            ae1
            interface Vlan30
             ip address 10.30.0.1/24
             ip dhcp relay address
              10.2.2.1 10.2.2.2
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        iface = result[0]
        assert iface['dhcp_relay_exists'] is True
        assert '10.2.2.1' in iface['dhcp_relay_list']
        assert '10.2.2.2' in iface['dhcp_relay_list']

    def test_no_ip_address_ignored(self, tmp_path):
        """'no ip address' must not crash and must not set an IP."""
        src = '''\
            ae1
            interface Vlan10
             no ip address
             ip address 10.0.0.1/24
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        iface = result[0]
        assert iface['ip_address'] == '10.0.0.1'

    def test_alias_truncated_to_25_chars(self, tmp_path):
        src = '''\
            ae1
            interface Vlan10
             description This is a very long description that exceeds 25 chars
             ip address 10.0.0.1/24
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        assert len(result[0]['description']) <= 25

    def test_multiple_interfaces(self, tmp_path):
        src = '''\
            ae1
            interface Vlan10
             ip address 10.0.0.1/24
            !
            interface Vlan20
             ip address 10.20.0.1/24
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        assert len(result) == 2
        vlan_ids = {i['vlan_id'] for i in result}
        assert vlan_ids == {'10', '20'}

    def test_no_trailing_bang(self, tmp_path):
        """Last interface block without trailing '!' must still be captured."""
        src = '''\
            ae1
            interface Vlan10
             ip address 10.0.0.1/24
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        assert len(result) == 1
        assert result[0]['vlan_id'] == '10'

    def test_missing_file_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            parse_cisco_interface(str(tmp_path / 'nonexistent.txt'))
        assert exc_info.value.code == 1

    def test_invalid_ip_rejected(self, tmp_path):
        """Octets outside 0-255 must not be stored as ip_address."""
        src = '''\
            ae1
            interface Vlan10
             ip address 999.0.0.1/24
            !
        '''
        result = parse_cisco_interface(_write_input(tmp_path, src))
        assert 'ip_address' not in result[0]


# ---------------------------------------------------------------------------
# _render_interface_block
# ---------------------------------------------------------------------------

class TestRenderInterfaceBlock:
    def _base(self, overrides=None):
        d = {
            'vlan_id': '10',
            'ip_address': '10.0.0.1',
            'subnet_mask': '24',
            'description': 'Test',
            'dhcp_relay_exists': False,
            'dhcp_relay_list': [],
            'secondary_list': [],
        }
        if overrides:
            d.update(overrides)
        return d

    def test_cidr_output(self):
        block = _render_interface_block(self._base(), 'ae1')
        assert 'set ip 10.0.0.1/24' in block
        assert 'edit "VL.10"' in block
        assert 'set interface "ae1"' in block
        assert 'set vlanid 10' in block
        assert block.startswith('edit')
        assert block.strip().endswith('next')

    def test_dotted_mask_output(self):
        block = _render_interface_block(
            self._base({'subnet_mask': '255.255.255.0'}), 'ae1'
        )
        assert 'set ip 10.0.0.1 255.255.255.0' in block

    def test_dhcp_relay_block(self):
        d = self._base({
            'dhcp_relay_exists': True,
            'dhcp_relay_list': ['10.1.1.1', '10.1.1.2'],
        })
        block = _render_interface_block(d, 'ae1')
        assert 'set dhcp-relay-service enable' in block
        assert '"10.1.1.1"' in block
        assert '"10.1.1.2"' in block
        assert 'set dhcp-relay-request-all-server enable' in block

    def test_secondary_ip_block(self):
        d = self._base({
            'secondary_list': [{'ip': '10.0.0.254', 'mask': '24'}],
        })
        block = _render_interface_block(d, 'ae1')
        assert 'set secondary-IP enable' in block
        assert 'config secondaryip' in block
        assert 'set ip 10.0.0.254/24' in block

    def test_multiple_secondary_ips(self):
        d = self._base({
            'secondary_list': [
                {'ip': '10.0.0.2', 'mask': '24'},
                {'ip': '10.0.0.3', 'mask': '24'},
            ],
        })
        block = _render_interface_block(d, 'ae1')
        assert 'edit 1' in block
        assert 'edit 2' in block
        assert 'set ip 10.0.0.2/24' in block
        assert 'set ip 10.0.0.3/24' in block

    def test_missing_ip_returns_empty(self):
        d = self._base()
        del d['ip_address']
        block = _render_interface_block(d, 'ae1')
        assert block == ''

    def test_no_secondary_in_dhcp_relay_block(self):
        """Secondary IPs must not be emitted when DHCP relay is active."""
        d = self._base({
            'dhcp_relay_exists': True,
            'dhcp_relay_list': ['10.1.1.1'],
            'secondary_list': [{'ip': '10.0.0.2', 'mask': '24'}],
        })
        block = _render_interface_block(d, 'ae1')
        assert 'secondary-IP' not in block

    def test_config_system_interface_wrapper(self, tmp_path):
        """Output file must be wrapped with 'config system interface' / 'end'."""
        ifaces = [{
            'vlan_id': '10',
            'ip_address': '10.0.0.1',
            'subnet_mask': '24',
            'description': 'Test',
            'dhcp_relay_exists': False,
            'dhcp_relay_list': [],
            'secondary_list': [],
        }]
        out = str(tmp_path / 'out.txt')
        create_forti_interface(ifaces, 'ae1', output_path=out)
        with open(out, encoding='utf-8') as fh:
            content = fh.read()
        assert content.startswith('config system interface\n')
        assert content.strip().endswith('end')
