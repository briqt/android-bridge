import json
import subprocess
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner
from android_bridge import actions, cli, device, perception


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(device, "CONFIG_FILE", tmp_path / "missing-config.json")
    monkeypatch.setattr(device, "_profile_override", None)
    monkeypatch.setattr(device, "_cached_serial", None)
    monkeypatch.setattr(device, "_config_loaded", False)


def test_unrooted_input_never_calls_su():
    with patch.object(device, "adb_shell", return_value="") as shell:
        actions.tap(12, 34)
    shell.assert_called_once_with("input tap 12 34")


def test_auto_retries_only_explicit_permission_denial():
    denied = device.BridgeError("ADB_COMMAND_FAILED", "SecurityException: INJECT_EVENTS permission denied")
    with patch.object(device, "adb_shell", side_effect=[denied, ""]) as shell:
        actions.press("back")
    assert shell.call_args_list[0].kwargs == {}
    assert shell.call_args_list[1].kwargs == {"root": True}


@pytest.mark.parametrize("mode,expected", [("required", {"root": True}), ("never", {})])
def test_explicit_privilege_mode(monkeypatch, mode, expected):
    monkeypatch.setattr(device, "_load_full_config", lambda: {"root_mode": mode})
    with patch.object(device, "adb_shell", return_value="") as shell:
        actions.swipe(1, 2, 3, 4)
    assert shell.call_args.kwargs == expected


@pytest.mark.parametrize("mode", ["auto", "never"])
def test_offline_failure_does_not_repeat_action(monkeypatch, mode):
    monkeypatch.setattr(device, "_load_full_config", lambda: {"root_mode": mode})
    with patch.object(device, "adb_shell", side_effect=device.BridgeError("ADB_OFFLINE", "device offline")) as shell:
        with pytest.raises(device.BridgeError, match="ADB_OFFLINE"):
            actions.tap(1, 2)
    assert shell.call_count == 1


def test_profile_mode_and_reconnect_preserve_settings(tmp_path):
    source = tmp_path / ".config.json"
    source.write_text(json.dumps({"active": "phone", "profiles": {"phone": {"serial": "one", "root_mode": "never"}}}))
    assert device.root_mode() == "never"
    device._save_config("two", "phone")
    assert json.loads(source.read_text())["profiles"]["phone"]["root_mode"] == "never"


def test_shell_nonzero_with_stdout_keeps_original_error(monkeypatch):
    monkeypatch.setattr(device, "_adb_base", lambda: ["adb"])
    result = subprocess.CompletedProcess([], 1, stdout="partial output", stderr="permission denied")
    with patch.object(device.subprocess, "run", return_value=result):
        with pytest.raises(device.BridgeError, match="permission denied.*",):
            device.adb_shell("false")


@pytest.mark.parametrize("message,code", [("ERROR: null root node returned", "UI_ROOT_UNAVAILABLE"), ("ERROR: could not get idle state", "UI_NOT_IDLE")])
def test_dump_keeps_first_failure_and_never_reads_missing_xml(message, code):
    with patch.object(perception, "adb_shell", side_effect=[message, ""]) as shell:
        with pytest.raises(device.BridgeError, match=code):
            perception._capture_ui_xml()
    assert not any(call.args[0].startswith("cat ") for call in shell.call_args_list)


def test_dump_paths_are_unique_and_cleaned_up():
    def respond(command):
        return '<hierarchy/>' if command.startswith("cat ") else ""
    with patch.object(perception, "adb_shell", side_effect=respond) as shell:
        assert perception._capture_ui_xml() == '<hierarchy/>'
        assert perception._capture_ui_xml() == '<hierarchy/>'
    dumps = [c.args[0] for c in shell.call_args_list if c.args[0].startswith("uiautomator ")]
    assert dumps[0] != dumps[1]
    assert len([c for c in shell.call_args_list if c.args[0].startswith("rm -f ")]) == 2


def test_keyboard_is_restored_even_when_broadcast_fails():
    original = "com.example.keyboard/.IME"
    with patch.object(actions, "_get_current_ime", return_value=original), patch("time.sleep"):
        with patch.object(actions, "action_shell", side_effect=["", RuntimeError("broadcast failed"), ""]) as shell:
            with pytest.raises(RuntimeError, match="broadcast failed"):
                actions.type_cjk("text")
    assert shell.call_args.args[0] == f"ime set {original}"


@pytest.mark.parametrize("command", ["type", "type-cjk"])
@pytest.mark.parametrize("source", ["stdin", "file"])
def test_multiline_input_is_not_an_option_or_echoed(tmp_path, command, source):
    secret = "-----BEGIN TEST-----\n中文🙂\n-----END TEST-----\n"
    args = [command]
    if source == "file":
        path = tmp_path / "input.txt"; path.write_text(secret)
        args += ["--file", str(path)]
    else:
        args += ["--stdin"]
    operation = "type_cjk" if command == "type-cjk" else "type_text"
    with patch.object(actions, operation, return_value="Typed characters") as invoke:
        result = CliRunner().invoke(cli.main, args, input=secret if source == "stdin" else None)
    assert result.exit_code == 0, result.output
    assert invoke.call_args.args[0] == secret
    assert secret not in result.output


def test_input_errors_do_not_echo_payload():
    secret = "private input"
    with patch.object(actions, "type_cjk", side_effect=RuntimeError(secret)):
        result = CliRunner().invoke(cli.main, ["type-cjk", "--stdin"], input=secret)
    assert result.exit_code == 1
    assert secret not in result.output
    assert "INPUT_FAILED" in result.stderr


def test_doctor_is_offline_and_exposes_capabilities():
    with patch.object(device, "adb_shell", side_effect=AssertionError("must not touch device")):
        result = CliRunner().invoke(cli.main, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["version"] == "0.3.0"
    assert "stdin-input" in report["capabilities"]


def test_shell_script_delegates_without_reparsing_or_losing_root():
    script = "printf '%s\\n' '中文'\nexit 0\n"
    with patch.object(device, "adb_shell_script", return_value="ok") as invoke:
        assert actions.shell_script(script, root=True) == "ok"
    invoke.assert_called_once_with(script, root=True)
