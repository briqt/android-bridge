---
name: android-bridge
description: Control a connected Android phone via ADB — tap, swipe, type, read screen via the accessibility tree, take screenshots (for humans/vision models), run shell commands. Use this skill whenever the user wants to interact with their Android device, automate phone tasks, read what's on the phone screen, check phone status, open apps, navigate UI, or perform any mobile device operation. Also use when the user mentions "手机", "phone", "device", "screen", or references android-bridge commands. Works for both text-only and vision-capable models.
---

# Android Device Control

Operate a connected Android device through the `android-bridge` CLI. Every interaction follows a **perceive → locate → act → verify → escalate** loop. The CLI is the single source of truth; this file is the agent-facing manual.

**Every command prints `[profile: <name>]` on the first line of stderr** (success or failure — defaults to `[profile: default]` when no profile is active). That is by design: use it to confirm which device is active. Stdout carries results; stderr carries diagnostics.

## Quick Start

```bash
pipx install git+https://github.com/briqt/android-bridge.git   # install CLI
android-bridge connect 192.168.1.100:5555                       # connect (WiFi ADB; remembered)
android-bridge snapshot                                          # read screen (native apps)
android-bridge dump                                              # read screen (Flutter/Compose apps)
android-bridge tap 540 1200                                      # act
```

## Command Quick Reference

| Command | Signature | Notes |
|---------|-----------|-------|
| `snapshot` | `[--json-out] [--out PATH]` | Curated UI tree (text + interactive elements). `--out` saves a screenshot. |
| `dump` | `[--json-out] [--clickable] [--all] [--max N] [--out PATH]` | Full node dump — use for Flutter/Compose sparse trees. |
| `screenshot` | `[--out PATH]` | Screenshot file (`--out`) or base64 to stdout (vision models only). |
| `tap` | `x y` | Tap point. |
| `long-tap` | `x y` | Long press. |
| `swipe` | `x1 y1 x2 y2` | Swipe / scroll. |
| `drag` | `x1 y1 x2 y2` | Drag and drop. |
| `type` | `"text"` | ASCII only (use `type-cjk` for CJK). |
| `type-cjk` | `"文本" [--at x y]` | CJK/unicode via ADBKeyBoard. |
| `clear-field` | `[--at x y]` | Clear focused field. |
| `select-all` | `[--at x y]` | Select all in focused field. |
| `press` | `button` | back\|home\|enter\|power\|volume_up\|volume_down\|tab\|delete\|recent (or any `KEYCODE_*`). |
| `shell` | `"cmd" [--root] [--script f]` | Run on device; stdin pipe supported. |
| `push` | `local remote` | Push file/dir to device. |
| `pull` | `remote [local]` | Pull from device (default: cwd). |
| `devices` | — | List connected devices. |
| `connect` | `[serial]` | Connect + remember. |

Global: `-p`/`--profile <name>` selects a device profile.

## Core Loop: Perceive → Locate → Act → Verify → Escalate

**PERCEIVE** — `android-bridge snapshot` (native apps) or `android-bridge dump` (Flutter/Compose).
- Empty / ERROR / "null root node" → go to **Failure Decision Tree** (screen off / offline).
- Normal → proceed to LOCATE.

**LOCATE** — find the target in the output.
- Element has coordinates → use its center.
- Text appears but has no coordinate (Flutter sparse tree: text node not flagged `clickable`) → run `android-bridge dump`, find the node by `text`/`content-desc`, use its `bounds` center.
- Target not on screen → scroll (`swipe`) or dismiss an overlay first (see Pitfalls).
- Multiple same-text elements → disambiguate by `resource_id` (use `--json-out`) or by `bounds` y-order.

**ACT** — dispatch by action type.
- Click → `tap` / `long-tap`.
- Type → `tap` field first; ASCII `type`, CJK `type-cjk --at x y`.
- Scroll/drag → `swipe` / `drag`.
- System key → `press`.

