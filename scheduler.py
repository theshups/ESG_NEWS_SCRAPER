from __future__ import annotations
"""
scheduler.py
────────────
Runs the ESG pipeline automatically 3x daily.
Keeps the process alive — run this in a dedicated terminal or as a background service.

Usage:
    python scheduler.py
"""

import schedule
import time
import subprocess
import sys
import os
from datetime import datetime
from src.logger import get_logger

log = get_logger("scheduler")

PYTHON_EXE  = sys.executable
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(SCRIPT_DIR, "main.py")
RUN_TIMES   = ["06:00", "12:00", "18:00"]


def run_pipeline():
    start = datetime.now()
    log.info("=" * 60)
    log.info("Scheduled pipeline run starting — " + start.strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)

    try:
        result = subprocess.run(
            [PYTHON_EXE, MAIN_SCRIPT],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour max
        )

        if result.returncode == 0:
            log.info("Pipeline completed successfully")
        else:
            log.error("Pipeline exited with code " + str(result.returncode))
            log.error("stderr: " + result.stderr[-2000:])

        elapsed = (datetime.now() - start).total_seconds()
        log.info("Run took " + str(round(elapsed)) + " seconds")

    except subprocess.TimeoutExpired:
        log.error("Pipeline timed out after 2 hours — killed")
    except Exception as e:
        log.exception("Scheduler run failed: " + str(e))

    log.info("Next run scheduled. Waiting...\n")


def main():
    log.info("ESG Updates Scheduler starting")
    log.info("Pipeline will run at: " + ", ".join(RUN_TIMES))
    log.info("Press Ctrl+C to stop\n")

    for t in RUN_TIMES:
        schedule.every().day.at(t).do(run_pipeline)

    # run once immediately on startup so DB is fresh
    log.info("Running pipeline once now on startup...")
    run_pipeline()

    while True:
        try:
            schedule.run_pending()
            time.sleep(30)
        except KeyboardInterrupt:
            log.info("Scheduler stopped by user")
            break
        except Exception as e:
            log.exception("Scheduler loop error: " + str(e))
            time.sleep(60)


if __name__ == "__main__":
    main()