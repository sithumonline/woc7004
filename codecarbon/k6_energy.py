import os
import json
import time
from pathlib import Path
from codecarbon import EmissionsTracker
import csv

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

    # Prefer supported file output over private attributes for energy
    total_energy_kwh = None
    try:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        candidate_csvs = sorted(
            [p for p in RESULTS_DIR.glob("*.csv") if "emission" in p.name.lower()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for csv_path in candidate_csvs:
            with csv_path.open(newline="") as f:
                reader = csv.DictReader(f)
                last_row = None
                for row in reader:
                    last_row = row
                if not last_row:
                    continue
                for key in ("energy_consumed", "energy_consumed_kwh", "total_energy_kwh"):
                    if key in last_row and last_row[key]:
                        try:
                            total_energy_kwh = float(last_row[key])
                            break
                        except Exception:
                            pass
                if total_energy_kwh is not None:
                    break
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
    # Human-readable helpers
    try:
        co2e_g = (co2e_kg * 1000) if co2e_kg is not None else None
    except Exception:
        co2e_g = None
    try:
        energy_wh = (total_energy_kwh * 1000) if total_energy_kwh is not None else None
        energy_kj = (total_energy_kwh * 3600) if total_energy_kwh is not None else None
    except Exception:
        energy_wh = None
        energy_kj = None
    try:
        per_req_mwh = (per_request_kwh * 1_000_000) if per_request_kwh is not None else None  # kWh -> mWh per request
        per_req_uwh = (per_request_kwh * 1_000_000_000) if per_request_kwh is not None else None  # kWh -> µWh
    except Exception:
        per_req_mwh = None
        per_req_uwh = None
    data["readable"] = {
        "energy_wh": f"{energy_wh:.3f} Wh" if energy_wh is not None else None,
        "energy_kj": f"{energy_kj:.3f} kJ" if energy_kj is not None else None,
        "energy_kwh": f"{total_energy_kwh:.6f} kWh" if total_energy_kwh is not None else None,
        "co2e": f"{co2e_g:.3f} g CO2e" if co2e_g is not None else None,
        "per_request_mwh": f"{per_req_mwh:.3f} mWh/req" if per_req_mwh is not None else None,
        "per_request_uwh": f"{per_req_uwh:.0f} µWh/req" if per_req_uwh is not None else None,
    }
    with out_json.open('w') as f:
        json.dump(data, f, indent=2)
    print("[energy] Summary:")
    print(json.dumps(data, indent=2))
    # Console one-liner summary
    hr_total = data["readable"]["energy_wh"] or "n/a"
    hr_per_req = data["readable"]["per_request_uwh"] or data["readable"]["per_request_mwh"] or "n/a"
    hr_co2 = data["readable"]["co2e"] or "n/a"
    print(f"[energy] {svc}: {hr_total} total over {total_requests} reqs, ~{hr_per_req}, {hr_co2}")
    print(f"[energy] Written {out_json}")


if __name__ == '__main__':
    main()
