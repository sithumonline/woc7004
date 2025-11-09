import time, json, os
from pathlib import Path
from codecarbon import EmissionsTracker

RESULTS_DIR = Path('/usr/src/app/k6/results')
DURATION_SECONDS = int(os.environ.get('BASELINE_DURATION', '60'))


def main():
    tracker = EmissionsTracker(
        project_name="url-shortener-baseline",
        output_dir=str(RESULTS_DIR),
        measure_power_secs=1,
        save_to_file=True,
    )
    tracker.start()
    time.sleep(DURATION_SECONDS)
    co2e_kg = tracker.stop()
    try:
        total_energy_kwh = tracker._total_energy.kwh  # type: ignore[attr-defined]
    except Exception:
        total_energy_kwh = None

    data = {
        "baseline_duration_seconds": DURATION_SECONDS,
        "baseline_co2e_kg": co2e_kg,
        "baseline_energy_kwh": total_energy_kwh,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    out_json = RESULTS_DIR / 'baseline_energy.json'
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with out_json.open('w') as f:
        json.dump(data, f, indent=2)
    print(json.dumps(data, indent=2))
    print(f"[baseline] Written {out_json}")


if __name__ == '__main__':
    main()
