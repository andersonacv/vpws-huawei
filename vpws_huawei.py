#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPWS Automation for Huawei VRP devices
Supports VLAN, VLANIF and Pseudowire (L2VPN Martini) configuration
"""

import sys
import re
import getpass
import ipaddress
from typing import Optional

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import (
        NetMikoTimeoutException,
        NetMikoAuthenticationException,
    )
except ImportError:
    print("[ERROR] 'netmiko' library not found.")
    print("        Install with: pip install netmiko")
    sys.exit(1)


# =============================================================================
# UTILITIES
# =============================================================================

def banner():
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║           VPWS AUTOMATION — HUAWEI VRP                   ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()


def ok(msg: str):
    print(f"  [OK]      {msg}")


def error(msg: str):
    print(f"  [ERROR]   {msg}")


def info(msg: str):
    print(f"  [INFO]    {msg}")


def warning(msg: str):
    print(f"  [WARNING] {msg}")


def section(title: str):
    print(f"\n  ── {title} {'─' * (52 - len(title))}")


def get_valid_ip(prompt: str) -> str:
    while True:
        value = input(f"  {prompt}").strip()
        try:
            ipaddress.ip_address(value)
            return value
        except ValueError:
            error(f"Invalid IP: '{value}'. Please try again.")


def get_valid_vlan(prompt: str) -> int:
    while True:
        try:
            vlan = int(input(f"  {prompt}").strip())
            if 1 <= vlan <= 4094:
                return vlan
            error("VLAN must be between 1 and 4094.")
        except ValueError:
            error("Please enter a valid integer.")


def get_valid_int(prompt: str, minimum: int = 1) -> int:
    while True:
        try:
            value = int(input(f"  {prompt}").strip())
            if value >= minimum:
                return value
            error(f"Minimum value is {minimum}.")
        except ValueError:
            error("Please enter a valid integer.")


def confirm(prompt: str, default: bool = True) -> bool:
    suffix = "(Y/n)" if default else "(y/N)"
    response = input(f"  {prompt} {suffix}: ").strip().lower()
    if not response:
        return default
    return response in ("y", "yes")


# =============================================================================
# CONNECTION
# =============================================================================

def connect(ip: str, username: str, password: str, port: int = 22) -> Optional[object]:
    device = {
        "device_type": "huawei_vrp",
        "host": ip,
        "username": username,
        "password": password,
        "port": port,
        "timeout": 30,
        "session_timeout": 60,
        "global_delay_factor": 2,
        "fast_cli": False,
    }
    try:
        info(f"Connecting to {ip}:{port}...")
        conn = ConnectHandler(**device)
        hostname = conn.find_prompt().strip("<>[]#\n\r ")
        ok(f"Connected to '{hostname}' ({ip})")
        return conn
    except NetMikoTimeoutException:
        error(f"Timeout connecting to {ip}. Check connectivity/SSH port.")
    except NetMikoAuthenticationException:
        error(f"Authentication failure on {ip}. Check username and password.")
    except Exception as exc:
        error(f"Failed to connect to {ip}: {exc}")
    return None


# =============================================================================
# VLAN CHECK
# =============================================================================

def check_vlan(conn, vlan_id: int) -> bool:
    """Returns True if it is safe to proceed (VLAN free or user accepts overwrite)."""
    output = conn.send_command(f"display vlan {vlan_id}")
    not_found = any(
        term in output.lower()
        for term in ("does not exist", "not found", "error", "wrong parameter")
    )

    if not_found:
        info(f"VLAN {vlan_id} does not exist — will be created.")
        return True

    warning(f"VLAN {vlan_id} already exists on device:")
    for line in output.splitlines()[:8]:
        if line.strip():
            print(f"      {line}")

    return confirm(f"  VLAN {vlan_id} already exists. Continue anyway?", default=False)


# =============================================================================
# INTERFACE LISTING
# =============================================================================

# Matches: <interface> <physical> <protocol> [description]
# "display interface description" output format on Huawei VRP
_IFACE_PATTERN = re.compile(
    r"^((?:GigabitEthernet|XGigabitEthernet|XGE|10GE|40GE|100GE|"
    r"Eth-Trunk|Ethernet|GE)\d[\d/]*)\s+(\S+)\s+(\S+)\s*(.*)",
    re.IGNORECASE,
)

# Abbreviated names shown by VRP → full names required in config commands
_IFACE_EXPAND = {
    "GE":   "GigabitEthernet",
    "XGE":  "XGigabitEthernet",
    "10GE": "10GigabitEthernet",
    "40GE": "40GigabitEthernet",
    "100GE": "100GigabitEthernet",
}

_IFACE_ABBREV_RE = re.compile(
    r"^(GE|XGE|10GE|40GE|100GE)(\d.*)", re.IGNORECASE
)


def expand_iface_name(name: str) -> str:
    """Expands abbreviated Huawei interface names to their full form."""
    m = _IFACE_ABBREV_RE.match(name)
    if m:
        abbrev = m.group(1).upper()
        rest   = m.group(2)
        return _IFACE_EXPAND.get(abbrev, abbrev) + rest
    return name


def list_interfaces(conn) -> list:
    output = conn.send_command("display interface description")
    interfaces = []
    idx = 1

    print()
    print(f"  {'#':<4} {'Interface':<28} {'PHY':<7} {'Proto':<7} {'Description'}")
    print(f"  {'─' * 4} {'─' * 28} {'─' * 7} {'─' * 7} {'─' * 30}")

    for line in output.splitlines():
        m = _IFACE_PATTERN.match(line.strip())
        if m:
            iface    = m.group(1)
            physical = m.group(2)
            protocol = m.group(3)
            desc     = m.group(4).strip()
            # Skip sub-interfaces and management (MEth)
            if "." not in iface and "MEth" not in iface:
                full_name = expand_iface_name(iface)
                interfaces.append(full_name)
                print(f"  {idx:<4} {iface:<28} {physical:<7} {protocol:<7} {desc}")
                idx += 1

    print()
    return interfaces


def select_interface(interfaces: list) -> str:
    while True:
        entry = input(f"  Select interface number (1-{len(interfaces)}): ").strip()
        try:
            idx = int(entry) - 1
            if 0 <= idx < len(interfaces):
                return interfaces[idx]
            error(f"Number out of range (1-{len(interfaces)}).")
        except ValueError:
            # Accept manually typed interface name
            if entry:
                full = expand_iface_name(entry)
                warning(f"Using manually typed interface: {full}")
                return full
            error("Enter a number or interface name.")


# =============================================================================
# INTERFACE TYPE DETECTION
# =============================================================================

def detect_interface_type(conn, interface: str) -> str:
    """Detects trunk, hybrid or access by querying the device."""
    port_types = ("trunk", "hybrid", "access")

    for cmd in (
        f"display interface {interface}",
        f"display current-configuration interface {interface}",
    ):
        output = conn.send_command(cmd).lower()
        for port_type in port_types:
            if f"link type: {port_type}" in output or f"port link-type {port_type}" in output:
                return port_type

    warning("Interface type not detected automatically.")
    print("  Available types:")
    print("    1. trunk")
    print("    2. hybrid")
    print("    3. access")

    while True:
        choice = input("  Select type (1-3): ").strip()
        if choice == "1":
            return "trunk"
        if choice == "2":
            return "hybrid"
        if choice == "3":
            return "access"
        error("Invalid option.")


# =============================================================================
# HUAWEI CONFIGURATION
# =============================================================================

def create_vlan(conn, vlan_id: int, description: str = "") -> bool:
    commands = [f"vlan {vlan_id}"]
    if description:
        commands.append(f"description {description}")
    commands.append("quit")

    info(f"Creating VLAN {vlan_id}...")
    output = conn.send_config_set(commands)

    if "error" in output.lower():
        error(f"Failed to create VLAN {vlan_id}:\n{output}")
        return False

    ok(f"VLAN {vlan_id} created.")
    return True


def create_vlanif(conn, vlan_id: int, description: str = "") -> bool:
    commands = [f"interface vlanif {vlan_id}"]
    if description:
        commands.append(f"description {description}")
    commands.append("quit")

    info(f"Creating interface Vlanif{vlan_id}...")
    output = conn.send_config_set(commands)

    if "error" in output.lower():
        error(f"Failed to create Vlanif{vlan_id}:\n{output}")
        return False

    ok(f"Vlanif{vlan_id} created.")
    return True


def configure_interface_vlan(conn, interface: str, vlan_id: int, port_type: str,
                             hybrid_mode: str = "tagged") -> bool:
    """
    Allows the VLAN on the interface according to its type (trunk/hybrid/access).
    hybrid_mode is only used when port_type == 'hybrid': 'tagged' or 'untagged'.
    """
    commands = [f"interface {interface}"]

    if port_type == "trunk":
        commands.append(f"port trunk allow-pass vlan {vlan_id}")
    elif port_type == "hybrid":
        commands.append(f"port hybrid {hybrid_mode} vlan {vlan_id}")
    elif port_type == "access":
        commands.append(f"port default vlan {vlan_id}")

    commands.append("quit")

    info(f"Configuring VLAN {vlan_id} on interface {interface} (type: {port_type.upper()})...")
    output = conn.send_config_set(commands)

    if "error" in output.lower():
        error(f"Failed to configure interface:\n{output}")
        return False

    ok(f"Interface {interface} allowed for VLAN {vlan_id}.")
    return True


def configure_pseudowire(conn, vlan_id: int, peer_ip: str, vc_id: int) -> bool:
    """
    Configures VPWS Pseudowire (L2VPN Martini) directly on the Vlanif.
    Structure:
        interface Vlanif<vlan>
          mpls l2vc <peer-ip> <vc-id> control-word
    """
    commands = [
        f"interface vlanif {vlan_id}",
        f"mpls l2vc {peer_ip} {vc_id} control-word",
        "quit",
    ]

    info(f"Configuring Pseudowire on Vlanif{vlan_id} → peer {peer_ip} VC-ID {vc_id}...")
    output = conn.send_config_set(commands)

    if "error" in output.lower():
        error(f"Failed to configure Pseudowire:\n{output}")
        warning("Make sure MPLS L2VPN is enabled globally (mpls l2vpn).")
        return False

    ok(f"Pseudowire configured: Vlanif{vlan_id} ↔ {peer_ip} (VC-ID: {vc_id})")
    return True


# =============================================================================
# VERIFICATION AND SAVE
# =============================================================================

def verify_configuration(conn, vlan_id: int, interface: str):
    section("APPLIED CONFIGURATION VERIFICATION")

    blocks = [
        (f"VLAN {vlan_id}",       f"display vlan {vlan_id}"),
        (f"Vlanif{vlan_id}",      f"display current-configuration interface vlanif {vlan_id}"),
        (f"Interface {interface}", f"display current-configuration interface {interface}"),
    ]

    for title, cmd in blocks:
        print(f"\n  [{title}]")
        output = conn.send_command(cmd)
        lines = [ln for ln in output.splitlines() if ln.strip()][:12]
        for line in lines:
            print(f"    {line}")


def check_pw_status(conn, vc_id: int):
    """
    Runs 'display mpls l2vc <vc_id>' and reports whether the tunnel is UP.
    Called after the last PE is configured so both sides should be signalled.
    """
    section("PSEUDOWIRE TUNNEL STATUS CHECK")
    info(f"Running: display mpls l2vc {vc_id}")

    output = conn.send_command(f"display mpls l2vc {vc_id}")

    for line in output.splitlines():
        if line.strip():
            print(f"    {line}")

    output_lower = output.lower()
    if "up" in output_lower:
        ok(f"Tunnel VC-ID {vc_id} is UP.")
    elif "down" in output_lower:
        warning(f"Tunnel VC-ID {vc_id} is DOWN — check peer reachability and MPLS config.")
    else:
        warning(f"Could not determine tunnel state — review output above.")


def save_configuration(conn) -> bool:
    info("Saving configuration...")
    output = conn.send_command(
        "save",
        expect_string=r"[Aa]re you sure|Y/N|\?",
        delay_factor=4,
    )
    if "Are you sure" in output or "Y/N" in output or "?" in output:
        output += conn.send_command(
            "y",
            expect_string=r"successfully|>|]",
            delay_factor=4,
        )

    if "successfully" in output.lower():
        ok("Configuration saved successfully.")
        return True

    warning("Could not confirm save — please verify manually.")
    return False


# =============================================================================
# MAIN FLOW
# =============================================================================

def _collect_pe(label: str) -> dict:
    """Collects credentials and SSH port for one PE endpoint."""
    print(f"┌─ {label} ──────────────────────────────────────────────────┐")
    ip       = get_valid_ip(f"{label} IP address              : ")
    port     = get_valid_int(f"{label} SSH Port (default 22)   : ", minimum=1)
    username = input(f"  {label} SSH Username         : ").strip()
    password = getpass.getpass(f"  {label} SSH Password         : ")

    return {
        "label":    label,
        "ip":       ip,
        "port":     port,
        "username": username,
        "password": password,
    }


def collect_inputs() -> dict:
    """
    Collects all parameters before opening any SSH connections.
    VPWS is always point-to-point: exactly two PE endpoints (PE-A and PE-B).
    The PW peer IP for each side is automatically the other side's management IP.
    """
    pe_a = _collect_pe("PE-A")
    print()
    pe_b = _collect_pe("PE-B")

    # Cross-assign PW peer IPs
    pe_a["peer_ip"] = pe_b["ip"]
    pe_b["peer_ip"] = pe_a["ip"]

    print()
    print("┌─ SERVICE PARAMETERS ──────────────────────────────────────┐")
    vlan_id   = get_valid_vlan("VLAN ID (1-4094)              : ")
    vlan_desc = input( "  VLAN description (optional)   : ").strip()

    # VC-ID mirrors the VLAN ID
    vc_id = vlan_id

    print()
    print("┌─ PSEUDOWIRE (L2VPN Martini) ───────────────────────────────┐")
    info(f"VC-ID set to VLAN ID: {vc_id}")
    info(f"PE-A ({pe_a['ip']}) will use peer {pe_a['peer_ip']}")
    info(f"PE-B ({pe_b['ip']}) will use peer {pe_b['peer_ip']}")

    return {
        "devices":   [pe_a, pe_b],
        "vlan_id":   vlan_id,
        "vlan_desc": vlan_desc,
        "vc_id":     vc_id,
    }


def validate_device(device: dict, shared: dict) -> Optional[dict]:
    """
    PHASE 1 — Validation only (no config changes).
    Connects to the PE, checks VLAN availability, lists interfaces, detects type.
    Returns a dict with the collected data, or None if validation failed.
    """
    ip    = device["ip"]
    label = device["label"]

    print(f"\n  ┌─ {label} ({ip}) {'─' * (44 - len(ip))}┐")

    conn = connect(ip, device["username"], device["password"], device["port"])
    if not conn:
        return None

    result = None
    try:
        # Check VLAN
        section(f"VLAN {shared['vlan_id']} AVAILABILITY CHECK — {label}")
        if not check_vlan(conn, shared["vlan_id"]):
            warning(f"VLAN check failed on {label} — aborting.")
            return None

        # List interfaces and let user pick AC
        section(f"AC INTERFACE SELECTION — {label}")
        interfaces = list_interfaces(conn)
        if not interfaces:
            error(f"No eligible interface found on {label}.")
            return None

        ac_interface = select_interface(interfaces)
        info(f"AC interface selected: {ac_interface}")

        # Detect interface type
        section(f"INTERFACE TYPE DETECTION — {label}")
        iface_type = detect_interface_type(conn, ac_interface)
        ok(f"Type detected: {iface_type.upper()}")

        hybrid_mode = "tagged"
        if iface_type == "hybrid":
            print("    1. Tagged   (uplink/trunk between switches)")
            print("    2. Untagged (access port, tag is removed)")
            while True:
                op = input("  Add VLAN as tagged or untagged? (1/2): ").strip()
                if op == "1":
                    hybrid_mode = "tagged"
                    break
                if op == "2":
                    hybrid_mode = "untagged"
                    break
                error("Invalid option.")
            ok(f"Hybrid mode: {hybrid_mode}")

        result = {"ac_interface": ac_interface, "iface_type": iface_type, "hybrid_mode": hybrid_mode}

    except KeyboardInterrupt:
        warning("Validation interrupted by user (Ctrl+C).")
    except Exception as exc:
        error(f"Unexpected error during validation: {exc}")
    finally:
        conn.disconnect()
        info(f"Disconnected from {ip}.")

    return result


def configure_device(device: dict, shared: dict, validated: dict, is_last: bool = False) -> bool:
    """
    PHASE 2 — Configuration.
    Only called after both PEs passed validation.
    Applies VLAN, VLANIF, interface, and PW configuration.
    If is_last=True, runs a tunnel status check after saving.
    """
    ip    = device["ip"]
    label = device["label"]

    print(f"\n╔══════════════════════════════════════════════════════════╗")
    print(f"║  {label} — CONFIGURING: {ip:<38}║")
    print(f"╚══════════════════════════════════════════════════════════╝")
    info(f"PW peer: {device['peer_ip']}")

    conn = connect(ip, device["username"], device["password"], device["port"])
    if not conn:
        return False

    ac_interface = validated["ac_interface"]
    iface_type   = validated["iface_type"]
    success      = False

    try:
        # 1 — Create VLAN
        section("VLAN CREATION")
        if not create_vlan(conn, shared["vlan_id"], shared["vlan_desc"]):
            return False

        # 2 — Create VLANIF
        section("VLANIF CREATION")
        if not create_vlanif(conn, shared["vlan_id"], shared["vlan_desc"]):
            return False

        # 3 — Allow VLAN on interface (trunk / hybrid / access)
        section("INTERFACE CONFIGURATION")
        if not configure_interface_vlan(conn, ac_interface, shared["vlan_id"], iface_type,
                                        validated["hybrid_mode"]):
            return False

        # 4 — Configure Pseudowire on Vlanif (peer = the other PE's IP)
        section("PSEUDOWIRE CONFIGURATION")
        if not configure_pseudowire(conn, shared["vlan_id"], device["peer_ip"], shared["vc_id"]):
            return False

        # 5 — Verify applied configuration
        verify_configuration(conn, shared["vlan_id"], ac_interface)

        # 6 — Save
        print()
        if confirm("Save configuration on device?"):
            save_configuration(conn)

        # 7 — Check tunnel status after the last PE is configured
        if is_last:
            check_pw_status(conn, shared["vc_id"])

        success = True

    except KeyboardInterrupt:
        warning("Configuration interrupted by user (Ctrl+C).")
    except Exception as exc:
        error(f"Unexpected error: {exc}")
    finally:
        conn.disconnect()
        info(f"Disconnected from {ip}.")

    return success


def main():
    banner()

    try:
        params = collect_inputs()
    except KeyboardInterrupt:
        print("\n\n  Operation cancelled.")
        sys.exit(0)

    shared = {
        "vlan_id":   params["vlan_id"],
        "vlan_desc": params["vlan_desc"],
        "vc_id":     params["vc_id"],
    }

    # ── PHASE 1: validate VLAN on both PEs before touching anything ──────────
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║           PHASE 1 — PRE-VALIDATION (BOTH PEs)            ║")
    print("╚══════════════════════════════════════════════════════════╝")

    validated = {}
    for device in params["devices"]:
        result = validate_device(device, shared)
        if result is None:
            error(f"Validation failed on {device['label']} ({device['ip']}). Aborting.")
            sys.exit(1)
        validated[device["label"]] = result

    ok("VLAN is available on both PEs — proceeding with configuration.")

    # ── SUMMARY: show what will be applied and ask for confirmation ───────────
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║              CONFIGURATION SUMMARY                       ║")
    print("╚══════════════════════════════════════════════════════════╝")

    for device in params["devices"]:
        v = validated[device["label"]]
        vlan_id   = shared["vlan_id"]
        vlan_desc = shared["vlan_desc"]
        vc_id     = shared["vc_id"]
        iface     = v["ac_interface"]
        iface_type = v["iface_type"].upper()

        # Build the exact commands that will be sent
        if v["iface_type"] == "trunk":
            iface_vlan_cmd = f"port trunk allow-pass vlan {vlan_id}"
        elif v["iface_type"] == "hybrid":
            iface_vlan_cmd = f"port hybrid {v['hybrid_mode']} vlan {vlan_id}"
        else:
            iface_vlan_cmd = f"port default vlan {vlan_id}"

        print(f"\n  ┌─ {device['label']} ({device['ip']}) {'─' * (42 - len(device['ip']))}┐")
        print(f"  │  SSH port     : {device['port']}")
        print(f"  │  PW peer      : {device['peer_ip']}")
        print(f"  │  AC interface : {iface}  [{iface_type}]")
        print(f"  │")
        print(f"  │  Commands to be applied:")
        print(f"  │    vlan {vlan_id}")
        if vlan_desc:
            print(f"  │     description {vlan_desc}")
        print(f"  │    interface vlanif {vlan_id}")
        if vlan_desc:
            print(f"  │     description {vlan_desc}")
        print(f"  │     mpls l2vc {device['peer_ip']} {vc_id} control-word")
        print(f"  │    interface {iface}")
        print(f"  │     {iface_vlan_cmd}")
        print(f"  └{'─' * 56}┘")

    print()
    if not confirm("Apply configuration on both PEs?"):
        warning("Aborted by user. No changes were made.")
        sys.exit(0)

    # ── PHASE 2: configure both PEs ──────────────────────────────────────────
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║              PHASE 2 — CONFIGURATION                     ║")
    print("╚══════════════════════════════════════════════════════════╝")

    results = {}
    devices = params["devices"]
    for i, device in enumerate(devices):
        is_last = i == len(devices) - 1
        results[device["label"]] = (
            device["ip"],
            configure_device(device, shared, validated[device["label"]], is_last=is_last),
        )

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║                     FINAL SUMMARY                        ║")
    print("╠══════════════════════════════════════════════════════════╣")
    for label, (ip, status) in results.items():
        symbol     = "✓" if status else "✗"
        status_str = "SUCCESS" if status else "FAILED "
        print(f"║  {symbol}  {label}  {ip:<20}  {status_str}                  ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    main()
