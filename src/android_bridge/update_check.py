"""Optional bounded update & notice check for android-bridge (manifest: notice.json on main)."""

from __future__ import annotations

import errno
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from . import __version__

ENDPOINT = "https://raw.githubusercontent.com/briqt/android-bridge/main/notice.json"
USER_AGENT = f"android-bridge/{__version__}"
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
MAX_BYTES = 64 * 1024
SEMVER_RE = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\+[\da-zA-Z-]+(?:\.[\da-zA-Z-]+)*)?$"
)
RELEASE_PATH_RE = re.compile(r"^/briqt/android-bridge/releases/tag/[A-Za-z0-9._-]+$")
NOTICE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{0,100}$")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirects are disallowed for update manifest", headers, fp)


def stable_version(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or len(value) > 100:
        return None
    match = SEMVER_RE.match(value)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def newer(remote: Any, current: Any) -> bool:
    a = stable_version(remote)
    b = stable_version(current)
    if a is None or b is None:
        return False
    return a > b


def clean_text(value: str) -> str:
    return CTRL_RE.sub(" ", ANSI_RE.sub("", value))


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not stable_version(value.get("latest_version")):
        raise ValueError("Invalid manifest schema or stable version")
    release_url = value.get("release_url")
    if not isinstance(release_url, str) or len(release_url) > 500:
        raise ValueError("Invalid release URL")
    parsed = urllib.parse.urlsplit(release_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not RELEASE_PATH_RE.match(parsed.path)
    ):
        raise ValueError("Release URL is outside the distribution repository")
    notice_id = value.get("notice_id")
    notice = value.get("notice")
    if (
        not isinstance(notice_id, str)
        or not NOTICE_ID_RE.match(notice_id)
        or not isinstance(notice, str)
        or len(notice) > 1000
        or bool(notice_id) != bool(notice)
    ):
        raise ValueError("Invalid notice")
    clean_ver = value["latest_version"].lstrip("v").split("+")[0]
    return {
        "schema_version": 1,
        "latest_version": clean_ver,
        "release_url": urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")),
        "notice_id": notice_id,
        "notice": clean_text(notice),
    }


def fetch_manifest(timeout_seconds: float = 2.0, opener_fn: Callable[..., Any] | None = None) -> dict[str, Any]:
    if opener_fn is not None:
        raw_bytes = opener_fn(ENDPOINT, timeout_seconds)
        if len(raw_bytes) > MAX_BYTES:
            raise ValueError("Manifest is too large")
        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Manifest is not valid JSON") from exc
        return validate_manifest(parsed)

    req = urllib.request.Request(ENDPOINT, headers={"User-Agent": USER_AGENT})
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(req, timeout=timeout_seconds) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > MAX_BYTES:
                raise ValueError("Manifest is too large")
            data = resp.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("Manifest is too large")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Update endpoint returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        raise RuntimeError("Update check timed out or failed") from exc

    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Manifest is not valid JSON") from exc
    return validate_manifest(parsed)


def _is_valid_ts(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0


def load_state(file: Path, now_ms: int) -> dict[str, Any]:
    try:
        state = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(state, dict):
        return {}
    time_fields = ("last_success_at", "next_check_at", "last_notified_version_at", "last_notified_notice_at")
    for key in time_fields:
        if key in state and not _is_valid_ts(state[key]):
            state.pop(key, None)
    if state.get("next_check_at", 0) > now_ms + HOUR_MS:
        return {}
    if any(state.get(k, 0) > now_ms for k in time_fields if k != "next_check_at"):
        return {}
    if "manifest" in state:
        try:
            state["manifest"] = validate_manifest(state["manifest"])
        except ValueError:
            state.pop("manifest", None)
    return state


def save_state(file: Path, state: dict[str, Any]) -> None:
    tmp = file.parent / f".{file.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, file)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def evaluate_notifications(state: dict[str, Any], current: str, now_ms: int) -> list[dict[str, str]]:
    manifest = state.get("manifest")
    last_ok = state.get("last_success_at")
    if not isinstance(manifest, dict) or not _is_valid_ts(last_ok) or now_ms - last_ok > 7 * DAY_MS:
        return []
    tips: list[dict[str, str]] = []
    latest = manifest["latest_version"]
    if newer(latest, current) and (
        state.get("last_notified_version") != latest
        or not _is_valid_ts(state.get("last_notified_version_at"))
        or now_ms - state["last_notified_version_at"] >= DAY_MS
    ):
        tips.append(
            {
                "kind": "version",
                "id": latest,
                "text": (
                    f"[android-bridge update] {latest} available (current {current}): {manifest['release_url']}\n"
                    "Upgrade CLI: pipx install --force git+https://github.com/briqt/android-bridge.git\n"
                    "Sync companion skill: npx skills add briqt/android-bridge -g -y"
                ),
            }
        )
    notice_id = manifest.get("notice_id", "")
    if (
        notice_id
        and not newer(current, latest)
        and (
            state.get("last_notified_notice") != notice_id
            or not _is_valid_ts(state.get("last_notified_notice_at"))
            or now_ms - state["last_notified_notice_at"] >= DAY_MS
        )
    ):
        tips.append({"kind": "notice", "id": notice_id, "text": f"[android-bridge notice] {manifest['notice']}"})
    return tips


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno != errno.ESRCH


def acquire_lock(directory: Path) -> Callable[[], None] | None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_file = directory / "update_check.lock"
    token = uuid.uuid4().hex

    def _take() -> Callable[[], None]:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, json.dumps({"pid": os.getpid(), "token": token}).encode("utf-8"))
        finally:
            os.close(fd)

        def _release() -> None:
            try:
                cur = json.loads(lock_file.read_text(encoding="utf-8"))
                if isinstance(cur, dict) and cur.get("token") == token:
                    lock_file.unlink(missing_ok=True)
            except (OSError, json.JSONDecodeError):
                pass

        return _release

    try:
        return _take()
    except FileExistsError:
        pass

    reap_dir = directory / "update_check.lock.reap"
    try:
        reap_dir.mkdir()
    except OSError:
        return None
    try:
        try:
            owner = json.loads(lock_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        pid = owner.get("pid") if isinstance(owner, dict) else None
        if not isinstance(pid, int) or _pid_alive(pid):
            return None
        lock_file.unlink(missing_ok=True)
        try:
            return _take()
        except FileExistsError:
            return None
    finally:
        try:
            reap_dir.rmdir()
        except OSError:
            pass


def is_update_disabled(
    *,
    no_update_check: bool = False,
    config_disabled: bool = False,
    env: dict[str, str] | None = None,
) -> bool:
    if no_update_check or config_disabled:
        return True
    env_map = os.environ if env is None else env
    raw = (env_map.get("ANDROID_BRIDGE_NO_UPDATE_CHECK") or "").strip().lower()
    return raw in ("1", "true", "yes")


def check_update(
    directory: Path,
    *,
    disabled: bool = False,
    force: bool = False,
    current: str = __version__,
    now_ms: int | None = None,
    timeout_seconds: float = 2.0,
    opener_fn: Callable[..., Any] | None = None,
    emit: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if disabled:
        return {"status": "disabled", "current_version": current}
    now = int(time.time() * 1000) if now_ms is None else now_ms
    emitter = emit or (lambda text: print(text, file=sys.stderr))
    release = None
    try:
        release = acquire_lock(directory)
        if release is None:
            return {"status": "busy", "current_version": current}
        cache_file = directory / "update_check.json"
        state = load_state(cache_file, now)
        status = "cached"
        error_msg: str | None = None
        if force or "next_check_at" not in state or now >= state["next_check_at"]:
            try:
                state["manifest"] = fetch_manifest(timeout_seconds=timeout_seconds, opener_fn=opener_fn)
                state["last_success_at"] = now
                state["next_check_at"] = now + HOUR_MS
                status = "checked"
            except (ValueError, RuntimeError) as exc:
                state["next_check_at"] = now + 5 * 60_000
                status = "unavailable"
                error_msg = str(exc)
            except Exception:
                state["next_check_at"] = now + 5 * 60_000
                status = "unavailable"
                error_msg = "Update check failed"

        tips = evaluate_notifications(state, current, now)
        for tip in tips:
            emitter(tip["text"])
            state[f"last_notified_{tip['kind']}"] = tip["id"]
            state[f"last_notified_{tip['kind']}_at"] = now
        save_state(cache_file, state)

        manifest = state.get("manifest") if isinstance(state.get("manifest"), dict) else None
        fresh = bool(
            manifest
            and _is_valid_ts(state.get("last_success_at"))
            and now - state["last_success_at"] <= 7 * DAY_MS
        )
        out: dict[str, Any] = {
            "status": status,
            "current_version": current,
            "latest_version": manifest.get("latest_version") if manifest else None,
            "release_url": manifest.get("release_url") if manifest else None,
            "update_available": bool(fresh and manifest and newer(manifest["latest_version"], current)),
            "notifications": len(tips),
        }
        if error_msg:
            out["error"] = error_msg
        return out
    except Exception:
        return {"status": "unavailable", "current_version": current, "error": "Update cache or lock is unavailable"}
    finally:
        if release is not None:
            release()
