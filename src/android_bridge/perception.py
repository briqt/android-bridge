"""Perception layer: UI tree parsing and screenshot capture."""

from xml.etree import ElementTree
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import base64
import re
import subprocess
import tempfile

from PIL import Image

from android_bridge.device import adb_shell, adb, get_serial, _adb_base

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass
class Element:
    index: int
    name: str
    class_name: str
    resource_id: str
    bounds: tuple[int, int, int, int]  # x1, y1, x2, y2
    center: tuple[int, int]
    clickable: bool
    scrollable: bool

    def to_line(self) -> str:
        cx, cy = self.center
        flags = []
        if self.clickable:
            flags.append("click")
        if self.scrollable:
            flags.append("scroll")
        flag_str = f" [{','.join(flags)}]" if flags else ""
        rid = f" #{self.resource_id}" if self.resource_id else ""
        return f"  [{self.index}] {self.name}{rid} ({cx},{cy}){flag_str}"


@dataclass
class Snapshot:
    texts: list[str]
    elements: list[Element]
    screenshot: Image.Image | None = None

    def to_text(self) -> str:
        parts = []
        if self.texts:
            parts.append("=== Visible Text ===")
            for t in self.texts:
                parts.append(f"  {t}")
        parts.append("")
        parts.append("=== Interactive Elements ===")
        for el in self.elements:
            parts.append(el.to_line())
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "texts": self.texts,
            "elements": [
                {
                    "index": e.index,
                    "name": e.name,
                    "class_name": e.class_name,
                    "resource_id": e.resource_id,
                    "center": list(e.center),
                    "bounds": list(e.bounds),
                }
                for e in self.elements
            ],
        }


@dataclass
class DumpNode:
    """A UI node with full attributes — no filtering of labeled-but-non-interactive nodes.

    Unlike Element, DumpNode always carries bounds + content-desc + all flags AND state
    (checked/focused/selected/disabled), so Flutter/Compose apps (which put text in
    content-desc and skip clickable flags) remain visible, tappable, and state-readable.
    """
    index: int
    label: str           # text or content-desc ("" if neither)
    text: str
    content_desc: str
    class_name: str
    resource_id: str
    bounds: tuple[int, int, int, int]  # x1, y1, x2, y2
    center: tuple[int, int]
    # capabilities (what the node CAN do)
    clickable: bool
    long_clickable: bool
    checkable: bool
    scrollable: bool
    # state (what the node IS right now) — the gap this class closes vs Element
    enabled: bool
    selected: bool
    checked: bool        # Switch/Checkbox/RadioButton on/off state
    focused: bool        # which EditText/input currently has focus

    def to_line(self) -> str:
        cx, cy = self.center
        flags = []
        if self.clickable:
            flags.append("click")
        if self.long_clickable:
            flags.append("long-click")
        if self.checkable:
            flags.append("checkable")
        if self.checked:
            flags.append("checked")
        if self.scrollable:
            flags.append("scroll")
        if self.selected:
            flags.append("selected")
        if self.focused:
            flags.append("focused")
        if not self.enabled:
            flags.append("disabled")
        flag_str = f" [{','.join(flags)}]" if flags else ""
        rid = f" rid={self.resource_id}" if self.resource_id else ""
        label = self.label if self.label else "—"
        # Collapse newlines/extra whitespace so one node = one line (content-desc often has \n)
        label = " ".join(label.split())
        if len(label) > 80:
            label = label[:79] + "…"
        cls = self.class_name.split(".")[-1] if self.class_name else ""
        x1, y1, x2, y2 = self.bounds
        return (f"  [{self.index}] {label} ({cx},{cy}){flag_str}"
                f" bounds=[{x1},{y1}][{x2},{y2}] class={cls}{rid}")

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "label": self.label,
            "text": self.text,
            "content_desc": self.content_desc,
            "class": self.class_name,
            "resource_id": self.resource_id,
            "bounds": list(self.bounds),
            "center": list(self.center),
            "clickable": self.clickable,
            "long_clickable": self.long_clickable,
            "checkable": self.checkable,
            "scrollable": self.scrollable,
            "enabled": self.enabled,
            "selected": self.selected,
            "checked": self.checked,
            "focused": self.focused,
        }


@dataclass
class DumpResult:
    """Full UI node dump — preserves all labeled/interactive nodes with coordinates."""
    screen: tuple[int, int]  # width, height
    nodes: list[DumpNode]
    truncated: bool
    total_nodes: int

    def to_text(self) -> str:
        w, h = self.screen
        shown = len(self.nodes)
        parts = [
            "=== UI Dump ===",
            f"screen: {w}x{h}  nodes: {self.total_nodes}  shown: {shown}",
        ]
        if self.truncated:
            parts.append(f"(truncated — use --clickable or --max N to see more)")
        parts.append("")
        for n in self.nodes:
            parts.append(n.to_line())
        return "\n".join(parts)

    def to_dict(self) -> dict:
        w, h = self.screen
        return {
            "screen": {"width": w, "height": h},
            "node_count": self.total_nodes,
            "shown": len(self.nodes),
            "truncated": self.truncated,
            "nodes": [n.to_dict() for n in self.nodes],
        }


def _parse_bounds(bounds_str: str) -> tuple[int, int, int, int] | None:
    m = BOUNDS_RE.match(bounds_str)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def _extract_text(node) -> str:
    return node.get("text", "") or node.get("content-desc", "")


def _is_interactive(node) -> bool:
    return (
        node.get("clickable") == "true"
        or node.get("long-clickable") == "true"
        or node.get("checkable") == "true"
        or node.get("scrollable") == "true"
    )


