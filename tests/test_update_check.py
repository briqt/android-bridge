"""Update check (notice.json manifest) and repository consistency tests."""

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from android_bridge import __version__, cli, device
from android_bridge.update_check import (
    DAY_MS,
    HOUR_MS,
    check_update,
    evaluate_notifications,
    is_update_disabled,
    newer,
    stable_version,
    upgrade_command,
    validate_manifest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "android-bridge"
RELEASE = "https://github.com/briqt/android-bridge/releases/tag/v{}"


def manifest(version="0.5.0", notice_id="n1", notice="Important notice"):
    return {"schema_version": 1, "latest_version": version, "release_url": RELEASE.format(version),
            "notice_id": notice_id, "notice": notice}


def test_semver_and_manifest_validation():
    assert stable_version("v0.4.0") == (0, 4, 0)
    assert stable_version("0.4.0-rc.1") is None
    assert newer("0.10.0", "0.9.0")
    assert not newer("0.4.0", "0.4.0")
    valid = validate_manifest(manifest(notice="Hello\x1b[31mWorld"))
    assert valid["latest_version"] == "0.5.0"
    assert "\x1b" not in valid["notice"]
    for bad in (
        {**manifest(), "schema_version": 2},
        {**manifest(), "release_url": "https://evil.example.com/briqt/android-bridge/releases/tag/v0.5.0"},
        {**manifest(), "release_url": "https://github.com/briqt/siyuan-cli/releases/tag/v0.5.0"},
        manifest(notice_id="n1", notice=""),
        manifest(notice="x" * 1001),
    ):
        with pytest.raises(ValueError):
            validate_manifest(bad)


def test_throttle_cooldown_and_stale_notice_suppression(tmp_path):
    calls = 0

    def opener(_url, _timeout):
        nonlocal calls
        calls += 1
        return json.dumps(manifest()).encode("utf-8")

    emitted = []
    t0 = 1_800_000_000_000
    r1 = check_update(tmp_path, current="0.4.0", now_ms=t0, opener_fn=opener, emit=emitted.append)
    assert r1["status"] == "checked" and r1["update_available"]
    assert len(emitted) == 2
    assert f"Upgrade CLI: {upgrade_command()}" in emitted[0]

    r2 = check_update(tmp_path, current="0.4.0", now_ms=t0 + 60_000, opener_fn=opener, emit=emitted.append)
    assert r2["status"] == "cached" and calls == 1 and len(emitted) == 2

    r3 = check_update(tmp_path, current="0.4.0", now_ms=t0 + 25 * HOUR_MS, opener_fn=opener, emit=emitted.append)
    assert r3["status"] == "checked" and calls == 2 and len(emitted) == 4

    old = {"last_success_at": t0, "manifest": manifest(version="0.3.1", notice_id="old", notice="Old")}
    assert evaluate_notifications(old, "0.4.0", t0) == []
    old["manifest"]["latest_version"] = "0.9.0"
    assert evaluate_notifications(old, "0.4.0", t0 + 8 * DAY_MS) == []

    assert is_update_disabled(no_update_check=True)
    assert is_update_disabled(config_disabled=True)
    assert is_update_disabled(env={"ANDROID_BRIDGE_NO_UPDATE_CHECK": "1"})
    assert not is_update_disabled(env={})


def test_failures_back_off_and_never_raise(tmp_path):
    def failing(_url, _timeout):
        raise RuntimeError("offline")

    t0 = 1_800_000_000_000
    r = check_update(tmp_path, current="0.4.0", now_ms=t0, opener_fn=failing, emit=lambda _t: None)
    assert r["status"] == "unavailable"
    state = json.loads((tmp_path / "update_check.json").read_text())
    assert state["next_check_at"] == t0 + 5 * 60_000
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x")
    assert check_update(not_a_dir, current="0.4.0", opener_fn=failing)["status"] == "unavailable"


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(device, "CONFIG_FILE", tmp_path / "home" / "config.json")
    monkeypatch.setattr(device, "_profile_override", None)
    monkeypatch.setattr(device, "_cached_serial", None)
    monkeypatch.setattr(device, "_config_loaded", False)
    monkeypatch.delenv("ANDROID_BRIDGE_NO_UPDATE_CHECK", raising=False)
    return tmp_path / "home"


def test_cli_disable_paths_never_touch_network(isolated_home, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("must not fetch")

    monkeypatch.setattr("android_bridge.update_check.fetch_manifest", boom)
    runner = CliRunner()
    res = runner.invoke(cli.main, ["--no-update-check", "check-update", "--json"])
    assert res.exit_code == 0 and json.loads(res.stdout)["status"] == "disabled"
    monkeypatch.setenv("ANDROID_BRIDGE_NO_UPDATE_CHECK", "1")
    res = runner.invoke(cli.main, ["check-update", "--json"])
    assert json.loads(res.stdout)["status"] == "disabled"
    monkeypatch.delenv("ANDROID_BRIDGE_NO_UPDATE_CHECK")
    isolated_home.mkdir(parents=True, exist_ok=True)
    (isolated_home / "config.json").write_text(json.dumps({"disable_update_check": True}))
    res = runner.invoke(cli.main, ["check-update", "--json"])
    assert json.loads(res.stdout)["status"] == "disabled"
    # doctor stays offline even when checks are enabled
    (isolated_home / "config.json").write_text("{}")
    res = runner.invoke(cli.main, ["doctor", "--json"])
    assert res.exit_code == 0
    for args in (["--version"], ["--help"], ["check-update", "--help"]):
        assert runner.invoke(cli.main, args).exit_code == 0


def test_auto_check_runs_after_success_and_writes_only_stderr(isolated_home, monkeypatch):
    calls = []
    monkeypatch.setattr("android_bridge.update_check.fetch_manifest",
                        lambda **_k: calls.append(1) or validate_manifest(manifest(version="99.0.0", notice_id="", notice="")))
    monkeypatch.setattr(device, "list_devices", lambda: [("serial1", "device")])
    res = CliRunner().invoke(cli.main, ["devices"])
    assert res.exit_code == 0
    assert res.stdout == "serial1\tdevice\n"
    assert "[android-bridge update] 99.0.0 available" in res.stderr
    assert calls == [1]


def test_skill_version_config_template_and_notice_stay_in_sync():
    skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r'^\s+version:\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*$', skill_md, re.MULTILINE)
    assert m, "skills/android-bridge/SKILL.md must declare metadata.version"
    assert m.group(1) == __version__
    template = json.loads((SKILL_DIR / "config.json").read_text(encoding="utf-8"))
    schema = json.loads((SKILL_DIR / "config.schema.json").read_text(encoding="utf-8"))
    assert set(template) <= set(schema["properties"])
    assert template["disable_update_check"] is False
    notice = REPO_ROOT / "notice.json"
    if notice.exists():
        validated = validate_manifest(json.loads(notice.read_text(encoding="utf-8")))
        assert not newer(validated["latest_version"], __version__)


def test_upgrade_command_matches_install_channel():
    uv = upgrade_command("/home/u/.local/share/uv/tools/android-bridge")
    assert uv == "uv tool install --force --reinstall --refresh git+https://github.com/briqt/android-bridge.git"
    pipx = upgrade_command(r"C:\Users\ts\pipx\venvs\android-bridge")
    assert pipx == "pipx uninstall android-bridge; pipx install git+https://github.com/briqt/android-bridge.git"
    assert "--force" not in pipx
    other = upgrade_command("/usr")
    assert uv in other and pipx in other
