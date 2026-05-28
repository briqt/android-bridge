# android-bridge

AI-facing interface for Android device automation via pure ADB. Designed to be called by any AI agent (Claude Code, Cursor, Hermes, etc.) through CLI or Skill.

## Install

### As a Skill (for AI agents)

```bash
npx skills add briqt/android-bridge
```

### As a CLI tool

```bash
git clone https://github.com/briqt/android-bridge.git
cd android-bridge
pip install -e .
```

### Prerequisites

- Python 3.10+
- ADB (Android Debug Bridge) accessible via PATH or `ADB` env var
- Android device with USB debugging enabled (root recommended)

## Usage

```bash
# Connect device (remembers for future commands)
android-bridge connect 192.168.137.96

# Read screen
android-bridge snapshot
android-bridge screenshot --out screen.png

# Interact
android-bridge tap 540 1200
android-bridge swipe 540 1500 540 500
android-bridge press back
android-bridge type "hello"

# Shell
android-bridge shell "dumpsys battery"
android-bridge shell --root "cat /sys/class/power_supply/battery/capacity"
```

## Design

- **LLM is the brain, tool is the hands.** No decision logic in the tool — just atomic operations (perceive, tap, swipe, type).
- **Pure ADB, zero on-device dependencies.** No apps, no agents, no Accessibility Service installed on the phone.
- **CLI is the single source of truth.** Skill is documentation; future MCP would be a protocol wrapper around CLI.
