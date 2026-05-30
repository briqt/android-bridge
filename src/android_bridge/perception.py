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


def take_snapshot(vision: bool = False) -> Snapshot:
    adb_shell("uiautomator dump /sdcard/window_dump.xml")
    xml_str = adb_shell("cat /sdcard/window_dump.xml")
    adb_shell("rm -f /sdcard/window_dump.xml")
    snapshot = parse_hierarchy(xml_str)
    if vision:
        snapshot.screenshot = take_screenshot()
    return snapshot


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
