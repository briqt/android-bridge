"""Device connection management. Supports pure ADB mode (default) and uiautomator2 mode."""

from pathlib import Path
import os
import subprocess
import tomllib

CONFIG_DIR = Path.home() / ".android-bridge"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def _adb_cmd() -> str:
    return os.environ.get("ADB", "adb")


def adb(args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    serial = _load_config()
    cmd_parts = [_adb_cmd()]
    if serial:
        cmd_parts.extend(["-s", serial])
    cmd_parts.extend(args.split())
    return subprocess.run(cmd_parts, capture_output=True, text=True, timeout=timeout)


def adb_shell(cmd: str, root: bool = False, timeout: int = 30) -> str:
    serial = _load_config()
    adb_bin = _adb_cmd()
    cmd_parts = [adb_bin]
    if serial:
        cmd_parts.extend(["-s", serial])
    if root:
        cmd_parts.extend(["shell", f"su -c '{cmd}'"])
    else:
        cmd_parts.extend(["shell", cmd])
    result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=timeout)
    output = result.stdout.strip()
    if result.returncode != 0:
        err = result.stderr.strip()
        raise RuntimeError(err or output or f"adb shell failed (exit {result.returncode})")
    return output


def list_devices() -> list[tuple[str, str]]:
    result = subprocess.run(
        [_adb_cmd(), "devices"], capture_output=True, text=True, timeout=10
    )
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
    result = subprocess.run(
        [_adb_cmd(), "connect", serial], capture_output=True, text=True, timeout=15
    )
    output = (result.stdout + result.stderr).strip().lower()
    if "connected" not in output and "already" not in output:
        raise RuntimeError(f"Failed to connect: {result.stdout.strip()}")


def _save_config(serial: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(f'[device]\nserial = "{serial}"\n')


def _load_config() -> str | None:
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, "rb") as f:
        data = tomllib.load(f)
    return data.get("device", {}).get("serial")


def connect(serial: str | None = None) -> str:
    if serial is None:
        serial = _load_config()
    if serial is None:
        devices = list_devices()
        online = [s for s, state in devices if state == "device"]
        if not online:
            raise RuntimeError("No device found. Specify a serial or connect a device.")
        serial = online[0]
    else:
        serial = _normalize_serial(serial)
        if ":" in serial:
            _adb_connect(serial)

    # Verify connection
    adb_bin = _adb_cmd()
    result = subprocess.run(
        [adb_bin, "-s", serial, "shell", "getprop", "ro.product.model"],
        capture_output=True, text=True, timeout=10
    )
    model = result.stdout.strip() or "unknown"
    _save_config(serial)
    return f"{model} ({serial})"


def get_serial() -> str:
    serial = _load_config()
    if serial:
        return serial
    devices = list_devices()
    online = [s for s, state in devices if state == "device"]
    if not online:
        raise RuntimeError("No device connected. Run: android-bridge connect <serial>")
    return online[0]

