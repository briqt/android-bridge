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
    # Profile header on stderr first line of every command (per my-skill-creator spec:
    # "每条命令的输出必须在 stderr 首行标明当前 profile，无论成功失败都必须输出").
    try:
        resolved = dev._resolve_profile() or "default"
    except Exception:
        resolved = "default"
    click.echo(f"[profile: {resolved}]", err=True)


@main.command()
def devices():
    """List connected ADB devices."""
    devs = dev.list_devices()
    if not devs:
        click.echo("No devices found.", err=True)
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
@click.option("--vision", is_flag=True, help="(deprecated) capture screenshot; --out is now self-sufficient")
@click.option("--json-out", "as_json", is_flag=True, help="Output as JSON")
@click.option("--out", "--save", "out", type=click.Path(), help="Save a screenshot to file")
def snapshot(vision, as_json, out):
    """Capture UI state (text + interactive elements)."""
    try:
        # --out implies capture (decoupled from --vision): `snapshot --out x.png` works alone.
        snap = perception.take_snapshot(vision=vision or bool(out))
        if as_json:
            click.echo(json.dumps(snap.to_dict(), ensure_ascii=False, indent=2))
        else:
            click.echo(snap.to_text())
        if out and snap.screenshot:
            snap.screenshot.save(out)
            click.echo(f"\nScreenshot saved: {out}", err=True)
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--json-out", "as_json", is_flag=True, help="Output as JSON")
@click.option("--clickable", is_flag=True, help="Only interactive nodes (click/long-click/check/scroll)")
@click.option("--all", "all_nodes", is_flag=True, help="Include anonymous layout containers (debug)")
@click.option("--max", "max_nodes", type=int, default=200, help="Max nodes to show (default 200)")
@click.option("--out", type=click.Path(), help="Save a screenshot to file alongside the dump")
def dump(as_json, clickable, all_nodes, max_nodes, out):
    """Full UI node dump — use for Flutter/Compose apps with sparse accessibility trees.

    Unlike snapshot, dump preserves EVERY node with a label, resource-id, or interactive
    flag, each with bounds + center + content-desc. Flutter apps put text in content-desc
    and often skip clickable flags, so snapshot drops them — dump keeps them.

    Use when snapshot shows too few elements, or target elements appear as label-less
    ImageView/View. Default filter keeps labeled + interactive nodes; --clickable narrows
    to interactive only; --all includes anonymous containers.
    """
    try:
        mode = "all" if all_nodes else ("clickable" if clickable else "default")
        result = perception.take_dump(mode=mode, max_nodes=max_nodes)
        if as_json:
            click.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            click.echo(result.to_text())
        if result.total_nodes == 0:
            click.echo(
                "\nWARNING: accessibility tree empty (0 nodes). Screen may be off, "
                "locked, or FLAG_SECURE.\n"
                "         Run `android-bridge screenshot --out shot.png` to verify visually.",
                err=True,
            )
        if result.truncated:
            click.echo(
                f"\nTip: truncated ({result.total_nodes} nodes total, {max_nodes} shown) "
                f"— use --clickable or --max N.",
                err=True,
            )
        if out:
            img = perception.take_screenshot()
            img.save(out)
            click.echo(f"\nScreenshot saved: {out}", err=True)
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
    """Type text (ASCII only; use type-cjk for CJK/unicode)."""
    try:
        click.echo(actions.type_text(text))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command("type-cjk")
@click.argument("text")
@click.option("--at", nargs=2, type=int, default=None, help="Tap coordinates (x y) to focus field first")
def type_cjk_cmd(text, at):
    """Type CJK/unicode text via ADBKeyBoard.

    Automatically handles IME switching and InputConnection establishment.
    Use --at x y to tap the input field before typing.
    """
    try:
        tap_x, tap_y = at if at else (None, None)
        click.echo(actions.type_cjk(text, tap_x, tap_y))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command("clear-field")
@click.option("--at", nargs=2, type=int, default=None, help="Tap coordinates (x y) to focus field first")
def clear_field_cmd(at):
    """Clear the focused input field via ADBKeyBoard.

    Requires ADBKeyBoard installed. Use --at x y to tap the field first.
    """
    try:
        tap_x, tap_y = at if at else (None, None)
        click.echo(actions.clear_field(tap_x, tap_y))
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command("select-all")
@click.option("--at", nargs=2, type=int, default=None, help="Tap coordinates (x y) to focus field first")
def select_all_cmd(at):
    """Select all text in the focused field via ADBKeyBoard Ctrl+A.

    Use --at x y to tap the field first.
    """
    try:
        tap_x, tap_y = at if at else (None, None)
        click.echo(actions.select_all(tap_x, tap_y))
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


if __name__ == "__main__":
    main()
