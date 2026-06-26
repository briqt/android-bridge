# android-bridge

AI-facing interface for Android device automation via pure ADB. Designed to be called by any AI agent (Claude Code, Cursor, Hermes, etc.) through CLI or Skill.

## Install

### As a Skill (for AI agents)

```bash
npx skills add briqt/android-bridge
```

### As a CLI tool (standard)

```bash
pipx install git+https://github.com/briqt/android-bridge.git
```

### For development

```bash
git clone https://github.com/briqt/android-bridge.git
cd android-bridge
pipx install --editable .
# after changes: pipx reinstall android-bridge
```

### Prerequisites

- Python 3.10+
- ADB (Android Debug Bridge) on PATH, or set `"adb_path"` in `~/.config/agent-skills/android-bridge/config.json`
- Android device with USB debugging enabled (root recommended)

## Usage

```bash
# Connect device (remembers for future commands)
android-bridge connect 192.168.1.100:5555

# Read screen
android-bridge snapshot                # native apps (text + interactive elements)
android-bridge dump                    # Flutter/Compose apps (full node tree with bounds)
android-bridge screenshot --out screen.png

# Interact
android-bridge tap 540 1200
android-bridge swipe 540 1500 540 500
android-bridge press back
android-bridge type "hello"
android-bridge type-cjk "中文内容" --at 638 779

# Shell
android-bridge shell "dumpsys battery"
android-bridge shell --root "cat /sys/class/power_supply/battery/capacity"
```

## Design

- **LLM is the brain, tool is the hands.** No decision logic in the tool — just atomic operations (perceive, tap, swipe, type).
- **Pure ADB, zero on-device dependencies.** No apps, no agents, no Accessibility Service installed on the phone.
- **CLI is the single source of truth.** Skill is documentation; future MCP would be a protocol wrapper around CLI.
