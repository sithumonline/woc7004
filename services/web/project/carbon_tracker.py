import atexit
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from codecarbon import EmissionsTracker

_DEFAULT_RESULTS_DIR = Path(os.environ.get("CODECARBON_RESULTS_DIR", "/usr/src/app/k6/results"))
_DEFAULT_MEASURE_INTERVAL = float(os.environ.get("CODECARBON_MEASURE_INTERVAL", "1"))
_DEFAULT_STABILITY_SECONDS = int(os.environ.get("SUMMARY_STABILITY_SECONDS", "5"))
_DEFAULT_PROJECT_NAME = os.environ.get("CODECARBON_PROJECT_NAME", "url-shortener")

_LOCK = threading.RLock()
_TRACKER: Optional[EmissionsTracker] = None
_STATE: Dict[str, Any] = {}
_LAST_SUMMARY: Optional[Dict[str, Any]] = None


def _control_base_url() -> Optional[str]:
    raw = os.environ.get("CODECARBON_CONTROL_URL", "http://127.0.0.1:8080/_carbon")
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    return raw.rstrip("/")


def _control_timeout() -> float:
    try:
        return float(os.environ.get("CODECARBON_CONTROL_TIMEOUT", "10"))
    except ValueError:
        return 10.0


def _http_control_enabled() -> bool:
    intent = os.environ.get("CODECARBON_HTTP_CONTROL", "").strip().lower()
    if intent in {"0", "off", "false", "no"}:
        return False
    return _control_base_url() is not None


def _maybe_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        return _env_true(value)
    return None


