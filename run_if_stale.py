"""Catch-up runner: run the nowcast if the current cycle's run hasn't succeeded.

Cross-platform twin of run_if_stale.ps1, for cron (Linux) and launchd (macOS).
Point a frequent cron entry at this -- every 30 minutes is fine -- instead of
scheduling the pipeline itself. It is cheap when there is nothing to do, and a
machine that was asleep at the scheduled slot catches up at its next wake.

    */30 * * * *  cd /path/to/repo && .venv/bin/python run_if_stale.py

It is anchored to the schedule, not to a staleness threshold in days. An age
threshold cannot be set correctly: below the 7-day cadence it fires before the
weekly slot and you get two runs and two emails; above it, it can never cover a
missed run, because a same-day check only ever sees a ~7.1-day-old run. Asking
"has a run succeeded since the most recent Monday 11:00?" has neither failure
mode and nothing to tune.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TS = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
IN_FLIGHT_MINUTES = 30


def last_matching(lines: list[str], needle: str) -> datetime | None:
    """Timestamp of the last log line containing needle."""
    for line in reversed(lines):
        if needle in line:
            m = TS.match(line)
            if m:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    return None


def most_recent_slot(now: datetime, dow: int, hour: int) -> datetime:
    """Latest scheduled slot at or before now. dow: Monday=0 .. Sunday=6."""
    slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    while slot.weekday() != dow or slot > now:
        slot -= timedelta(days=1)
    return slot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", type=int, default=0,
                    help="scheduled weekday, Monday=0 (default 0)")
    ap.add_argument("--hour", type=int, default=11,
                    help="scheduled hour, local time (default 11)")
    ap.add_argument("--output-dir", default=str(ROOT / "output"))
    args = ap.parse_args()

    log_path = Path(args.output_dir) / "run.log"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        lines = []

    now = datetime.now()
    due = most_recent_slot(now, args.day, args.hour)
    ok = last_matching(lines, "run OK")
    started = last_matching(lines, "nowcast run start")

    if ok is not None and ok >= due:
        print(f"up to date (last OK {ok:%Y-%m-%d %H:%M} >= due {due:%Y-%m-%d %H:%M}), skipping")
        return 0

    # The weekly job may have started seconds ago and not yet logged "run OK";
    # a second concurrent run here would double the work and the email.
    if started is not None and (now - started) < timedelta(minutes=IN_FLIGHT_MINUTES):
        print(f"a run started {started:%Y-%m-%d %H:%M} and may still be in flight, skipping")
        return 0

    print(f"due {due:%Y-%m-%d %H:%M} not yet satisfied - running nowcast now")
    return subprocess.call([sys.executable, str(ROOT / "run_nowcast.py"),
                            "--skip-if-fresh", "20"])


if __name__ == "__main__":
    sys.exit(main())