**VERIFY** — `android-bridge snapshot` (or `dump`) and compare to before.
- Name the expected change concretely: "button X now shows Y", "page titled Z appeared", "field contains V".
- For transient feedback (Toast/Snackbar) see Pitfalls — do NOT rely on reading a screenshot unless you are a vision-capable model.

**ESCALATE** — on verify failure.
- Element may have shifted after render → re-PERCEIVE → LOCATE new coords → re-ACT. Max 2 rounds.
- Still failing → stop and report: "tap (x,y) produced no change; last snapshot: <summary>". Do not retry indefinitely.

## Failure Decision Tree

```
Operation failed?
│
├─ snapshot/dump returns ERROR / "null root node"
│   ├─ Screen off/locked → android-bridge shell --root "input keyevent KEYCODE_POWER" → retry
│   └─ Still null → android-bridge devices
│       ├─ No device → android-bridge connect <ip:5555> (WiFi) or plug USB
│       └─ "offline" → android-bridge shell --root "input keyevent 224" (WAKEUP); retry; still offline → ask user to replug
│
├─ snapshot/dump reports "could not get idle state" / dump fails
│   └─ Flutter animation never idle → retry ≤3 times → still failing: android-bridge shell "uiautomator dump --compressed /sdcard/d.xml && cat /sdcard/d.xml" → still failing: blind-operate by geometry + verify post-action
│
├─ snapshot normal but Interactive Elements empty / target has no coordinates
│   └─ Flutter/Compose sparse tree → android-bridge dump → find node by text/content-desc → tap bounds center
│
├─ tap produces no state change (verify failed)
│   ├─ Element shifted → re-snapshot, re-tap with new coords (≤2 rounds)
│   ├─ Overlay/coach-mark intercepting → snapshot, find "我知道了/跳过/Got it", tap it, retry target
│   ├─ Non-clickable Flutter node → use dump bounds (above) or press back, re-enter
│   └─ 2 rounds still no change → stop, report diagnostics
│
├─ Screenshot all-black
│   ├─ FLAG_SECURE app → use snapshot/dump (a11y tree is unaffected), drop screenshot path
│   └─ Text-only model → never use --vision/screenshot as visual input; use text + dump + logcat
│
├─ Transient toast not in snapshot
│   └─ Most app feedback is Snackbar (in view tree) → re-snapshot promptly; else verify post-action state; see Pitfalls
│
├─ "unauthorized" / auth failed
│   └─ Do NOT bypass via ro.adb.secure/resetprop/adb_keys (unreliable on HyperOS/MIUI) → user taps "Allow" + "Always allow" on device → reconnect
│
├─ "ADB not found"
│   └─ Set "adb_path" in ~/.config/agent-skills/android-bridge/config.json, or sudo apt install adb
│
└─ Connection timeout / WiFi ADB dropped
    └─ android-bridge connect <ip:5555> → retry; "failed to connect" → on device: adb tcpip 5555 (via USB first)
```

## Visual Capability & Perception Strategy

This skill serves **both** vision-capable multimodal models and text-only models. Detect which one you are before choosing a perception path.

### Text-only models (cannot read PNG/image bytes)

Your **only** perception channel is the accessibility tree text. Use this path:

1. `android-bridge snapshot` — default. Returns visible text + interactive elements with center coordinates. This is your eyes.
2. If `snapshot` is missing elements (sparse tree, Flutter app, or you need raw `content-desc`/`bounds` it dropped), use `android-bridge dump` — it preserves every labeled/interactive node with coordinates.
3. Last-resort raw XML (when even `dump` is uncooperative):
   ```bash
   android-bridge shell "uiautomator dump /sdcard/d.xml && cat /sdcard/d.xml"
   ```
   Compute tap center from `bounds="[x1,y1][x2,y2]"` → `((x1+x2)/2, (y1+y2)/2)`.
4. `screenshot` / `snapshot --out` produce an **image file you cannot read**. Do NOT call them for perception. See "When screenshots still help" below.

**Default path (text-only):** perceive via `snapshot` (fallback to `dump`) → locate element → `tap` → verify via `snapshot`. Never depend on reading pixels.

