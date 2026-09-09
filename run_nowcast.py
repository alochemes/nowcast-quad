"""Entry point for one autonomous nowcast run.

Usage: .venv\\Scripts\\python.exe run_nowcast.py [--output-dir DIR]
Writes quad_map.png, report.html, nowcast.csv and run.log to the output dir.
Exit code 0 on success, 1 on failure (for Task Scheduler alerting).
"""

import argparse
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from nowcast import notify_remote, pipeline, quads

# Windows consoles default to cp1252, which cannot print arrows etc.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NOTIFY_PS1 = Path(__file__).resolve().parent / "notify.ps1"


def last_success(log_path: Path) -> datetime | None:
    """Timestamp of the most recent 'run OK' line in the log, if any."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-400:]):
        if line.endswith("run OK"):
            try:
                return datetime.strptime(line[1:20], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    return None


def toast(title: str, body: str) -> None:
    """Best-effort Windows toast; never fails the run."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(NOTIFY_PS1), "-Title", title, "-Body", body],
            capture_output=True, timeout=30)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--skip-if-fresh", type=float, default=0.0, metavar="HOURS",
                    help="exit without running (and without notifying) if the "
                         "last successful run is younger than HOURS. Both "
                         "scheduled tasks pass this so a weekly run and a "
                         "logon catch-up cannot both fire on the same day.")
    ap.add_argument("--force", action="store_true",
                    help="run even if --skip-if-fresh would skip")
    args = ap.parse_args()
    out_dir = Path(args.output_dir) if args.output_dir else pipeline.OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)
    log_path = out_dir / "run.log"

    with open(log_path, "a", encoding="utf-8") as f:
        def log(msg):
            line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
            print(line)
            f.write(line + "\n")

        log("========== nowcast run start ==========")
        prev_ok = last_success(log_path)
        if args.skip_if_fresh > 0 and not args.force and prev_ok is not None:
            age_h = (datetime.now() - prev_ok).total_seconds() / 3600
            if age_h < args.skip_if_fresh:
                log(f"skipped: last success {prev_ok:%Y-%m-%d %H:%M} was "
                    f"{age_h:.1f}h ago (< --skip-if-fresh "
                    f"{args.skip_if_fresh:g}h); nothing run, nothing sent")
                return 0
        try:
            res = pipeline.run(output_dir=out_dir, log=log)
            log("run OK")
            t = res["table"]
            # the calendar quarter we are living in, not the first quarter BEA
            # has yet to publish (pipeline.run decides; see its comment)
            p = res.get("current_q")
            cur = t.loc[t.index == p] if p is not None else t[t["is_estimate"]]
            payload = {"status": "OK"}
            if not cur.empty:
                p, r = cur.index[0], cur.iloc[0]
                payload = {"status": "OK",
                           "quarter": quads.quarter_label(p, bool(r["is_estimate"])),
                           "quad": int(r["quad"]), "quad_name": r["quad_name"],
                           "gdp_yoy": round(float(r["gdp_yoy"]), 2),
                           "cpi_yoy": round(float(r["cpi_yoy"]), 2),
                           "note": res["meta"].get("GDP ensemble (approved 2026-07-14)", "")}
                payload = notify_remote.enrich_payload(payload, res, out_dir,
                                                       log=log)
                toast("Nowcast Quad: run OK",
                      f"{payload['quarter']}: Quad {payload['quad']} "
                      f"{payload['quad_name']} — GDP {payload['gdp_yoy']}%, "
                      f"CPI {payload['cpi_yoy']}%")
            notify_remote.push_status(payload, log=log)
            return 0
        except Exception:
            log("run FAILED:\n" + traceback.format_exc())
            toast("Nowcast Quad: run FAILED", "See output\\run.log for the traceback.")
            notify_remote.push_status(
                {"status": "FAILED", "note": traceback.format_exc()[-500:]}, log=log)
            return 1


if __name__ == "__main__":
    sys.exit(main())
