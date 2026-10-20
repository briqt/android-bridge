# android-bridge

AI-facing interface for Android device automation via pure ADB. Designed to be called by any AI agent (Claude Code, Cursor, Hermes, etc.) through CLI or Skill.

## Install

### As a Skill (for AI agents)

```bash
npx skills add briqt/android-bridge -g -y
```

### As a CLI tool (standard)

```bash
pipx install git+https://github.com/briqt/android-bridge.git
```

### Update and verify

```bash
pipx install --force git+https://github.com/briqt/android-bridge.git
npx skills add briqt/android-bridge -g -y
android-bridge --version
android-bridge doctor --json
```

Version 0.3.0 adds per-profile `root_mode` (`auto`, `required`, `never`), offline
capability diagnostics, file/stdin text input, and first-cause UI capture errors.
Text payloads are not echoed. Use `type-cjk --file input.txt` for multiline content.

### For development

```bash
git clone https://github.com/briqt/android-bridge.git
cd android-bridge
pipx install --editable .
# after changes: pipx reinstall android-bridge
```

### Prerequisites

- Python 3.11+
- ADB (Android Debug Bridge) on PATH, or set `"adb_path"` in `~/.config/agent-skills/android-bridge/config.json`
- Android device with USB debugging enabled; root is optional and selected per profile

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

## Dependencies verified for 0.3.0

Runtime: Click 8.5.0 and Pillow 13.0.0; build: Hatchling 1.32.4. Pillow 13 requires
Python 3.11+, so this release raises the Python minimum accordingly. Test/build
extras use pytest 9.1.1 and build 1.6.1 (`pip install -e '.[dev]'`). Input streams
use Python's stdin API rather than Click's deprecated get_text_stream helper.
