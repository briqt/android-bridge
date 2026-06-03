---
name: android-bridge
description: Control a connected Android phone via ADB — tap, swipe, type, read screen, take screenshots, run shell commands. Use this skill whenever the user wants to interact with their Android device, automate phone tasks, read what's on the phone screen, check phone status, open apps, navigate UI, or perform any mobile device operation. Also use when the user mentions "手机", "phone", "device", "screen", or references android-bridge commands.
---

# Android Device Control

Operate a connected Android device through the `android-bridge` CLI. Every interaction follows a perceive-act-verify loop.

## Prerequisites

### Installation

If `android-bridge` is not available, install it:

```bash
pipx install git+https://github.com/briqt/android-bridge.git
```

### Device Connection

Before first use, ensure the device is connected:

1. Run `android-bridge devices` to check for connected devices
2. If no device is listed, ask the user for their device IP (WiFi ADB) or serial (USB), then run `android-bridge connect <ip_or_serial>`
3. If a device is already connected via USB or previously remembered, `android-bridge connect` (no argument) will auto-detect it
4. Once connected, the device is remembered — no need to reconnect in future sessions

### Multi-Device (Profiles)

Use `--profile` / `-p` to target a specific device when multiple are configured:

```bash
android-bridge -p mi11 snapshot
android-bridge -p tablet tap 500 800
```

Profiles are stored in `~/.config/agent-skills/android-bridge/config.json`:
```json
{
  "active": "mi11",
  "profiles": {
    "mi11": { "serial": "192.168.137.96:5555" },
    "tablet": { "serial": "192.168.137.100:5555" }
  }
}
```

Selection priority: `--profile` flag > `config.json` `active` field.

### Waking the Device

The device must be awake for UI operations. If `snapshot` fails with "null root node", wake it first:

```bash
android-bridge shell --root "input keyevent KEYCODE_POWER"
```

### ADB Not Found

If `adb` is not on PATH, set the path in config:
```json
{
  "adb_path": "/usr/local/bin/adb"
}
```

### Remote ADB Server

When ADB server runs on another host (e.g. Windows host from WSL), configure in `~/.config/agent-skills/android-bridge/config.json`:

```json
{
  "adb_host": "127.0.0.1",
  "adb_port": 5038
}
```

