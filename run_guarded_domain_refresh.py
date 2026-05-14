#!/usr/bin/env python3
"""Run Bolt Hole search only when Domain scrape coverage is healthy.

Safeguards:
- uses the repo virtualenv Python
- treats Domain Web as incomplete below historical coverage floor
- requires Domain gate-passed listings to have descriptions
- does not rebuild shortlist/docs until a healthy search exists
- retries with cooldown/backoff instead of sending partial output
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "bin" / "python"
RESULTS = ROOT / "data" / "listings"
LOG_DIR = ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR = RESULTS / "quarantine_incomplete"
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)


def newest_search_after(start_ts: float) -> Path | None:
    files = sorted(RESULTS.glob("search_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        if f.stat().st_mtime >= start_ts - 2:
            return f
    return files[0] if files else None


def load(path: Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


def health(data: dict, min_domain: int, min_passed: int, min_domain_desc: int) -> tuple[bool, list[str], dict]:
    report = data.get("source_report", {}) or {}
    props = data.get("properties", []) or []
    dw_source = (report.get("Domain Web") or {}).get("count") or 0
    passed = len(props)
    dw_passed = [p for p in props if p.get("source") == "domain_web"]
    dw_desc = sum(1 for p in dw_passed if p.get("description"))
    source_errors = {k: v.get("error") for k, v in report.items() if v.get("error")}

    checks = {
        "domain_web_source_count": dw_source,
        "passed_gates": passed,
        "domain_web_passed": len(dw_passed),
        "domain_web_passed_with_descriptions": dw_desc,
        "source_errors": source_errors,
    }
    problems = []
    if dw_source < min_domain:
        problems.append(f"Domain Web source count {dw_source} < floor {min_domain}")
    if passed < min_passed:
        problems.append(f"passed gates {passed} < floor {min_passed}")
    if dw_desc < min_domain_desc:
        problems.append(f"Domain Web described passed listings {dw_desc} < floor {min_domain_desc}")
    if source_errors:
        problems.append(f"source errors present: {source_errors}")
    return not problems, problems, checks


def run_once(attempt: int, args) -> tuple[bool, Path | None, dict, list[str]]:
    start = time.time()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"guarded_domain_refresh_attempt_{attempt:02d}_{stamp}.log"
    print(f"\n[{datetime.now().isoformat(timespec='seconds')}] Attempt {attempt} starting; log={log_path}", flush=True)
    env = dict(os.environ)
    env.setdefault("BOLT_SKIP_SHEET_UPSERT", "1")
    proc = subprocess.run(
        [str(PY), "search.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=args.timeout,
        env=env,
    )
    log_path.write_text(proc.stdout)
    if proc.returncode != 0:
        return False, None, {"returncode": proc.returncode, "log": str(log_path)}, [f"search.py exited {proc.returncode}"]

    result = newest_search_after(start)
    if not result:
        return False, None, {"log": str(log_path)}, ["no search_*.json produced"]
    data = load(result)
    ok, problems, checks = health(data, args.min_domain, args.min_passed, args.min_domain_desc)
    checks["result_file"] = str(result)
    checks["log"] = str(log_path)
    print("Health:", json.dumps(checks, indent=2), flush=True)
    if not ok:
        print("Incomplete:", "; ".join(problems), flush=True)
    return ok, result, checks, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-domain", type=int, default=240, help="minimum Domain Web raw source count; historical healthy run is ~270-280")
    ap.add_argument("--min-passed", type=int, default=110, help="minimum final gate-passed properties")
    ap.add_argument("--min-domain-desc", type=int, default=90, help="minimum gate-passed Domain Web listings with descriptions")
    ap.add_argument("--cooldown", type=int, default=900, help="seconds between failed attempts")
    ap.add_argument("--max-attempts", type=int, default=3, help="0 means retry indefinitely")
    ap.add_argument("--timeout", type=int, default=2700, help="per search timeout seconds")
    ap.add_argument("--shortlist", action="store_true", help="rebuild docs/index.html after healthy search")
    args = ap.parse_args()

    if not PY.exists():
        print(f"Missing virtualenv Python: {PY}", file=sys.stderr)
        return 2

    attempt = 1
    last = {}
    while args.max_attempts == 0 or attempt <= args.max_attempts:
        try:
            ok, result, checks, problems = run_once(attempt, args)
        except subprocess.TimeoutExpired:
            ok, result, checks, problems = False, None, {}, [f"search.py timed out after {args.timeout}s"]
        except Exception as exc:
            ok, result, checks, problems = False, None, {}, [f"unexpected runner error: {exc}"]
        quarantined = None
        if not ok and result and result.exists():
            quarantined_path = QUARANTINE_DIR / result.name
            try:
                result.replace(quarantined_path)
                quarantined = str(quarantined_path)
                checks["quarantined_result_file"] = quarantined
                checks.pop("result_file", None)
                result = None
            except OSError as exc:
                problems.append(f"failed to quarantine incomplete result: {exc}")
        last = {"ok": ok, "result": str(result) if result else None, "quarantined": quarantined, "checks": checks, "problems": problems}
        (LOG_DIR / "guarded_domain_refresh_status.json").write_text(json.dumps({"updated": datetime.now().isoformat(), "attempt": attempt, **last}, indent=2))
        if ok:
            print(f"COMPLETE: healthy Domain scrape in {result}", flush=True)
            if args.shortlist:
                subprocess.run([str(PY), "shortlist.py"], cwd=ROOT, check=True)
                print("Shortlist rebuilt: docs/index.html", flush=True)
            return 0
        wait = args.cooldown
        print(f"Retrying in {wait}s. Problems: {'; '.join(problems)}", flush=True)
        time.sleep(wait)
        attempt += 1
    print("FAILED: exhausted attempts", json.dumps(last, indent=2), flush=True)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
