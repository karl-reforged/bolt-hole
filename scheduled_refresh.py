#!/usr/bin/env python3
"""Run, verify, and publish the weekly Bolt Hole refresh.

This is the launchd entry point. It keeps publication fail-closed: a dirty
generated shortlist is never overwritten or committed, and GitHub is updated
only after the guarded refresh records a healthy result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REFRESH = ROOT / "refresh.sh"
PUBLIC_SITE_FILES = (
    Path("docs/index.html"),
    Path("docs/site-state.json"),
    Path("docs/site-state.js"),
    Path("docs/bolt-hole-overview.html"),
    Path("docs/system-map.html"),
    Path("docs/dashboard.html"),
    Path("docs/top10.html"),
)
GUARDED_STATUS = ROOT / "data" / "logs" / "guarded_domain_refresh_status.json"
SCHEDULED_STATUS = ROOT / "data" / "logs" / "scheduled_refresh_status.json"


class ScheduledRefreshError(RuntimeError):
    pass


def _run(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def _site_is_dirty() -> bool:
    result = _run(
        [
            "git", "status", "--porcelain", "--untracked-files=normal", "--",
            *(str(path) for path in PUBLIC_SITE_FILES),
        ],
        capture_output=True,
    )
    return bool(result.stdout.strip())


def _verify_guarded_result() -> dict:
    try:
        status = json.loads(GUARDED_STATUS.read_text())
    except (OSError, ValueError) as exc:
        raise ScheduledRefreshError(f"guarded refresh status is unavailable: {exc}") from exc
    if status.get("ok") is not True:
        problems = "; ".join(status.get("problems") or []) or "unknown failure"
        raise ScheduledRefreshError(f"guarded refresh was not healthy: {problems}")
    return status


def _verify_site_bundle() -> None:
    _run([sys.executable, "site_state.py", "--verify"])


def _publish_site() -> str:
    branch = _run(["git", "branch", "--show-current"], capture_output=True).stdout.strip()
    publish_branch = os.getenv("BOLT_PUBLISH_BRANCH", "main")
    if branch != publish_branch:
        raise ScheduledRefreshError(
            f"refusing to publish from branch {branch!r}; expected {publish_branch!r}"
        )

    unchanged = subprocess.run(
        ["git", "diff", "--quiet", "--", *(str(path) for path in PUBLIC_SITE_FILES)],
        cwd=ROOT,
    ).returncode == 0
    if unchanged:
        # A previous attempt may have committed successfully but failed while
        # pushing. Always push so a retry repairs that partial publication.
        _run(["git", "push", "origin", f"HEAD:{publish_branch}"])
        return "unchanged"

    _run(["git", "add", "--", *(str(path) for path in PUBLIC_SITE_FILES)])
    message = f"Refresh coherent Bolt Hole site — {datetime.now().date().isoformat()}"
    _run([
        "git", "commit", "--only", *(str(path) for path in PUBLIC_SITE_FILES),
        "-m", message,
    ])
    _run(["git", "push", "origin", f"HEAD:{publish_branch}"])
    return "pushed"


def _write_status(ok: bool, **details) -> None:
    SCHEDULED_STATUS.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated": datetime.now().isoformat(), "ok": ok, **details}
    SCHEDULED_STATUS.write_text(json.dumps(payload, indent=2))


def _notify_failure(message: str) -> None:
    if sys.platform != "darwin":
        return
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')[:240]
    script = f'display notification "{safe_message}" with title "Bolt Hole refresh failed"'
    subprocess.run(["osascript", "-e", script], cwd=ROOT, check=False)


def main() -> int:
    try:
        if _site_is_dirty():
            raise ScheduledRefreshError(
                "public site files already have uncommitted changes; refusing to overwrite them"
            )
        _run([str(REFRESH)])
        guarded = _verify_guarded_result()
        _verify_site_bundle()
        publication = _publish_site()
        _write_status(
            True,
            publication=publication,
            result=guarded.get("result"),
            checks=guarded.get("checks", {}),
        )
        print(f"Scheduled refresh complete; publication={publication}", flush=True)
        return 0
    except (OSError, subprocess.CalledProcessError, ScheduledRefreshError) as exc:
        message = str(exc)
        _write_status(False, error=message)
        _notify_failure(message)
        print(f"Scheduled refresh failed: {message}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
