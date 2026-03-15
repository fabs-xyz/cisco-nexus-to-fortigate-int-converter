# Cisco Nexus to FortiGate Converter

A Python script that reads **Cisco Nexus interface configurations** (old and new NX-OS syntax) and automatically generates the matching **FortiGate interface configuration**.  
It handles **VLANs, IP addresses, DHCP relays, multiple secondary IPs, and aliases** out of the box.

---

## ✨ Features
- Supports **old** and **new** Cisco Nexus NX-OS syntax:
  - `ip address <IP> <MASK>` (old / dotted-mask style)
  - `ip address <IP>/<CIDR>` (new / prefix-length style)
- Automatically detects interface blocks (with or without `!` as separator)
- Converts **DHCP relay settings** (`ip helper-address` & `ip dhcp relay address`, including multi-line continuation)
- Supports **multiple secondary IP addresses** (`ip address <IP> secondary`)
- Supports **HSRP / standby IPs** — the virtual IP is used as a fallback only when no real IP is configured; HSRP secondary IPs map to FortiGate secondary IPs
- Validates every parsed IPv4 address (rejects out-of-range octets)
- Automatically trims **alias/description** to max **25 characters**
- Wraps output in a proper `config system interface` / `end` block
- Clean, consistently-indented output ready to paste into FortiGate CLI
- **CLI arguments** — no more editing the script to change paths or interface names

---

## 📂 Project structure
```
cisco-nexus-to-fortigate-converter/
│── input/
│   └── input_nexus.txt          # Cisco Nexus interface configuration
│── output/
│   └── forti_config.txt         # Generated FortiGate configuration
│── nexus-interface_parser.py    # Main script
│── tests/
│   └── test_parser.py           # pytest test suite
│── requirements.txt
│── README.md
```

---

## 🚀 Usage

### Default (uses `input/input_nexus.txt` → `output/forti_config.txt`)
```bash
python3 nexus-interface_parser.py
```

### Custom paths and interface name
```bash
python3 nexus-interface_parser.py \
  --input  /path/to/nexus_config.txt \
  --output /path/to/forti_config.txt \
  --interface ae1
```

| Argument | Short | Description |
|---|---|---|
| `--input` | `-i` | Path to the Cisco Nexus input file (default: `input/input_nexus.txt`) |
| `--output` | `-o` | Path for the generated FortiGate config (default: `output/forti_config.txt`) |
| `--interface` | `-n` | FortiGate parent interface / LAG name (e.g. `ae1`). Overrides the first line of the input file. |

---

## ⚠️ Note on Interface / LAG Name

When `--interface` is **not** provided the script reads the **first line** of the input file as the parent interface name (e.g. `ae1` or `port-channel1`).  
This name is used for all VLAN sub-interfaces generated from the Cisco Nexus configuration.

**Example input file:**
```
ae1
interface Vlan12
 description 192.168.178__House
 ip address 192.168.178.2/24
 ip dhcp relay address 192.168.178.80
```
- `ae1` → becomes the parent interface name on FortiGate.
- All VLANs (like Vlan12) will reference this interface in their configuration.

💡 Pass `--interface <name>` on the command line to override the first-line convention entirely.

---

## 📖 Example Output

### Input (Cisco Nexus):
```
ae1
interface Vlan12
 description 192.168.178__House
 ip address 192.168.178.2/24
 ip dhcp relay address 192.168.178.80
!
interface Vlan10
 description Corp LAN
 ip address 10.0.0.1/24
 ip address 10.0.0.254/24 secondary
!
```

### Output (FortiGate):
```
config system interface
edit "VL.12"
    set vdom "root"
    set dhcp-relay-service enable
    set ip 192.168.178.2/24
    set allowaccess ping
    set status down
    set alias "192.168.178__House"
    set device-identification enable
    set role lan
    set dhcp-relay-ip "192.168.178.80"
    set dhcp-relay-request-all-server enable
    set interface "ae1"
    set vlanid 12
next
edit "VL.10"
    set vdom "root"
    set ip 10.0.0.1/24
    set allowaccess ping
    set status down
    set alias "Corp LAN"
    set device-identification enable
    set role lan
    set interface "ae1"
    set vlanid 10
    set secondary-IP enable
    config secondaryip
        edit 1
            set ip 10.0.0.254/24
            set allowaccess ping
        next
    end
next
end
```

---

## 🧪 Running Tests

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v
```
