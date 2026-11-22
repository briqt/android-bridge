"""Device connection management via pure ADB (no on-device agent)."""

from pathlib import Path
import json
import os
import shlex
import shutil
import sys
import subprocess

def _config_dir() -> Path:
    """Runtime directory; ANDROID_BRIDGE_HOME relocates it (e.g. to isolate tests)."""
    custom = os.environ.get("ANDROID_BRIDGE_HOME", "").strip()
    return Path(custom).expanduser() if custom else Path.home() / ".config" / "agent-skills" / "android-bridge"


CONFIG_DIR = _config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"

class BridgeError(RuntimeError):
    """An actionable failure category, retaining diagnostics from its first cause."""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


def _command_error(result) -> BridgeError:
    message = (result.stderr.strip() + "\n" + result.stdout.strip()).strip()
    lower = message.lower()
    code = "ADB_UNAUTHORIZED" if "unauthorized" in lower else "ADB_OFFLINE" if "offline" in lower else "ADB_DEVICE_NOT_FOUND" if "not found" in lower and "device" in lower else "ADB_COMMAND_FAILED"
    return BridgeError(code, message or f"adb shell failed (exit {result.returncode})")


def root_mode() -> str:
    config = _load_full_config()
    profile = _resolve_profile()
    settings = config.get("profiles", {}).get(profile, {}) if profile else config.get("device", {})
    mode = settings.get("root_mode", config.get("root_mode", "auto"))
    if mode not in ("auto", "required", "never"):
        raise BridgeError("CONFIG_INVALID", f"root_mode must be auto|required|never. Edit {CONFIG_FILE}")
    return mode


def action_shell(command: str) -> str:
    """Prefer shell privileges; retry as root only after an explicit permission denial."""
    mode = root_mode()
    if mode == "required":
        return adb_shell(command, root=True)
    try:
        return adb_shell(command)
    except BridgeError as error:
        permission = any(word in str(error).lower() for word in ("permission denial", "permission denied", "securityexception", "inject_events", "requires root", "operation not permitted"))
        if mode != "auto" or not permission:
            raise
        return adb_shell(command, root=True)


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
    """Return (config, CONFIG_FILE). Config is read only from CONFIG_FILE: never from the
    current working directory or the installed skill directory. A missing file means defaults;
    an unreadable one is an error, never a silent fallback."""
    path = CONFIG_FILE
    if not path.exists():
        return {}, path
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BridgeError("CONFIG_INVALID", f"cannot read {path}: {error}. Fix: correct the JSON in {path}, or delete it to start from defaults")
    if not isinstance(config, dict):
        raise BridgeError("CONFIG_INVALID", f"{path} must contain a JSON object. Fix: correct {path}, or delete it to start from defaults")
    return config, path


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
    # Merge into the existing CONFIG_FILE so unrelated settings (root_mode, adb_*) survive.
    config, path = _load_full_config_with_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if profile:
        config.setdefault("profiles", {}).setdefault(profile, {})["serial"] = serial
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
    if result.returncode != 0:
        raise _command_error(result)
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
    if result.returncode != 0:
        raise _command_error(result)
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
