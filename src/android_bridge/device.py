"""Device connection management via pure ADB (no on-device agent)."""

from pathlib import Path
import json
import os
import shlex
import shutil
import sys
import subprocess

CONFIG_DIR = Path.home() / ".config" / "agent-skills" / "android-bridge"
CONFIG_FILE = CONFIG_DIR / "config.json"

_profile_override: str | None = None


def set_profile_override(profile: str) -> None:
    global _profile_override
    _profile_override = profile


def _adb_cmd() -> str:
    config = _load_full_config()
    adb = config.get("adb_path", "adb")
    if not shutil.which(adb):
        search_paths = os.environ.get("PATH", "").split(os.pathsep)
        raise RuntimeError(
            f"ADB not found.\n"
            f"  Searched: {adb!r} in PATH entries:\n"
            + "".join(f"    - {p}\n" for p in search_paths[:10])
            + f"  Fix: edit {CONFIG_FILE} and set \"adb_path\": \"/path/to/adb\"\n"
            f"  Or:  sudo apt install adb"
        )
    return adb


def _adb_server_args() -> list[str]:
    """Return -H/-P args if adb_host/adb_port are configured."""
    config = _load_full_config()
    args = []
    host = config.get("adb_host")
    port = config.get("adb_port")
    if host:
        args.extend(["-H", str(host)])
    if port:
        args.extend(["-P", str(port)])
    return args


def _adb_base() -> list[str]:
    """Return base adb command with server args: ['adb', '-H', host, '-P', port]."""
    return [_adb_cmd()] + _adb_server_args()


def _resolve_profile() -> str | None:
    """Profile selection: --profile CLI flag > config.json active field."""
    if _profile_override:
        return _profile_override
    config = _load_full_config()
    return config.get("active") or None


def _load_full_config() -> dict:
    config, _ = _load_full_config_with_path()
    return config


def _load_full_config_with_path() -> tuple[dict, Path]:
    """Return (config, path_loaded_from). Path falls back to CONFIG_FILE when none exists."""
    dev_config = Path.cwd() / ".config.json"
    if dev_config.exists():
        with open(dev_config) as f:
            return json.load(f), dev_config
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f), CONFIG_FILE
    return {}, CONFIG_FILE


_cached_serial: str | None = None
_config_loaded: bool = False


def _load_config() -> str | None:
    global _cached_serial, _config_loaded
    if _config_loaded:
        return _cached_serial
    _config_loaded = True

    config = _load_full_config()
    profile = _resolve_profile()
    if profile:
        profiles = config.get("profiles", {})
        p = profiles.get(profile)
        if not p:
            raise RuntimeError(
                f"Profile '{profile}' not found. Available: {list(profiles.keys())}\n"
                f"  Fix: edit {CONFIG_FILE} and add under \"profiles\":\n"
                f'    "{profile}": {{"serial": "<ip:5555>"}}'
            )
        _cached_serial = p.get("serial")
        return _cached_serial
    device = config.get("device", {})
    if device.get("serial"):
        _cached_serial = device["serial"]
        return _cached_serial
    profiles = config.get("profiles", {})
    active = config.get("active")
    if active and active in profiles:
        _cached_serial = profiles[active].get("serial")
        return _cached_serial
    return None


def _save_config(serial: str, profile: str | None = None) -> None:
    # Write back to the SAME file we loaded from, so a dev override (.config.json in cwd)
    # doesn't lose state by having saves silently redirected to CONFIG_FILE.
    config, path = _load_full_config_with_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if profile:
        config.setdefault("profiles", {})[profile] = {"serial": serial}
        config["active"] = profile
    else:
        config.setdefault("device", {})["serial"] = serial
    path.write_text(json.dumps(config, indent=2) + "\n")


def adb(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run an adb command. args should be a list of arguments (not a string)."""
    serial = _load_config()
    cmd_parts = _adb_base()
    if serial:
        cmd_parts.extend(["-s", serial])
    cmd_parts.extend(args)
    return subprocess.run(cmd_parts, capture_output=True, text=True, timeout=timeout)


def adb_shell(cmd: str, root: bool = False, timeout: int = 30) -> str:
    serial = _load_config()
    cmd_parts = _adb_base()
    if serial:
        cmd_parts.extend(["-s", serial])
    if root:
        cmd_parts.extend(["shell", f"su -c {shlex.quote(cmd)}"])
    else:
        cmd_parts.extend(["shell", cmd])
    result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=timeout)
    output = result.stdout.strip()
    if result.returncode != 0 and not output:
        err = result.stderr.strip()
        raise RuntimeError(err or output or f"adb shell failed (exit {result.returncode})")
    return output


def adb_shell_script(script: str, root: bool = False, timeout: int = 30) -> str:
    """Execute a multi-line script on device via stdin pipe.

    Bypasses all local shell quoting issues by piping the script directly
    to adb shell's stdin. The script runs in a fresh sh on the device.
    """
    serial = _load_config()
    cmd_parts = _adb_base()
    if serial:
        cmd_parts.extend(["-s", serial])
    if root:
        cmd_parts.extend(["shell", "su"])
    else:
        cmd_parts.extend(["shell"])
    result = subprocess.run(
        cmd_parts,
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout.strip()
    if result.returncode != 0 and not output:
        err = result.stderr.strip()
        raise RuntimeError(err or f"adb shell failed (exit {result.returncode})")
    return output


def list_devices() -> list[tuple[str, str]]:
    cmd_parts = _adb_base() + ["devices"]
    result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=10)
    devices = []
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 2:
            devices.append((parts[0], parts[1]))
    return devices


def _normalize_serial(serial: str) -> str:
    if ":" not in serial:
        return f"{serial}:5555"
    return serial


def _adb_connect(serial: str) -> None:
    cmd_parts = _adb_base() + ["connect", serial]
    result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=15)
    output = (result.stdout + result.stderr).strip().lower()
    if "connected" not in output and "already" not in output:
        raise RuntimeError(f"Failed to connect: {result.stdout.strip()}")


def connect(serial: str | None = None) -> str:
    profile = _resolve_profile()
    if serial is None:
        serial = _load_config()
    if serial is None:
        devices = list_devices()
        online = [s for s, state in devices if state == "device"]
        if not online:
            raise RuntimeError(
                "No device found. Specify a serial or connect a device.\n"
                "  Fix: android-bridge connect <ip:5555>  (WiFi ADB, e.g. 192.168.1.100:5555)\n"
                "  Or:  plug in via USB and run `android-bridge connect`"
            )
        serial = online[0]
    else:
        serial = _normalize_serial(serial)
        if ":" in serial:
            _adb_connect(serial)

    cmd_parts = _adb_base() + ["-s", serial, "shell", "getprop", "ro.product.model"]
    result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=10)
    model = result.stdout.strip() or "unknown"
    _save_config(serial, profile)
    return f"{model} ({serial})"


def get_serial() -> str:
    serial = _load_config()
    if serial:
        return serial
    devices = list_devices()
    online = [s for s, state in devices if state == "device"]
    if not online:
        raise RuntimeError(
            "No device connected.\n"
            "  Fix: android-bridge connect <ip:5555>  (e.g. 192.168.1.100:5555)\n"
            f"  Config: {CONFIG_FILE}"
        )
    return online[0]
