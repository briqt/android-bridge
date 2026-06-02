"""CLI entry point for android-bridge."""

import json
import os
import sys

import click

from android_bridge import device as dev
from android_bridge import perception, actions


@click.group()
@click.option("--profile", "-p", default=None, help="Device profile to use")
@click.pass_context
def main(ctx, profile):
    """AI-facing interface for Android device automation."""
    ctx.ensure_object(dict)
    if profile:
        dev.set_profile_override(profile)


@main.command()
def devices():
    """List connected ADB devices."""
    devs = dev.list_devices()
    if not devs:
        click.echo("No devices found.")
        sys.exit(1)
    for serial, state in devs:
        click.echo(f"{serial}\t{state}")


@main.command()
@click.argument("serial", required=False)
def connect(serial):
    """Connect to a device (auto-detect if no serial given)."""
    try:
        result = dev.connect(serial)
        click.echo(f"Connected: {result}")
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--vision", is_flag=True, help="Include screenshot")
@click.option("--json-out", "as_json", is_flag=True, help="Output as JSON")
@click.option("--save", type=click.Path(), help="Save screenshot to file")
def snapshot(vision, as_json, save):
    """Capture UI state (text + interactive elements)."""
    try:
        snap = perception.take_snapshot(vision=vision)
        if as_json:
            click.echo(json.dumps(snap.to_dict(), ensure_ascii=False, indent=2))
        else:
            click.echo(snap.to_text())
        if vision and snap.screenshot and save:
            snap.screenshot.save(save)
            click.echo(f"\nScreenshot saved: {save}", err=True)
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--out", type=click.Path(), help="Save to file instead of base64 output")
def screenshot(out):
    """Take a screenshot."""
    try:
        img = perception.take_screenshot()
        if out:
            img.save(out)
            click.echo(f"Saved: {out}")
        else:
            click.echo(perception.screenshot_to_base64(img))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("x", type=int)
@click.argument("y", type=int)
def tap(x, y):
    """Tap a point on screen."""
    try:
        click.echo(actions.tap(x, y))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command("long-tap")
@click.argument("x", type=int)
@click.argument("y", type=int)
def long_tap_cmd(x, y):
    """Long-tap a point."""
    try:
        click.echo(actions.long_tap(x, y))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("x1", type=int)
@click.argument("y1", type=int)
@click.argument("x2", type=int)
@click.argument("y2", type=int)
def swipe(x1, y1, x2, y2):
    """Swipe from (x1,y1) to (x2,y2)."""
    try:
        click.echo(actions.swipe(x1, y1, x2, y2))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command("type")
@click.argument("text")
def type_cmd(text):
    """Type text (ASCII only; use shell for CJK via ADBKeyBoard)."""
    try:
        click.echo(actions.type_text(text))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("button")
def press(button):
    """Press a device button (back, home, enter, power, volume_up, volume_down)."""
    try:
        click.echo(actions.press(button))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("x1", type=int)
@click.argument("y1", type=int)
@click.argument("x2", type=int)
@click.argument("y2", type=int)
def drag(x1, y1, x2, y2):
    """Drag from (x1,y1) to (x2,y2)."""
    try:
        click.echo(actions.drag(x1, y1, x2, y2))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("cmd", required=False)
@click.option("--root", is_flag=True, help="Execute as root (su -c)")
@click.option("--script", "script_file", type=click.Path(exists=True), default=None,
              help="Execute a local script file on the device")
def shell(cmd, root, script_file):
    """Execute a shell command on the device.

    Three modes:

    \b
      1. Inline:  android-bridge shell [--root] "command"
      2. Script:  android-bridge shell [--root] --script path/to/file.sh
      3. Stdin:   echo "cmd" | android-bridge shell [--root]
    """
    try:
        if script_file:
            from pathlib import Path
            content = Path(script_file).read_text()
            result = actions.shell_script(content, root=root)
        elif cmd:
            result = actions.shell(cmd, root=root)
        elif not sys.stdin.isatty():
            content = sys.stdin.read()
            if not content.strip():
                click.echo("ERROR: empty stdin", err=True)
                sys.exit(1)
            result = actions.shell_script(content, root=root)
        else:
            click.echo("ERROR: provide a command, --script file, or pipe via stdin", err=True)
            sys.exit(1)
        click.echo(result)
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("local", type=click.Path(exists=True))
@click.argument("remote")
def push(local, remote):
    """Push a local file/directory to the device."""
    try:
        result = actions.push(local, remote)
        click.echo(result)
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("remote")
@click.argument("local", type=click.Path(), default=".")
def pull(remote, local):
    """Pull a file/directory from the device to local."""
    try:
        result = actions.pull(remote, local)
        click.echo(result)
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)
