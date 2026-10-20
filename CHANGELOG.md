# Changelog

## v0.3.0

- Pin the latest stable Click 8.5.0, Pillow 13.0.0 and Hatchling 1.32.4; use pytest 9.1.1/build 1.6.1 for development. Python 3.11+ is now required by Pillow 13.

- Support non-root Android devices with per-profile auto|required|never privilege modes. Preserve profile settings on reconnect.
- Add offline doctor/version diagnostics and document the separate CLI/skill update commands.
- Preserve uiautomator failure categories and use unique temporary capture paths.
- Add UTF-8 file/stdin input without payload echoes; restore the previous IME on failures.
- Create requested screenshot parent directories and check screencap/pull failures.
- Add device-free regression coverage for privileges, capture failure recovery, and safe input.
