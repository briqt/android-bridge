"""Tests for android-bridge core logic (no device required)."""

import json
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from android_bridge import perception, device


# --- perception.parse_hierarchy ---

SAMPLE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="下午3:53" resource-id="" class="android.widget.TextView"
        package="com.miui.home" content-desc="" checkable="false" checked="false"
        clickable="false" enabled="true" focusable="false" focused="false"
        scrollable="false" long-clickable="false" password="false" selected="false"
        bounds="[440,370][640,420]" />
  <node index="1" text="设置" resource-id="com.miui.home:id/icon_title" class="android.widget.TextView"
        package="com.miui.home" content-desc="" checkable="false" checked="false"
        clickable="true" enabled="true" focusable="true" focused="false"
        scrollable="false" long-clickable="true" password="false" selected="false"
        bounds="[860,750][980,860]" />
  <node index="2" text="" resource-id="com.miui.home:id/scroll_view" class="android.widget.ScrollView"
        package="com.miui.home" content-desc="" checkable="false" checked="false"
        clickable="false" enabled="true" focusable="false" focused="false"
        scrollable="true" long-clickable="false" password="false" selected="false"
        bounds="[0,0][1080,2400]" />
</hierarchy>
"""


def test_parse_hierarchy_texts():
    snap = perception.parse_hierarchy(SAMPLE_XML)
    assert "下午3:53" in snap.texts


def test_parse_hierarchy_interactive_elements():
    snap = perception.parse_hierarchy(SAMPLE_XML)
    assert len(snap.elements) == 2  # clickable "设置" + scrollable ScrollView

    settings = snap.elements[0]
    assert settings.name == "设置"
    assert settings.clickable is True
    assert settings.center == (920, 805)
    assert settings.resource_id == "icon_title"

    scroll = snap.elements[1]
    assert scroll.scrollable is True
    assert scroll.clickable is False


def test_parse_hierarchy_to_text():
    snap = perception.parse_hierarchy(SAMPLE_XML)
    text = snap.to_text()
    assert "=== Visible Text ===" in text
    assert "=== Interactive Elements ===" in text
    assert "(920,805)" in text


def test_parse_hierarchy_to_dict():
    snap = perception.parse_hierarchy(SAMPLE_XML)
    d = snap.to_dict()
    assert "texts" in d
    assert "elements" in d
    assert d["elements"][0]["center"] == [920, 805]


# --- device config loading ---

def test_load_full_config_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_data = {"active": "test", "profiles": {"test": {"serial": "1.2.3.4:5555"}}}
    (tmp_path / ".config.json").write_text(json.dumps(config_data))

    # Reset cached state
    device._cached_serial = None
    device._config_loaded = False
    device._profile_override = None

    config = device._load_full_config()
    assert config["active"] == "test"


def test_resolve_profile_override():
    device._profile_override = "myphone"
    assert device._resolve_profile() == "myphone"
    device._profile_override = None


# --- actions (mocked) ---

@patch("android_bridge.actions.adb_shell")
def test_tap_calls_adb(mock_shell):
    from android_bridge import actions
    result = actions.tap(100, 200)
    mock_shell.assert_called_once_with("input tap 100 200", root=True)
    assert "100" in result and "200" in result


@patch("android_bridge.actions.adb_shell")
def test_type_text_escapes_quotes(mock_shell):
    from android_bridge import actions
    actions.type_text("it's a test")
    call_args = mock_shell.call_args[0][0]
    # Should use shlex.quote, not raw single quotes
    assert "'" not in call_args or "\\'" in call_args or "'\"'\"'" in call_args or "it\\'s" in call_args or "'it'\\''s a test'" in call_args


@patch("android_bridge.actions.adb_shell")
def test_press_maps_button(mock_shell):
    from android_bridge import actions
    actions.press("back")
    mock_shell.assert_called_once_with("input keyevent KEYCODE_BACK", root=True)


# --- perception.dump_hierarchy ---

DUMP_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="标题" resource-id="" class="android.widget.TextView"
        content-desc="" clickable="false" scrollable="false" long-clickable="false" checkable="false"
        bounds="[0,100][1080,200]" />
  <node index="1" text="" resource-id="" class="android.widget.ImageView"
        content-desc="底部tab" clickable="false" scrollable="false" long-clickable="false" checkable="false"
        bounds="[800,1800][1080,1900]" />
  <node index="2" text="" resource-id="com.app:id/btn" class="android.widget.Button"
        content-desc="" clickable="true" scrollable="false" long-clickable="false" checkable="false"
        bounds="[100,300][200,400]" />
  <node index="3" text="" resource-id="" class="android.view.View"
        content-desc="" clickable="false" scrollable="false" long-clickable="false" checkable="false"
        bounds="[0,0][1080,2400]" />
</hierarchy>"""


