---
name: android-bridge
description: Control a connected Android phone via ADB — tap, swipe, type, read screen, take screenshots, run shell commands. Use this skill whenever the user wants to interact with their Android device, automate phone tasks, read what's on the phone screen, check phone status, open apps, navigate UI, or perform any mobile device operation. Also use when the user mentions "手机", "phone", "device", "screen", or references android-bridge commands.
---

# Android Device Control

Operate a connected Android device through the `android-bridge` CLI. Every interaction follows a perceive-act-verify loop.

## Prerequisites

### Installation

If `android-bridge` is not available, ask the user to install it:

```bash
pip install git+https://github.com/briqt/android-bridge.git
```

### Device Connection

Before first use, ensure the device is connected:

1. Run `android-bridge devices` to check for connected devices
2. If no device is listed, ask the user for their device IP (WiFi ADB) or serial (USB), then run `android-bridge connect <ip_or_serial>`
3. Once connected, the device is remembered — no need to reconnect in future sessions

The device must be awake for UI operations. If `snapshot` fails with "null root node", wake it first:

```bash
android-bridge shell --root "input keyevent KEYCODE_POWER"
```

If `ADB` is not on PATH, ask the user for the path and set it:
```bash
export ADB=/path/to/adb
```

## Core Loop

1. `android-bridge snapshot` — read current screen (visible text + interactive elements with coordinates)
2. Identify target element from output
3. `android-bridge tap <x> <y>` — act on the element's center coordinates
4. `android-bridge snapshot` — verify the result

## Command Reference

### Perception
```bash
android-bridge snapshot                          # UI tree (text + elements)
android-bridge snapshot --json-out               # JSON format
android-bridge snapshot --vision --save shot.png # With screenshot
android-bridge screenshot --out shot.png         # Screenshot only
```

### Actions
```bash
android-bridge tap <x> <y>                # Tap point
android-bridge long-tap <x> <y>           # Long press
android-bridge swipe <x1> <y1> <x2> <y2> # Swipe
android-bridge type "<text>"              # ASCII input
android-bridge press <button>             # back|home|enter|power|volume_up|volume_down
android-bridge drag <x1> <y1> <x2> <y2>  # Drag and drop
```

### Shell
```bash
android-bridge shell "<cmd>"              # Normal shell
android-bridge shell --root "<cmd>"       # Root shell (su -c)
```

### Device
```bash
android-bridge devices                    # List devices
android-bridge connect <ip_or_serial>     # Connect and remember
```

## Chinese Text Input

`type` only handles ASCII. For CJK, use ADBKeyBoard (pre-installed):

```bash
android-bridge shell --root "ime set com.android.adbkeyboard/.AdbIME"
android-bridge shell "am broadcast -a ADB_INPUT_B64 --es msg '$(echo -n '中文内容' | base64)'"
android-bridge shell --root "ime set com.sohu.inputmethod.sogou.xiaomi/.SogouIME"
```

## Scrolling

```bash
android-bridge swipe 540 1500 540 500    # Scroll down
android-bridge swipe 540 500 540 1500    # Scroll up
android-bridge swipe 800 1200 200 1200   # Scroll left
android-bridge swipe 200 1200 800 1200   # Scroll right
```

## Snapshot Output Format

```
=== Visible Text ===
  下午3:53
  晴 28℃

=== Interactive Elements ===
  [0] 时钟 (540,399) [click]
  [1] 设置 (921,806) [click]
  [2] 电话 (286,2187) [click]
```

Each element shows: `[index] name (center_x, center_y) [capabilities]`. Use the center coordinates directly with `tap`.
