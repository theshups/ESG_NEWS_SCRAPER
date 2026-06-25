import argparse
import subprocess
import sys
import time
from datetime import datetime, time as dt_time


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

    schedule_times = [dt_time(6, 0), dt_time(12, 0), dt_time(18, 0)]
    last_run_time = None

    print("scheduler running pipeline will execute at 06:00, 12:00, 18:00 daily")
    print("press Ctrl+C to stop\n")

    while True:
        now = datetime.now()
        current_time = now.time().replace(second=0, microsecond=0)

        if current_time in schedule_times and last_run_time != current_time:
            run_pipeline()
            last_run_time = current_time
        elif current_time not in schedule_times:
            last_run_time = None

        time.sleep(30)
