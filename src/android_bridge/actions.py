"""Action layer: device operations via pure ADB commands."""

import shlex

from android_bridge.device import adb_shell


def tap(x: int, y: int) -> str:
    adb_shell(f"input tap {x} {y}", root=True)
    return f"Tapped ({x}, {y})"


def long_tap(x: int, y: int, duration: int = 1000) -> str:
    adb_shell(f"input swipe {x} {y} {x} {y} {duration}", root=True)
    return f"Long-tapped ({x}, {y}) for {duration}ms"


def swipe(x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> str:
    adb_shell(f"input swipe {x1} {y1} {x2} {y2} {duration}", root=True)
    return f"Swiped ({x1},{y1}) -> ({x2},{y2})"


def type_text(text: str) -> str:
    # Escape for shell; 'input text' expects shell-safe string
    adb_shell(f"input text {shlex.quote(text)}", root=True)
    return f"Typed: '{text}'"


def press(button: str) -> str:
    key_map = {
        "back": "KEYCODE_BACK",
        "home": "KEYCODE_HOME",
        "enter": "KEYCODE_ENTER",
        "power": "KEYCODE_POWER",
        "volume_up": "KEYCODE_VOLUME_UP",
        "volume_down": "KEYCODE_VOLUME_DOWN",
        "tab": "KEYCODE_TAB",
        "delete": "KEYCODE_DEL",
        "recent": "KEYCODE_APP_SWITCH",
    }
    keycode = key_map.get(button.lower(), button.upper())
    if not keycode.startswith("KEYCODE_"):
        keycode = f"KEYCODE_{keycode}"
    adb_shell(f"input keyevent {keycode}", root=True)
    return f"Pressed: {button}"


def drag(x1: int, y1: int, x2: int, y2: int, duration: int = 500) -> str:
    adb_shell(f"input draganddrop {x1} {y1} {x2} {y2} {duration}", root=True)
    return f"Dragged ({x1},{y1}) -> ({x2},{y2})"


def shell(cmd: str, root: bool = False) -> str:
    return adb_shell(cmd, root=root)


def shell_script(script: str, root: bool = False) -> str:
    from android_bridge.device import adb_shell_script
    return adb_shell_script(script, root=root)


def _ensure_adbkeyboard(tap_x: int = None, tap_y: int = None) -> None:
    """Switch to ADBKeyBoard and optionally re-tap to establish InputConnection."""
    adb_shell("ime set com.android.adbkeyboard/.AdbIME", root=True)
    import time
    time.sleep(0.3)
    if tap_x is not None and tap_y is not None:
        adb_shell(f"input tap {tap_x} {tap_y}", root=True)
        time.sleep(0.3)


def _restore_ime(ime: str = "com.sohu.inputmethod.sogou.xiaomi/.SogouIME") -> None:
    """Restore the original IME after ADBKeyBoard operations."""
    adb_shell(f"ime set {ime}", root=True)


def _get_current_ime() -> str:
    """Get the current IME identifier."""
    result = adb_shell("settings get secure default_input_method")
    return result.strip()


def type_cjk(text: str, tap_x: int = None, tap_y: int = None) -> str:
    """Type CJK/unicode text via ADBKeyBoard broadcast.

    If tap coordinates are provided, taps the field first, switches IME,
    re-taps to establish InputConnection, then types.
    """
    import base64
    import time

    original_ime = _get_current_ime()
    adbkb = "com.android.adbkeyboard/.AdbIME"

    # Only switch IME if not already ADBKeyBoard
    need_switch = adbkb not in original_ime

    if need_switch:
        if tap_x is not None and tap_y is not None:
            adb_shell(f"input tap {tap_x} {tap_y}", root=True)
            time.sleep(0.3)
        _ensure_adbkeyboard(tap_x, tap_y)

    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    adb_shell(f"am broadcast -a ADB_INPUT_B64 --es msg '{encoded}'")
    time.sleep(0.3)

    if need_switch:
        _restore_ime(original_ime)

    return f"Typed CJK: '{text}'"


def clear_field(tap_x: int = None, tap_y: int = None) -> str:
    """Clear the focused EditText field using ADBKeyBoard's ADB_CLEAR_TEXT.

    If tap coordinates provided, ensures proper IME focus chain.
    """
    import time

    original_ime = _get_current_ime()
    adbkb = "com.android.adbkeyboard/.AdbIME"
    need_switch = adbkb not in original_ime

    if need_switch:
        if tap_x is not None and tap_y is not None:
            adb_shell(f"input tap {tap_x} {tap_y}", root=True)
            time.sleep(0.3)
        _ensure_adbkeyboard(tap_x, tap_y)

    adb_shell("am broadcast -a ADB_CLEAR_TEXT")
    time.sleep(0.3)

    if need_switch:
        _restore_ime(original_ime)

    return "Field cleared"


def select_all(tap_x: int = None, tap_y: int = None) -> str:
    """Select all text in the focused field using ADBKeyBoard's Ctrl+A via mcode.

    If tap coordinates provided, ensures proper IME focus chain.
    """
    import time

    original_ime = _get_current_ime()
    adbkb = "com.android.adbkeyboard/.AdbIME"
    need_switch = adbkb not in original_ime

    if need_switch:
        if tap_x is not None and tap_y is not None:
            adb_shell(f"input tap {tap_x} {tap_y}", root=True)
            time.sleep(0.3)
        _ensure_adbkeyboard(tap_x, tap_y)

    # mcode: META_CTRL_ON=4096, KEYCODE_A=29
    adb_shell("am broadcast -a ADB_INPUT_TEXT --es mcode '4096,29'")
    time.sleep(0.3)

    if need_switch:
        _restore_ime(original_ime)

    return "Selected all text"


def push(local: str, remote: str) -> str:
    from android_bridge.device import adb
    result = adb(["push", local, remote], timeout=120)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(output or f"adb push failed (exit {result.returncode})")
    return output


def pull(remote: str, local: str) -> str:
    from android_bridge.device import adb
    result = adb(["pull", remote, local], timeout=120)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(output or f"adb pull failed (exit {result.returncode})")
    return output