### Vision-capable models

`snapshot --out shot.png` gives you both the a11y tree text AND a screenshot you can read. Use the image to resolve ambiguity the text tree cannot (icons without `content-desc`, canvas-rendered content, layout sanity checks). The text tree is still your primary source for coordinates.

### When screenshots still help (any model)

- Hand the file to a **human** for visual confirmation (`screenshot --out x.png`).
- Hand the file to a **vision-capable model** in a multi-agent setup.
- **Archive** a debugging artifact of a failure state.

A text-only model may still *take* a screenshot for these purposes — it just cannot *analyze* it itself.

## Reading the Screen

### snapshot — curated view (default for native apps)

```
=== Visible Text ===
  下午3:53
  晴 28℃

=== Interactive Elements ===
  [0] 时钟 (540,399) [click]
  [1] 设置 (921,806) [click]
```

Each element: `[index] name (cx, cy) [capabilities]`. Use the center coordinates directly with `tap`.

`snapshot --json-out` adds `class_name`, `resource_id`, and `bounds` per element — use it to disambiguate same-text elements or compute off-center taps.

### dump — full node dump (use for Flutter/Compose/Canvas apps)

`snapshot` drops nodes that have a label but aren't flagged `clickable` (Flutter puts text in `content-desc` and often skips clickable flags). `dump` keeps them:

```
=== UI Dump ===
screen: 1080x2400  nodes: 44  shown: 44

  [0] 社区小医生，全城专家求我会诊 (540,395) bounds=[0,160][1080,275] class=TextView
  [1] 底部tab-我的 (940,1850) [click] bounds=[800,1800][1080,1900] class=ImageView
```

Each node: `[index] label (cx,cy) [flags] bounds=[x1,y1][x2,y2] class=X rid=Y`.

- **Trigger rule**: if `snapshot` returns fewer than ~3 interactive elements, or a target appears as a label-less `ImageView`/`View`, switch to `dump`. Flutter/Compose/Canvas apps (e.g. `com.bytedance.writer_assistant_flutter`) — default to `dump`.
- `dump --clickable` — only interactive nodes (tighter output when the tree is large).
- `dump --json-out` — full fields including `content_desc` (untruncated) for programmatic use.
- `dump --max N` — cap nodes shown (default 200; stderr warns on truncation).

## Text Input (ASCII & CJK)

`type` is ASCII only. For CJK/unicode use `type-cjk` (via ADBKeyBoard):

```bash
android-bridge type-cjk "中文内容"              # field must already have focus
android-bridge type-cjk "中文内容" --at 638 779 # tap field first, then type
```

Related:
```bash
android-bridge clear-field                      # clear focused field
android-bridge clear-field --at 638 779         # tap first, then clear
android-bridge select-all                       # Ctrl+A in focused field
android-bridge select-all --at 638 779          # tap first, then select all
```

`--at x y` taps the field, switches IME to ADBKeyBoard, re-taps to bind the InputConnection, then acts. See Pitfalls for why the re-tap matters.

Manual ADBKeyBoard broadcasts (rare):
```bash
android-bridge shell "am broadcast -a ADB_INPUT_B64 --es msg '$(echo -n '文本' | base64)'"
android-bridge shell "am broadcast -a ADB_CLEAR_TEXT"
android-bridge shell "am broadcast -a ADB_INPUT_TEXT --es mcode '4096,29'"  # Ctrl+A
android-bridge shell "am broadcast -a ADB_INPUT_CODE --ei code 67"          # KEYCODE_DEL
```

## Scrolling

```bash
android-bridge swipe 540 1500 540 500    # scroll down
android-bridge swipe 540 500 540 1500    # scroll up
android-bridge swipe 800 1200 200 1200   # scroll left
android-bridge swipe 200 1200 800 1200   # scroll right
```

## Pitfalls

