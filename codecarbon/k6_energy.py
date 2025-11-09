import os
import json
import time
from pathlib import Path
from codecarbon import EmissionsTracker

RESULTS_DIR = Path('/usr/src/app/k6/results')
STABILITY_SECONDS = int(os.environ.get('SUMMARY_STABILITY_SECONDS', '5'))


def pick_summary_path() -> Path:
    svc = os.environ.get("K6_SERVICE", "k6")
    if svc == "k6_db":
        return RESULTS_DIR / 'db_only_summary.csv'
    elif svc == "k6_redis":
        return RESULTS_DIR / 'redis_only_summary.csv'
    else:
        return RESULTS_DIR / 'performance_summary.csv'


def wait_for_summary_ready(summary: Path) -> None:
    last_size = -1
    stable_since = None
    while True:
        if summary.exists():
            size = summary.stat().st_size
            if size == last_size:
                if stable_since is None:
                    stable_since = time.time()
                elif time.time() - stable_since >= STABILITY_SECONDS:
                    return
            else:
                stable_since = None
                last_size = size
        time.sleep(1)


def parse_total_requests(summary: Path) -> int:
    if not summary.exists():
        return 0
    total = 0
    with summary.open() as f:
        for line in f:
            if line.startswith('Total User Requests'):
                parts = line.strip().split(',')
                # Sum DB and Redis columns if present
                for p in parts[1:3]:
                    try:
                        total += int(p)
                    except Exception:
                        pass
                break
    return total


def main():
    summary_path = pick_summary_path()
    tracker = EmissionsTracker(
        project_name="url-shortener",
        output_dir=str(RESULTS_DIR),
        measure_power_secs=1,
        save_to_file=True,
    )

    tracker.start()
    start = time.time()
    print(f"[energy] Waiting for summary at {summary_path} ...")
    wait_for_summary_ready(summary_path)
    duration = time.time() - start
    co2e_kg = tracker.stop()

    try:
        total_energy_kwh = tracker._total_energy.kwh  # type: ignore[attr-defined]
    except Exception:
        total_energy_kwh = None

    total_requests = parse_total_requests(summary_path)
    per_request_kwh = (total_energy_kwh / total_requests) if (total_energy_kwh and total_requests) else None

    svc = os.environ.get("K6_SERVICE", "k6")
    out_json = RESULTS_DIR / f'energy_result_{svc}.json'
    data = {
        "duration_seconds": duration,
        "co2e_kg": co2e_kg,
        "total_energy_kwh": total_energy_kwh,
        "total_requests": total_requests,
        "energy_per_request_kwh": per_request_kwh,
        "scenario": svc,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    with out_json.open('w') as f:
        json.dump(data, f, indent=2)
    print("[energy] Summary:")
    print(json.dumps(data, indent=2))
    print(f"[energy] Written {out_json}")


if __name__ == '__main__':
    main()
