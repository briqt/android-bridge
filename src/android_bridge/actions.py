"""Action layer: device operations via pure ADB commands."""

import shlex

from android_bridge.device import adb_shell, action_shell


def tap(x: int, y: int) -> str:
    action_shell(f"input tap {x} {y}")
    return f"Tapped ({x}, {y})"


def long_tap(x: int, y: int, duration: int = 1000) -> str:
    action_shell(f"input swipe {x} {y} {x} {y} {duration}")
    return f"Long-tapped ({x}, {y}) for {duration}ms"


def swipe(x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> str:
    action_shell(f"input swipe {x1} {y1} {x2} {y2} {duration}")
    return f"Swiped ({x1},{y1}) -> ({x2},{y2})"


def type_text(text: str) -> str:
    # Escape for shell; 'input text' expects shell-safe string
    action_shell(f"input text {shlex.quote(text)}")
    return f"Typed {len(text)} characters"


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
    action_shell(f"input keyevent {keycode}")
    return f"Pressed: {button}"


def drag(x1: int, y1: int, x2: int, y2: int, duration: int = 500) -> str:
    action_shell(f"input draganddrop {x1} {y1} {x2} {y2} {duration}")
    return f"Dragged ({x1},{y1}) -> ({x2},{y2})"


def shell(cmd: str, root: bool = False) -> str:
    return adb_shell(cmd, root=root)


def shell_script(script: str, root: bool = False) -> str:
    from android_bridge.device import adb_shell_script
    return adb_shell_script(script, root=root)


def _get_current_ime() -> str:
    return adb_shell("settings get secure default_input_method").strip()


def _with_keyboard(operation: str, tap_x: int = None, tap_y: int = None) -> None:
    import time
    original = _get_current_ime()
    target = "com.android.adbkeyboard/.AdbIME"
    switched = False
    try:
        if original != target:
            action_shell(f"ime set {target}")
            switched = True
            time.sleep(0.3)
        if tap_x is not None and tap_y is not None:
            action_shell(f"input tap {tap_x} {tap_y}")
            time.sleep(0.3)
        action_shell(operation)
        time.sleep(0.3)
    finally:
        if switched and original and original != "null":
            # A failed input must not leave the user's keyboard replaced.
            import sys
            try:
                action_shell(f"ime set {shlex.quote(original)}")
            except Exception:
                print("WARNING: could not restore the previous IME; check device keyboard settings", file=sys.stderr)


def type_cjk(text: str, tap_x: int = None, tap_y: int = None) -> str:
    import base64
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    _with_keyboard(f"am broadcast -a ADB_INPUT_B64 --es msg {shlex.quote(encoded)}", tap_x, tap_y)
    return f"Typed {len(text)} Unicode characters"


def clear_field(tap_x: int = None, tap_y: int = None) -> str:
    _with_keyboard("am broadcast -a ADB_CLEAR_TEXT", tap_x, tap_y)
    return "Field cleared"


def select_all(tap_x: int = None, tap_y: int = None) -> str:
    _with_keyboard("am broadcast -a ADB_INPUT_TEXT --es mcode '4096,29'", tap_x, tap_y)
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