def test_dump_default_keeps_labeled_and_interactive():
    r = perception.dump_hierarchy(DUMP_XML)
    # 标题 (labeled text), 底部tab (content-desc-only), btn (interactive+rid); root View anonymous → dropped
    assert r.total_nodes == 3
    labels = [n.label for n in r.nodes]
    assert "标题" in labels
    assert "底部tab" in labels
    # content-desc-only non-clickable node keeps bounds+center (the Flutter bottom-tab case snapshot drops)
    tab = [n for n in r.nodes if n.label == "底部tab"][0]
    assert tab.center == (940, 1850)
    assert tab.bounds == (800, 1800, 1080, 1900)
    assert tab.clickable is False


def test_dump_clickable_only():
    r = perception.dump_hierarchy(DUMP_XML, mode="clickable")
    assert r.total_nodes == 1
    assert r.nodes[0].resource_id == "btn"
    assert r.nodes[0].clickable is True


def test_dump_all_includes_anonymous():
    r = perception.dump_hierarchy(DUMP_XML, mode="all")
    assert r.total_nodes == 4  # includes the anonymous root View


def test_dump_truncation():
    r = perception.dump_hierarchy(DUMP_XML, max_nodes=2)
    assert r.truncated is True
    assert len(r.nodes) == 2
    assert r.total_nodes == 3


def test_dump_screen_size():
    r = perception.dump_hierarchy(DUMP_XML)
    assert r.screen == (1080, 2400)


def test_dump_non_xml_friendly_error():
    with pytest.raises(RuntimeError) as exc:
        perception.dump_hierarchy("ERROR: null root node")
    assert "non-XML" in str(exc.value)
    assert "KEYCODE_POWER" in str(exc.value)


def test_dump_to_dict_has_all_flags():
    r = perception.dump_hierarchy(DUMP_XML, mode="clickable")
    d = r.to_dict()
    n = d["nodes"][0]
    for key in ("clickable", "long_clickable", "checkable", "scrollable", "bounds", "center", "content_desc"):
        assert key in n


def test_dump_label_collapses_newlines():
    xml = ('<?xml version="1.0"?><hierarchy>'
           '<node text="line1&#10;line2" resource-id="" class="android.widget.TextView" '
           'content-desc="" clickable="false" scrollable="false" long-clickable="false" checkable="false" '
           'bounds="[0,0][10,10]" /></hierarchy>')
    r = perception.dump_hierarchy(xml)
    line = r.nodes[0].to_line()
    assert "\n" not in line
    assert "line1" in line and "line2" in line


# --- device config write-back (A6 regression: save must write to loaded source path) ---

def test_save_config_writes_to_dev_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    device._cached_serial = None
    device._config_loaded = False
    device._profile_override = None
    (tmp_path / ".config.json").write_text(json.dumps({"profiles": {"mi11": {"serial": "1.2.3.4:5555"}}}))

    device._save_config("5.6.7.8:5555", profile="mi11")

    # Must write back to .config.json (dev override), NOT split to CONFIG_FILE
    written = json.loads((tmp_path / ".config.json").read_text())
    assert written["profiles"]["mi11"]["serial"] == "5.6.7.8:5555"
    assert written["active"] == "mi11"


def test_load_full_config_with_path_returns_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    device._cached_serial = None
    device._config_loaded = False
    device._profile_override = None
    (tmp_path / ".config.json").write_text(json.dumps({"active": "x"}))

    config, path = device._load_full_config_with_path()
    assert path == tmp_path / ".config.json"
    assert config["active"] == "x"


# --- CLI profile header + error stream (A3, A4) ---

from click.testing import CliRunner
from android_bridge import cli


def test_cli_profile_header_on_stderr(monkeypatch):
    monkeypatch.setattr(device, "_profile_override", None)
    monkeypatch.setattr(device, "_resolve_profile", lambda: "testphone")
    runner = CliRunner()
    with patch("android_bridge.device.list_devices", return_value=[]):
        result = runner.invoke(cli.main, ["devices"])
    assert result.exit_code == 1
    assert "[profile: testphone]" in result.stderr
    assert "No devices found." in result.stderr


def test_cli_devices_error_not_on_stdout(monkeypatch):
    monkeypatch.setattr(device, "_profile_override", None)
    monkeypatch.setattr(device, "_resolve_profile", lambda: "default")
    runner = CliRunner()
    with patch("android_bridge.device.list_devices", return_value=[]):
        result = runner.invoke(cli.main, ["devices"])
    assert "No devices found." not in result.stdout
    assert "No devices found." in result.stderr


def test_cli_dump_help_lists_options(monkeypatch):
    monkeypatch.setattr(device, "_profile_override", None)
    monkeypatch.setattr(device, "_resolve_profile", lambda: "default")
    runner = CliRunner()
    result = runner.invoke(cli.main, ["dump", "--help"])
    assert result.exit_code == 0
    for opt in ("--json-out", "--clickable", "--all", "--max", "--out"):
        assert opt in result.output