def _try_http_request(action: str, payload: Optional[Dict[str, Any]] = None, *, method: str = "POST") -> Optional[Dict[str, Any]]:
    if not _http_control_enabled():
        return None
    base = _control_base_url()
    if not base:
        return None
    url = f"{base}/{action.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("CODECARBON_CONTROL_TOKEN")
    if token:
        headers["X-CodeCarbon-Token"] = token
    verb = method.upper()
    data_bytes = None
    if verb == "GET":
        request_obj = urllib.request.Request(url, headers=headers, method=verb)
    else:
        body = payload or {}
        data_bytes = json.dumps(body).encode("utf-8")
        request_obj = urllib.request.Request(url, data=data_bytes, headers=headers, method=verb)
    try:
        with urllib.request.urlopen(request_obj, timeout=_control_timeout()) as response:
            raw = response.read()
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {"status": "ok", "raw": raw.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as err:
        body = err.read()
        detail: Any
        if body:
            try:
                detail = json.loads(body.decode("utf-8"))
            except Exception:
                detail = body.decode("utf-8", errors="replace")
        else:
            detail = err.reason
        return {"status": "http-error", "code": err.code, "detail": detail}
    except urllib.error.URLError:
        return None
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _env_true(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.lower() in {"1", "true", "t", "yes", "on"}


def _iso8601(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _summarize_readable(total_energy_kwh: Optional[float], co2e_kg: Optional[float], per_request_kwh: Optional[float]) -> Dict[str, Optional[str]]:
    try:
        co2e_g = co2e_kg * 1000 if co2e_kg is not None else None
    except Exception:
        co2e_g = None
    try:
        energy_wh = total_energy_kwh * 1000 if total_energy_kwh is not None else None
        energy_kj = total_energy_kwh * 3600 if total_energy_kwh is not None else None
    except Exception:
        energy_wh = None
        energy_kj = None
    try:
        per_req_mwh = per_request_kwh * 1_000_000 if per_request_kwh is not None else None
        per_req_uwh = per_request_kwh * 1_000_000_000 if per_request_kwh is not None else None
    except Exception:
        per_req_mwh = None
        per_req_uwh = None
    return {
        "energy_wh": f"{energy_wh:.3f} Wh" if energy_wh is not None else None,
        "energy_kj": f"{energy_kj:.3f} kJ" if energy_kj is not None else None,
        "energy_kwh": f"{total_energy_kwh:.6f} kWh" if total_energy_kwh is not None else None,
        "co2e": f"{co2e_g:.3f} g CO2e" if co2e_g is not None else None,
        "per_request_mwh": f"{per_req_mwh:.3f} mWh/req" if per_req_mwh is not None else None,
        "per_request_uwh": f"{per_req_uwh:.0f} µWh/req" if per_req_uwh is not None else None,
    }


def _wait_for_summary(summary_path: Path, stability_seconds: int, timeout: Optional[int]) -> None:
    start = time.time()
    last_size = -1
    stable_since: Optional[float] = None
    while True:
        if summary_path.exists():
            size = summary_path.stat().st_size
            if size == last_size:
                if stable_since is None:
                    stable_since = time.time()
                elif time.time() - stable_since >= stability_seconds:
                    return
            else:
                stable_since = None
                last_size = size
        if timeout is not None and time.time() - start > timeout:
            return
        time.sleep(1)


def _parse_total_requests(summary_path: Path) -> Optional[int]:
    if not summary_path.exists():
        return None
    total = 0
    with summary_path.open() as handle:
        for line in handle:
            if line.startswith("Total User Requests"):
                parts = line.strip().split(",")
                for value in parts[1:3]:
                    try:
                        total += int(value)
                    except Exception:
                        continue
                break
    return total if total > 0 else None


def _parse_energy_kwh(csv_path: Path) -> Optional[float]:
    if not csv_path.exists():
        return None
    try:
        import csv

        with csv_path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            last_row = None
            for row in reader:
                last_row = row
            if not last_row:
                return None
            for key in ("energy_consumed", "energy_consumed_kwh", "total_energy_kwh"):
                if key in last_row and last_row[key]:
                    try:
                        return float(last_row[key])
                    except Exception:
                        continue
    except Exception:
        return None
    return None


def tracker_running() -> bool:
    with _LOCK:
        return _TRACKER is not None


def status() -> Dict[str, Any]:
    with _LOCK:
        running = _TRACKER is not None
        state = dict(_STATE)
        last = dict(_LAST_SUMMARY) if _LAST_SUMMARY else None
    return {
        "running": running,
        "state": state,
        "last_summary": last,
    }


def start_tracking(
    *,
    scenario: Optional[str] = None,
    results_dir: Optional[str] = None,
    measure_power_secs: Optional[float] = None,
    force: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    global _TRACKER, _STATE
    with _LOCK:
        if _TRACKER and not force:
            return {"status": "already-running", "state": dict(_STATE)}
        if _TRACKER and force:
            # Stop without summary capture to avoid mixing runs.
            _stop_internal(reason="force-restart")
        scenario_name = scenario or os.environ.get("CODECARBON_SCENARIO") or os.environ.get("K6_SERVICE") or "web"
        results_path = Path(results_dir) if results_dir else _DEFAULT_RESULTS_DIR
        results_path.mkdir(parents=True, exist_ok=True)
        measure_interval = measure_power_secs if measure_power_secs is not None else _DEFAULT_MEASURE_INTERVAL
        suffix = f"{scenario_name.replace(' ', '_')}_{os.getpid()}_{int(time.time())}"
        output_file = f"emissions_{suffix}.csv"
        tracking_mode = os.environ.get("CODECARBON_TRACKING_MODE")
        if not tracking_mode:
            tracking_mode = "machine" if not _http_control_enabled() else "process"
        tracker = EmissionsTracker(
            project_name=f"{_DEFAULT_PROJECT_NAME}-{scenario_name}",
            output_dir=str(results_path),
            output_file=output_file,
            measure_power_secs=measure_interval,
            save_to_file=True,
            gpu_ids=[],
            tracking_mode=tracking_mode,
        )
        tracker.start()
        _TRACKER = tracker
        _STATE = {
            "scenario": scenario_name,
            "results_dir": str(results_path),
            "output_file": output_file,
            "started_at": time.time(),
            "measure_power_secs": measure_interval,
            "metadata": metadata or {},
        }
        return {"status": "started", "state": dict(_STATE)}


def stop_tracking(
    *,
    summary_csv: Optional[str] = None,
    stability_seconds: Optional[int] = None,
    write_json: Optional[str] = None,
    wait_timeout: Optional[int] = None,
    reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    summary = _stop_internal(
        summary_csv=summary_csv,
        stability_seconds=stability_seconds,
        write_json=write_json,
        wait_timeout=wait_timeout,
        reason=reason or "manual-stop",
    )
    return summary


def _stop_internal(
    summary_csv: Optional[str] = None,
    stability_seconds: Optional[int] = None,
    write_json: Optional[str] = None,
    wait_timeout: Optional[int] = None,
    reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    global _TRACKER, _STATE, _LAST_SUMMARY
    with _LOCK:
        tracker = _TRACKER
        if tracker is None:
            return None
        state = dict(_STATE)
        _TRACKER = None
        _STATE = {}
    co2e_kg = tracker.stop()
    end_ts = time.time()
    start_ts = state.get("started_at", end_ts)
    duration = end_ts - start_ts
    results_dir = Path(state.get("results_dir", str(_DEFAULT_RESULTS_DIR)))
    csv_name = state.get("output_file")
    emissions_csv = results_dir / csv_name if csv_name else None
    total_energy_kwh = _parse_energy_kwh(emissions_csv) if emissions_csv else None
    summary_path = Path(summary_csv) if summary_csv else None
    stability = stability_seconds if stability_seconds is not None else _DEFAULT_STABILITY_SECONDS
    if summary_path:
        _wait_for_summary(summary_path, stability, wait_timeout)
        total_requests = _parse_total_requests(summary_path)
    else:
        total_requests = None
    per_request_kwh = (
        (total_energy_kwh / total_requests) if (total_energy_kwh is not None and total_requests) else None
    )
    summary = {
        "scenario": state.get("scenario"),
        "co2e_kg": co2e_kg,
        "total_energy_kwh": total_energy_kwh,
        "duration_seconds": duration,
        "started_at": _iso8601(start_ts),
        "ended_at": _iso8601(end_ts),
        "timestamp": _iso8601(end_ts),
        "total_requests": total_requests,
        "energy_per_request_kwh": per_request_kwh,
        "measure_power_secs": state.get("measure_power_secs"),
        "emissions_csv": str(emissions_csv) if emissions_csv else None,
        "summary_csv": str(summary_path) if summary_path else None,
        "reason": reason,
    }
    summary["readable"] = _summarize_readable(total_energy_kwh, co2e_kg, per_request_kwh)
    if write_json:
        out_path = Path(write_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as handle:
            json.dump(summary, handle, indent=2)
    with _LOCK:
        _LAST_SUMMARY = dict(summary)
    return summary


def init_app(app) -> None:
    if getattr(app, "_carbon_tracker_init", False):
        return
    app._carbon_tracker_init = True

    auto_enabled = _env_true(os.environ.get("CODECARBON_ENABLED"))
    auto_scenario = os.environ.get("CODECARBON_SCENARIO") or os.environ.get("K6_SERVICE")
    auto_results = os.environ.get("CODECARBON_RESULTS_DIR")
    auto_interval = os.environ.get("CODECARBON_MEASURE_INTERVAL")

    auto_started = False

    def _ensure_auto_start() -> None:
        nonlocal auto_started
        if auto_started or not auto_enabled:
            return
        try:
            start_tracking(
                scenario=auto_scenario,
                results_dir=auto_results,
                measure_power_secs=float(auto_interval) if auto_interval else None,
                force=False,
            )
            auto_started = True
        except Exception as exc:
            app.logger.exception("Failed to auto-start CodeCarbon tracker: %s", exc)

    if hasattr(app, "before_serving"):
        @app.before_serving
        def _carbon_before_serving() -> None:
            _ensure_auto_start()
    else:
        @app.before_request
        def _carbon_before_request() -> None:
            _ensure_auto_start()

    atexit.register(lambda: stop_tracking(reason="atexit"))

    from flask import Blueprint, jsonify, request

    if not getattr(app, "_carbon_tracker_http_registered", False):
        control = Blueprint("carbon_http_control", __name__)

        def _http_authorized() -> Optional[Any]:
            token = os.environ.get("CODECARBON_CONTROL_TOKEN")
            if not token:
                return None
            provided = request.headers.get("X-CodeCarbon-Token")
            if provided != token:
                return jsonify({"error": "unauthorized"}), 403
            return None

        @control.post("/_carbon/start")
        def http_start() -> Any:
            auth_error = _http_authorized()
            if auth_error:
                return auth_error
            data = request.get_json(silent=True) or {}
            measure_raw = data.get("measure_interval")
            measure_interval: Optional[float] = None
            if measure_raw is not None:
                try:
                    measure_interval = float(measure_raw)
                except (TypeError, ValueError):
                    measure_interval = None
            force_raw = data.get("force")
            force_flag = _maybe_bool(force_raw)
            if force_flag is not None:
                force_value = force_flag
            elif isinstance(force_raw, (int, float)):
                force_value = bool(force_raw)
            else:
                force_value = False
            info = start_tracking(
                scenario=data.get("scenario"),
                results_dir=data.get("results_dir"),
                measure_power_secs=measure_interval,
                force=force_value,
                metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
            )
            info.setdefault("control", "http")
            return jsonify(info)

        @control.post("/_carbon/stop")
        def http_stop() -> Any:
            auth_error = _http_authorized()
            if auth_error:
                return auth_error
            data = request.get_json(silent=True) or {}
            stability_raw = data.get("stability_seconds")
            stability: Optional[int] = None
            if stability_raw is not None:
                try:
                    stability = int(stability_raw)
                except (TypeError, ValueError):
                    stability = None
            wait_raw = data.get("wait_timeout")
            wait_timeout: Optional[int] = None
            if wait_raw is not None:
                try:
                    wait_timeout = int(wait_raw)
                except (TypeError, ValueError):
                    wait_timeout = None
            summary = stop_tracking(
                summary_csv=data.get("summary_csv"),
                stability_seconds=stability,
                write_json=data.get("write_json"),
                wait_timeout=wait_timeout,
                reason=data.get("reason"),
            )
            if summary is None:
                return jsonify({"status": "not-running", "control": "http"})
            summary.setdefault("control", "http")
            return jsonify(summary)

        @control.get("/_carbon/status")
        def http_status() -> Any:
            auth_error = _http_authorized()
            if auth_error:
                return auth_error
            info = status()
            info.setdefault("control", "http")
            return jsonify(info)

        app.register_blueprint(control)
        app._carbon_tracker_http_registered = True

    import click
    from flask.cli import AppGroup, with_appcontext

    carbon = AppGroup("carbon", help="Manage CodeCarbon energy tracking.")

    @carbon.command("start")
    @click.option("--scenario", type=str, default=None, help="Scenario label for this run.")
    @click.option(
        "--results-dir",
        type=click.Path(file_okay=False, dir_okay=True, path_type=str),
        default=None,
        help="Directory for emissions CSV/JSON outputs.",
    )
    @click.option("--measure-interval", type=float, default=None, help="Sampling interval in seconds.")
    @click.option("--force/--no-force", default=False, help="Restart tracker if it is already running.")
    @with_appcontext
    def carbon_start(scenario, results_dir, measure_interval, force) -> None:
        payload = {
            "scenario": scenario,
            "results_dir": results_dir,
            "measure_interval": measure_interval,
            "force": force,
        }
        response = _try_http_request("start", payload)
        if response is not None:
            click.echo(json.dumps(response, indent=2))
            return
        info = start_tracking(
            scenario=scenario,
            results_dir=results_dir,
            measure_power_secs=measure_interval,
            force=force,
        )
        info.setdefault("control", "local")
        click.echo(json.dumps(info, indent=2))

    @carbon.command("stop")
    @click.option(
        "--summary-csv",
        type=click.Path(dir_okay=False, path_type=str),
        default=None,
        help="Optional k6 summary CSV to derive request counts.",
    )
    @click.option(
        "--write-json",
        type=click.Path(dir_okay=False, path_type=str),
        default=None,
        help="Where to write the energy summary JSON.",
    )
    @click.option("--stability-seconds", type=int, default=None, help="Stable size window for summary CSV.")
    @click.option("--wait-timeout", type=int, default=None, help="Optional timeout while waiting for summary CSV.")
    @click.option("--reason", type=str, default="manual-stop", help="Reason label stored in the summary.")
    @with_appcontext
    def carbon_stop(summary_csv, write_json, stability_seconds, wait_timeout, reason) -> None:
        payload = {
            "summary_csv": summary_csv,
            "write_json": write_json,
            "stability_seconds": stability_seconds,
            "wait_timeout": wait_timeout,
            "reason": reason,
        }
        response = _try_http_request("stop", payload)
        if response is not None:
            click.echo(json.dumps(response, indent=2))
            return
        summary = stop_tracking(
            summary_csv=summary_csv,
            stability_seconds=stability_seconds,
            write_json=write_json,
            wait_timeout=wait_timeout,
            reason=reason,
        )
        if summary is None:
            click.echo(json.dumps({"status": "not-running", "control": "local"}, indent=2))
            return
        summary.setdefault("control", "local")
        click.echo(json.dumps(summary, indent=2))

    @carbon.command("status")
    @with_appcontext
    def carbon_status() -> None:
        response = _try_http_request("status", method="GET")
        if response is not None:
            click.echo(json.dumps(response, indent=2))
            return
        info = status()
        info.setdefault("control", "local")
        click.echo(json.dumps(info, indent=2))

    app.cli.add_command(carbon)
