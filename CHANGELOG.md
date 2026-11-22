# Changelog

## v0.4.0

- Configuration comes only from `~/.config/agent-skills/android-bridge/config.json`: the `.config.json` lookup in the current working directory is removed, and an invalid file now fails with `CONFIG_INVALID` instead of being used or skipped. `ANDROID_BRIDGE_HOME` relocates the runtime directory (for isolated tests). `connect` merges into that file, preserving other settings.
- Add update checks against `notice.json` on the main branch: `check-update [--json]`, plus a bounded hourly check after successful commands (2-second budget, 5-minute retry, 24-hour reminder cooldown per version and per notice). Notices go to stderr only; `doctor`, help and version stay offline. Disable with `--no-update-check`, `ANDROID_BRIDGE_NO_UPDATE_CHECK=1` or `"disable_update_check": true`.
- The skill moves to `skills/android-bridge/`, and the config template and schema move in with it. Installed skills follow automatically on the next `npx skills add briqt/android-bridge -g -y` or `npx skills update`.
- The package version is maintained only in `src/android_bridge/__init__.py`; tests check that SKILL.md `metadata.version` matches it.
- Skill description states the capability boundary instead of listing scenarios; examples no longer use a specific personal device.

## v0.3.0

- Pin the latest stable Click 8.5.0, Pillow 13.0.0 and Hatchling 1.32.4; use pytest 9.1.1/build 1.6.1 for development. Python 3.11+ is now required by Pillow 13.

- Support non-root Android devices with per-profile auto|required|never privilege modes. Preserve profile settings on reconnect.
- Add offline doctor/version diagnostics and document the separate CLI/skill update commands.
- Preserve uiautomator failure categories and use unique temporary capture paths.
- Add UTF-8 file/stdin input without payload echoes; restore the previous IME on failures.
- Create requested screenshot parent directories and check screencap/pull failures.
- Add device-free regression coverage for privileges, capture failure recovery, and safe input.
