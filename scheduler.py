"""
scheduler.py — runs the ESG pipeline on a daily schedule.

Usage:
    python scheduler.py          # runs immediately then every day at 06:00, 12:00, 18:00
    python scheduler.py --once   # single run and exit
"""
import argparse
import subprocess
import sys
import schedule
import time
from datetime import datetime


def run_pipeline():
    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] starting scheduled pipeline run")
    result = subprocess.run(
        [sys.executable, "main.py", "--mode", "keyword"],
        capture_output=False,
    )
    if result.returncode == 0:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] pipeline completed successfully")
    else:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] pipeline exited with code {result.returncode}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run once and exit")
    args = parser.parse_args()

    run_pipeline()  # always run immediately on start

    if args.once:
        sys.exit(0)

    # schedule three daily runs
    schedule.every().day.at("06:00").do(run_pipeline)
    schedule.every().day.at("12:00").do(run_pipeline)
    schedule.every().day.at("18:00").do(run_pipeline)

    print("scheduler running — pipeline will execute at 06:00, 12:00, 18:00 daily")
    print("press Ctrl+C to stop\n")

    while True:
        schedule.run_pending()
        time.sleep(30)
