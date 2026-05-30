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
