# Cisco Nexus to FortiGate Converter

A Python script that reads **Cisco Nexus interface configurations** (old and new NX-OS syntax) and automatically generates the matching **FortiGate interface configuration**.  
It handles **VLANs, IP addresses, DHCP relays, secondary IPs, and aliases** out of the box.  

---

## ✨ Features
- Supports **old** and **new** Cisco Nexus NX-OS syntax:
  - `ip address <IP> <MASK>` (old style)
  - `ip address <IP>/<CIDR>` (new style)
- Automatically detects interface blocks (with or without `!` as separator)
- Converts **DHCP relay settings** (`ip helper-address` & `ip dhcp relay address`)
- Supports **HSRP IPs** (including secondary addresses)
- Automatically trims **alias/description** to max **25 characters**
- Generates FortiGate `config system interface` blocks

---

## 📂 Project structure
```
cisco-nexus-to-fortigate-converter/
│── input/
│ └── input_nexus.txt # Cisco Nexus interface configuration
│── output/
│ └── forti_config.txt # Generated FortiGate configuration
│── main.py # Main script
│── README.md # This file
```
---


## ⚠️ Note on Interface / LAG Name

The script reads the **first line of your input file** (`input/input_nexus.txt`) as the name of the **FortiGate interface or LAG** (for example `ae1` or `port-channel1`).  
This name will be used for all VLANs parsed from the Cisco Nexus configuration.  

**Example:** 
```
ae1
interface Vlan12
description 192.168.178__House
ip address 192.168.178.2/24
ip dhcp relay address 192.168.178.80
```
- `ae1` → becomes the parent interface name on FortiGate.  
- All VLANs (like Vlan12) will reference this interface in their configuration.  

💡 If you want to use a different interface or LAG name, simply change the **first line** of your input file.


---
## 📖 Example Output

### Input (Cisco Nexus):
```
interface Vlan12
description 192.168.178__House
ip address 192.168.178.2/24
ip dhcp relay address 192.168.178.80
```

### Output (FortiGate):
```
edit "VL.12"
set vdom "root"
set dhcp-relay-service enable
set ip 192.168.178.2/24
set alias "192.168.178__House"
set dhcp-relay-ip "192.168.178.80"
set interface "ae1"
set vlanid 12
next
```
