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