### Flutter/Compose sparse accessibility tree
**Symptom**: `snapshot` shows few/no interactive elements, or target text appears with no coordinates; bottom tab bars vanish.
**Cause**: Flutter handles gestures in Dart and doesn't set `clickable` on a11y nodes; `snapshot` only lists `clickable`/`scrollable` nodes as interactive.
**Fix**: `android-bridge dump` — preserves all labeled/interactive nodes with `bounds` + center. For Flutter/Compose/Canvas apps, default to `dump`.

### uiautomator dump fails on animating UI
**Symptom**: `snapshot`/`dump` returns ERROR, "could not get idle state", or empty.
**Cause**: Flutter continuous render (animation/loading spinner) keeps the UI non-idle; uiautomator can't grab a stable frame.
**Fix**: retry ≤3 times; then `android-bridge shell "uiautomator dump --compressed /sdcard/d.xml && cat /sdcard/d.xml"`; still failing → blind-operate by known geometry and verify via the next `snapshot`.

### Coach-mark / onboarding overlays
**Symptom**: tapping target coords does nothing; `snapshot`/`dump` shows a dim overlay with a single "我知道了/知道了/跳过/Got it" button above the real UI.
**Cause**: first-visit coach-mark intercepts touches.
**Fix**: dismiss the overlay first (tap its button), re-perceive to confirm the real UI is exposed, then act on the original target.

### Bottom tab bar not in accessibility tree
**Symptom**: a visible bottom tab bar has no elements in `snapshot`.
**Fix**: try `dump` first (tab text often lives in `content-desc`); if still absent, use screen geometry — tabs sit at the screen bottom (1080×2400 ≈ y=2284), evenly spaced by index (5 tabs → x≈139,340,540,740,940); `tap <x> <y_bottom>`. Or `press back` and re-enter (nodes sometimes appear after re-entry).

### Text-only model has no vision
**Symptom**: `Read shot.png` returns nothing useful; `snapshot --out` screenshots carry no information for you.
**Fix**: never use "looking at a screenshot" as a verification step. All "see the screen" needs go through: `snapshot` → `dump` → raw `uiautomator dump` XML → `android-bridge shell --root "logcat -d -t 50"` → `android-bridge shell "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"`.

### FLAG_SECURE black screenshots
**Symptom**: `screenshot --out x.png` yields an all-black/blank PNG.
**Cause**: app set `FLAG_SECURE` (banks, some editors, DRM).
**Fix**: drop the screenshot path; use `snapshot`/`dump` (a11y tree is unaffected by FLAG_SECURE).

### `snapshot --out` is self-sufficient (no `--vision` needed)
`--vision` is deprecated. `snapshot --out x.png` captures and saves a screenshot on its own. (Previously `--save` required `--vision` — that coupling is gone; `--save` remains as an alias.)

### `screenshot` without `--out` dumps base64 to stdout
For text-only models this is a long, unreadable string that pollutes context. Only use `screenshot` (no `--out`) if you are a vision-capable model consuming base64, or redirect to a file. Prefer `screenshot --out x.png` (file lands on disk, not in context).

### Transient feedback (Toast / Snackbar) — text-only-safe detection
Do NOT assume `snapshot` misses all transient feedback. The two differ:
- **Snackbar** (Material; Flutter `SnackBar`) lives **inside** the app view tree / Flutter semantics. It **IS** captured by `snapshot`/`dump` as a `text`/`content-desc` node while visible (~4s). After a save/submit, re-perceive promptly and look for the new message node.
- **Native Android Toast** renders in a separate window layer and is **NOT** in `snapshot`/`dump`. There is **no reliable text channel** for native Toast text: `adb logcat` doesn't log `Toast.show()`, `dumpsys window` shows the window token but not its text.

**Recommended success-check (text-only):**
1. `snapshot`/`dump` right after the action — look for a Snackbar message node AND/OR a screen-state change (navigation, new element, updated field).
2. If transient text is genuinely absent, **verify post-action state** instead: `android-bridge shell "dumpsys activity top | grep mResumedActivity"` (did the Activity change?) or check the next `snapshot` for persistent changes.
3. If you must read a **native** Toast's exact text and have no vision model: best-effort `--windows` dump (unreliable, timing-sensitive): `android-bridge shell "uiautomator dump --windows /sdcard/d.xml && cat /sdcard/d.xml" | grep -iE 'toast|TransientNotification'`.
4. If 1-3 fail, **you cannot read this feedback as a text-only model** — say so and ask the user to confirm visually, or delegate the screenshot to a vision-capable model. Do not pretend you saw it.

