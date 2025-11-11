import time, json, os
from pathlib import Path
from codecarbon import EmissionsTracker
import csv

RESULTS_DIR = Path('/usr/src/app/k6/results')
DURATION_SECONDS = int(os.environ.get('BASELINE_DURATION', '60'))


def main():
    tracker = EmissionsTracker(
        project_name="url-shortener-baseline",
        output_dir=str(RESULTS_DIR),
        measure_power_secs=1,
        save_to_file=True,
        gpu_ids=[],  # disable GPU probing to avoid pynvml import/warning
    )
    tracker.start()
    time.sleep(DURATION_SECONDS)
    co2e_kg = tracker.stop()
    # Prefer supported file output over private attributes for energy
    total_energy_kwh = None
    try:
        # CodeCarbon writes an emissions CSV; parse latest and read energy column
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
                # Try a few common header names used by CodeCarbon
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
        # Swallow and fall back to None if parsing fails
        total_energy_kwh = None

    data = {
        "baseline_duration_seconds": DURATION_SECONDS,
        "baseline_co2e_kg": co2e_kg,
        "baseline_energy_kwh": total_energy_kwh,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    # Add human-readable fields
    try:
        co2e_g = co2e_kg * 1000 if co2e_kg is not None else None
    except Exception:
        co2e_g = None
    try:
        energy_wh = total_energy_kwh * 1000 if total_energy_kwh is not None else None
        energy_kj = total_energy_kwh * 3_600 if total_energy_kwh is not None else None  # 1 Wh = 3.6 kJ; 1 kWh = 3600 kJ
    except Exception:
        energy_wh = None
        energy_kj = None
    data["readable"] = {
        "co2e": f"{co2e_g:.3f} g CO2e" if co2e_g is not None else None,
        "energy_wh": f"{energy_wh:.3f} Wh" if energy_wh is not None else None,
        "energy_kj": f"{energy_kj:.3f} kJ" if energy_kj is not None else None,
        "energy_kwh": f"{total_energy_kwh:.6f} kWh" if total_energy_kwh is not None else None,
        "note": "Over the measured baseline duration",
    }
    out_json = RESULTS_DIR / 'baseline_energy.json'
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with out_json.open('w') as f:
        json.dump(data, f, indent=2)
    # Console summary (human-readable)
    print(json.dumps(data, indent=2))
    hr_co2 = data["readable"]["co2e"] or "n/a"
    hr_wh = data["readable"]["energy_wh"] or "n/a"
    hr_kj = data["readable"]["energy_kj"] or "n/a"
    print(f"[baseline] Human-readable: {hr_wh} (~{hr_kj}), {hr_co2}")
    print(f"[baseline] Written {out_json}")


if __name__ == '__main__':
    main()