This adds `-H <host> -P <port>` to all adb commands, connecting to the remote server instead of a local one.

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
android-bridge screenshot --out shot.png         # Screenshot only (saves to file)
android-bridge screenshot                        # Screenshot as base64 (stdout)
```

### Actions
```bash
android-bridge tap <x> <y>                # Tap point
android-bridge long-tap <x> <y>           # Long press
android-bridge swipe <x1> <y1> <x2> <y2> # Swipe
android-bridge type "<text>"              # ASCII input
android-bridge press <button>             # back|home|enter|power|volume_up|volume_down|tab|delete|recent
android-bridge drag <x1> <y1> <x2> <y2>  # Drag and drop
```

### Shell
```bash
android-bridge shell "<cmd>"              # Normal shell
android-bridge shell --root "<cmd>"       # Root shell (su -c)
android-bridge shell --root --script f.sh # Execute local script file on device
echo "cmd" | android-bridge shell --root  # Stdin pipe (bypasses all quoting issues)
```

For complex commands with `$()`, nested quotes, or pipes, prefer stdin mode:
```bash
cat <<'EOF' | android-bridge -p mi11 shell --root
echo "cap=$(cat /sys/class/power_supply/battery/capacity)%"
ps -A | grep my-daemon | grep -v grep
EOF
```

### File Transfer
```bash
android-bridge push <local> <remote>      # Push file/dir to device
android-bridge pull <remote> [local]      # Pull from device (default: cwd)
```

### Device
```bash
android-bridge devices                    # List devices
android-bridge connect <ip_or_serial>     # Connect and remember
android-bridge connect                    # Auto-detect connected device
```

## Chinese/CJK Text Input

`type` only handles ASCII. For CJK/unicode, use the built-in `type-cjk` command:

```bash
android-bridge type-cjk "中文内容"              # Type CJK (field must already have focus)
android-bridge type-cjk "中文内容" --at 638 779 # Tap field first, then type
```

Related field operations:

```bash
android-bridge clear-field                      # Clear focused input field
android-bridge clear-field --at 638 779         # Tap field first, then clear
android-bridge select-all                       # Select all text in focused field
android-bridge select-all --at 638 779          # Tap field first, then select all
```

These commands automatically handle ADBKeyBoard IME switching and InputConnection establishment. The `--at x y` option ensures proper focus by tapping the field, switching IME, then re-tapping to bind the InputConnection.

For manual control (rare), the underlying ADBKeyBoard broadcasts:

```bash
android-bridge shell "am broadcast -a ADB_INPUT_B64 --es msg '$(echo -n '文本' | base64)'"
android-bridge shell "am broadcast -a ADB_CLEAR_TEXT"
android-bridge shell "am broadcast -a ADB_INPUT_TEXT --es mcode '4096,29'"  # Ctrl+A
android-bridge shell "am broadcast -a ADB_INPUT_CODE --ei code 67"          # KEYCODE_DEL
```

## Scrolling

```bash
android-bridge swipe 540 1500 540 500    # Scroll down
android-bridge swipe 540 500 540 1500    # Scroll up
android-bridge swipe 800 1200 200 1200   # Scroll left
android-bridge swipe 200 1200 800 1200   # Scroll right
```

## Error Recovery

| Symptom | Cause | Fix |
|---------|-------|-----|
| "null root node" | Screen off or lock screen | `android-bridge shell --root "input keyevent KEYCODE_POWER"` then retry |
| Connection timeout | WiFi ADB disconnected | `android-bridge connect <ip>` to reconnect |
| "ADB not found" | adb binary not in PATH | Set `"adb_path"` in config.json |
| "No device found" | No USB/WiFi connection | Check cable or `adb tcpip 5555` on device |
| "unauthorized" / "failed to authenticate" | Device has not authorized this machine's ADB key | User must tap "Allow" (and "Always allow") on the device screen. Do NOT attempt to bypass via `ro.adb.secure`, `resetprop`, or writing to `adb_keys` directly — these hacks are unreliable on modern Android (HyperOS/MIUI framework overrides them). Use the official authorization flow. |

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

## Pitfalls

### ADBKeyBoard requires InputConnection

ADBKeyBoard broadcasts (`ADB_CLEAR_TEXT`, `ADB_INPUT_B64`, etc.) only work when ADBKeyBoard has an active InputConnection to the focused field. After switching IME with `ime set`, you MUST re-tap the input field to establish the connection. The `--at` option on `type-cjk`, `clear-field`, and `select-all` handles this automatically.

If using manual broadcasts and they silently fail, the cause is almost always: IME was switched but InputConnection was not re-established (missing re-tap).

Fallback for apps with non-standard InputConnection (very rare):

```bash
# Move cursor to end, then delete characters one by one
android-bridge shell --root "input keyevent KEYCODE_MOVE_END"
for i in $(seq 1 30); do
  android-bridge shell --root "input keyevent 67"   # KEYCODE_DEL
done
```

### Toast / Snackbar detection

Transient UI elements (toast messages, snackbar) are NOT captured by `snapshot` (accessibility tree). After any save/submit action, use `screenshot` + vision analysis to check for success/failure feedback.

### Avoid batch keyevent spam

Do NOT send a batch of unrelated keycodes (e.g., `input keyevent 28 29 30 ...`) hoping one will work — this can trigger unintended app launches or navigation. Send only the specific keyevent you need.

### `input keycombination` vs ADBKeyBoard mcode

`input keycombination` injects hardware-level KeyEvents via InputManagerService. It does NOT go through the IME channel. For text selection operations (Ctrl+A, Ctrl+C, etc.) on a focused EditText, prefer ADBKeyBoard's mcode broadcast — it goes through InputConnection and is more reliable:

```bash
# Prefer this (IME channel):
android-bridge shell "am broadcast -a ADB_INPUT_TEXT --es mcode '4096,29'"
# Over this (hardware injection — may not reach the editor):
android-bridge shell --root "input keycombination 113 29"
```