### ADBKeyBoard requires InputConnection
ADBKeyBoard broadcasts only work when ADBKeyBoard has an active InputConnection to the focused field. After `ime set`, you MUST re-tap the input field to establish the connection. The `--at` option on `type-cjk`/`clear-field`/`select-all` handles this automatically.
If using manual broadcasts and they silently fail, the cause is almost always: IME switched but InputConnection not re-established (missing re-tap).
Fallback for apps with non-standard InputConnection (rare):
```bash
android-bridge shell --root "input keyevent KEYCODE_MOVE_END"
for i in $(seq 1 30); do android-bridge shell --root "input keyevent 67"; done   # KEYCODE_DEL x30
```

### Avoid batch keyevent spam
Do NOT send a batch of unrelated keycodes (e.g. `input keyevent 28 29 30 ...`) hoping one works — this can trigger unintended app launches/navigation. Send only the specific keyevent you need.

### `input keycombination` vs ADBKeyBoard mcode
`input keycombination` injects hardware-level KeyEvents via InputManagerService — it does NOT go through the IME channel. For text selection (Ctrl+A, Ctrl+C) on a focused EditText, prefer ADBKeyBoard's mcode broadcast (goes through InputConnection, more reliable):
```bash
# Prefer (IME channel):
android-bridge shell "am broadcast -a ADB_INPUT_TEXT --es mcode '4096,29'"
# Over (hardware injection — may not reach the editor):
android-bridge shell --root "input keycombination 113 29"
```

## Device & Profile Setup

### Installation
```bash
pipx install git+https://github.com/briqt/android-bridge.git
```

### Device connection
1. `android-bridge devices` — check for connected devices.
2. If none, ask the user for the device IP (WiFi ADB) or serial (USB), then `android-bridge connect <ip_or_serial>`.
3. If already connected via USB or remembered, `android-bridge connect` (no arg) auto-detects.
4. Once connected, the device is remembered.

### Waking the device
The device must be awake for UI ops. If `snapshot` fails with "null root node":
```bash
android-bridge shell --root "input keyevent KEYCODE_POWER"
```

### Multi-device (profiles)
Use `--profile`/`-p` to target a specific device:
```bash
android-bridge -p mi11 snapshot
android-bridge -p tablet tap 500 800
```
Profiles live in `~/.config/agent-skills/android-bridge/config.json`. Selection priority: `--profile` flag > `active` field.

### ADB not on PATH
Set `adb_path` in config:
```json
{ "adb_path": "/usr/local/bin/adb" }
```

### Remote ADB server (e.g. Windows host from WSL)
```json
{ "adb_host": "127.0.0.1", "adb_port": 5038 }
```
Adds `-H <host> -P <port>` to all adb commands.

## Config Reference

Runtime data lives in `~/.config/agent-skills/android-bridge/config.json`:
```json
{
  "active": "mi11",
  "adb_path": "",
  "adb_host": "",
  "adb_port": 5037,
  "profiles": {
    "mi11": { "serial": "192.168.31.20:5555" }
  },
  "device": { "serial": "" }
}
```
- `active` — default profile when no `--profile`.
- `adb_path` / `adb_host` / `adb_port` — ADB binary and server location.
- `profiles` — named devices (`serial` = `IP:port` or USB serial).
- `device.serial` — remembered device when no profile is active (written by `connect`).

Config load priority: a `.config.json` in the current working directory (dev override, gitignored) wins over the standard location; the first found is used, not merged.

**Every command emits `[profile: <name>]` on stderr's first line** (defaults to `[profile: default]` when no profile is active). This is by design — use it to confirm the active device.