def parse_hierarchy(xml_str: str) -> Snapshot:
    root = ElementTree.fromstring(xml_str)
    texts: list[str] = []
    elements: list[Element] = []
    idx = 0

    for node in root.iter("node"):
        text = _extract_text(node)
        bounds_str = node.get("bounds", "")
        bounds = _parse_bounds(bounds_str)

        if text and not _is_interactive(node):
            texts.append(text)

        if _is_interactive(node) and bounds:
            x1, y1, x2, y2 = bounds
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            name = text or node.get("class", "").split(".")[-1]
            rid = node.get("resource-id", "")
            if "/" in rid:
                rid = rid.split("/", 1)[1]
            elements.append(Element(
                index=idx,
                name=name,
                class_name=node.get("class", ""),
                resource_id=rid,
                bounds=bounds,
                center=(cx, cy),
                clickable=node.get("clickable") == "true",
                scrollable=node.get("scrollable") == "true",
            ))
            idx += 1

    return Snapshot(texts=texts, elements=elements)


def _has_label(node) -> bool:
    """True if node carries text or content-desc (Flutter puts labels in content-desc)."""
    return bool(node.get("text", "") or node.get("content-desc", ""))


def dump_hierarchy(xml_str: str, mode: str = "default", max_nodes: int = 200) -> DumpResult:
    """Parse UI XML into a full node dump that preserves labeled/interactive nodes.

    Unlike parse_hierarchy (which drops labeled-but-non-interactive nodes' coordinates
    and only emits interactive Elements), dump keeps every node with a label, resource-id,
    or interactive flag — each with bounds + center. This is the reliable perception path
    for Flutter/Compose/Canvas apps whose accessibility trees are sparse.

    mode:
      - "default": nodes with valid bounds AND (label OR resource-id OR interactive)
      - "clickable": only interactive nodes (click/long-click/check/scroll)
      - "all": every node with valid bounds (debug; includes anonymous containers)
    """
    stripped = xml_str.lstrip()
    if not stripped.startswith(("<?xml", "<hierarchy", "<node")):
        preview = stripped[:100]
        raise RuntimeError(
            f"uiautomator dump returned non-XML output: {preview!r}\n"
            f"  Screen may be off — run: android-bridge shell --root "
            f"\"input keyevent KEYCODE_POWER\" then retry"
        )
    root = ElementTree.fromstring(xml_str)
    all_nodes = list(root.iter("node"))

    # Screen size = max extent across all nodes (root window typically spans full screen)
    max_w = max_h = 0
    for n in all_nodes:
        b = _parse_bounds(n.get("bounds", ""))
        if b:
            max_w = max(max_w, b[2])
            max_h = max(max_h, b[3])

    def keep(node):
        b = _parse_bounds(node.get("bounds", ""))
        if not b:
            return False
        if mode == "all":
            return True
        if mode == "clickable":
            return _is_interactive(node)
        return _has_label(node) or bool(node.get("resource-id", "")) or _is_interactive(node)

    kept = [n for n in all_nodes if keep(n)]
    total = len(kept)
    truncated = total > max_nodes
    shown = kept[:max_nodes]

    nodes = []
    for i, n in enumerate(shown):
        b = _parse_bounds(n.get("bounds", ""))
        x1, y1, x2, y2 = b
        text = n.get("text", "")
        desc = n.get("content-desc", "")
        rid = n.get("resource-id", "")
        if "/" in rid:
            rid = rid.split("/", 1)[1]
        nodes.append(DumpNode(
            index=i,
            label=text or desc,
            text=text,
            content_desc=desc,
            class_name=n.get("class", ""),
            resource_id=rid,
            bounds=b,
            center=((x1 + x2) // 2, (y1 + y2) // 2),
            clickable=n.get("clickable") == "true",
            long_clickable=n.get("long-clickable") == "true",
            checkable=n.get("checkable") == "true",
            scrollable=n.get("scrollable") == "true",
            enabled=n.get("enabled") == "true",
            selected=n.get("selected") == "true",
            checked=n.get("checked") == "true",
            focused=n.get("focused") == "true",
        ))

    return DumpResult(screen=(max_w, max_h), nodes=nodes, truncated=truncated, total_nodes=total)


def _capture_ui_xml() -> str:
    """Dump current UI hierarchy to a temp file on device and read it back."""
    adb_shell("uiautomator dump /sdcard/window_dump.xml")
    xml_str = adb_shell("cat /sdcard/window_dump.xml")
    adb_shell("rm -f /sdcard/window_dump.xml")
    return xml_str


def take_snapshot(vision: bool = False) -> Snapshot:
    xml_str = _capture_ui_xml()
    snapshot = parse_hierarchy(xml_str)
    if vision:
        snapshot.screenshot = take_screenshot()
    return snapshot


def take_dump(mode: str = "default", max_nodes: int = 200) -> DumpResult:
    xml_str = _capture_ui_xml()
    return dump_hierarchy(xml_str, mode=mode, max_nodes=max_nodes)


def take_screenshot() -> Image.Image:
    serial = get_serial()
    cmd_base = _adb_base() + ["-s", serial]
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        subprocess.run(
            cmd_base + ["shell", "screencap", "-p", "/sdcard/screen.png"],
            capture_output=True, timeout=10
        )
        subprocess.run(
            cmd_base + ["pull", "/sdcard/screen.png", tmp_path],
            capture_output=True, timeout=10
        )
        subprocess.run(
            cmd_base + ["shell", "rm", "-f", "/sdcard/screen.png"],
            capture_output=True, timeout=5
        )
        img = Image.open(tmp_path)
        img.load()  # Force read before deleting temp file
        return img
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def screenshot_to_base64(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
