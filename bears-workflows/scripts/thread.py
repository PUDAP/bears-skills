"""
Threaded monitors for viscosity optimization workflows.

- ``monitor_balance_threaded``  — collect mass readings from the PUDA balance
  driver at 4 Hz concurrently with an Opentrons OT-2 protocol run.
- ``monitor_protocol_status_threaded`` — poll OT-2 run status and collect
  protocol commands via HTTP; sets ``stop_event`` when the run is terminal.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover - optional runtime dependency
    requests = None

try:
    import requests
except ImportError:  # pragma: no cover - optional runtime dependency
    requests = None  # type: ignore[assignment]

try:
    import pandas as pd
except ImportError:  # pragma: no cover - optional runtime dependency
    pd = None


def _sanitize_filename(name: str) -> str:
    """Replace characters unsafe for filenames with underscores."""
    return re.sub(r'[^\w\-.]', '_', name)


def monitor_balance_threaded(
    driver: Any,
    *,
    frequency: int = 4,
    sample_name: str = "sample",
    save_csv: bool = True,
    csv_dir: str | None = None,
    stop_event: threading.Event | None = None,
    max_duration: float | None = None,
    result_dict: dict | None = None,
) -> None:
    """
    Collect balance readings in a background thread during an Opentrons run.

    Designed to run as the target of a ``threading.Thread``. Reads from the
    PUDA balance driver at *frequency* Hz until either *stop_event* is set
    (Opentrons run reached a terminal state) or *max_duration* seconds have
    elapsed — whichever comes first.

    Args:
        driver:       Initialised balance driver instance (exposes ``get_mass()``).
        frequency:    Target reading rate in Hz. Default 4.
        sample_name:  Used to build the output CSV filename.
        save_csv:     Write a CSV to *csv_dir* when monitoring ends.
        csv_dir:      Directory for the raw CSV. Defaults to
                      ``reports/viscosity_raw_data``.
        stop_event:   ``threading.Event`` set by the caller when the OT-2 run
                      reaches a terminal state. Create with
                      ``threading.Event()`` and call ``.set()`` after polling
                      confirms the run is done.
        max_duration: Hard upper bound in seconds. Stops even if *stop_event*
                      is never set. ``None`` means no limit.
        result_dict:  Dict updated in-place with results so the caller can
                      read them after ``thread.join()``. Keys written:
                      ``balance_readings``, ``csv_path``, ``balance_complete``,
                      and optionally ``balance_error``.

    Usage::

        from balance_thread import monitor_balance_threaded

        stop_event = threading.Event()
        result = {}
        t = threading.Thread(
            target=monitor_balance_threaded,
            kwargs=dict(
                driver=driver,
                sample_name="glycerol_50pct",
                stop_event=stop_event,
                max_duration=120,
                result_dict=result,
            ),
            daemon=True,
        )

        # Hard gate: confirm balance is streaming before play
        m = driver.get_mass()
        if not m.get("fresh") or m.get("age", 999) >= 5:
            raise RuntimeError("Balance not streaming fresh readings — abort before play.")

        driver.tare(wait=2.0)
        t.start()

        ot2_client.play(run_id)      # send play only after thread is started
        poll_until_terminal(run_id)  # poll OT-2 status
        stop_event.set()             # signal thread to stop
        t.join()                     # wait for final readings to flush

        balance_readings = result["balance_readings"]
        csv_path = result.get("csv_path")
    """
    if csv_dir is None:
        csv_dir = os.path.join("reports", "viscosity_raw_data")

    if result_dict is None:
        result_dict = {}

    if stop_event is None:
        stop_event = threading.Event()

    reading_interval = 1.0 / frequency
    start_time = datetime.now()
    balance_readings: list[dict] = []
    csv_path: str | None = None
    reading_count = 0
    next_reading_time = time.time()

    print(f"Starting balance monitoring at {frequency} Hz "
          f"(max {max_duration if max_duration else 'unlimited'} s) …")

    try:
        while True:
            if max_duration is not None:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= max_duration:
                    print(f"Balance monitoring: max duration ({max_duration} s) reached — "
                          f"{reading_count} readings collected.")
                    break

            if stop_event.is_set():
                print(f"Balance monitoring: stop_event set — {reading_count} readings collected.")
                break

            current_time = time.time()
            sleep_time = next_reading_time - current_time
            if sleep_time > 0:
                time.sleep(sleep_time)
            next_reading_time += reading_interval

            try:
                m = driver.get_mass()
                if m.get("fresh"):
                    mass_g = m["mass_g"]
                    elapsed_time = (datetime.now() - start_time).total_seconds()
                    balance_readings.append({
                        "time": elapsed_time,
                        "mass_g": mass_g,
                        "mass_mg": mass_g * 1000,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    })
                    reading_count += 1

                    if reading_count % (frequency * 10) == 0:
                        print(f"  Balance reading {reading_count}: "
                              f"{mass_g * 1000:.2f} mg @ {elapsed_time:.2f} s")
                else:
                    age = m.get("age", "?")
                    if reading_count % (frequency * 5) == 0:
                        print(f"  Stale balance reading skipped (age={age} s)")

            except Exception as exc:
                if reading_count % (frequency * 5) == 0:
                    print(f"  Balance read error: {exc}")
                continue

        if save_csv and balance_readings:
            try:
                os.makedirs(csv_dir, exist_ok=True)
                safe_name = _sanitize_filename(sample_name)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_filename = f"balance_{safe_name}_{ts}.csv"
                csv_path = os.path.join(csv_dir, csv_filename)

                if pd is None:
                    print("Cannot save CSV: pandas is not installed.")
                else:
                    pd.DataFrame(balance_readings).to_csv(csv_path, index=False)
                    print(f"Balance data saved: {csv_path} ({len(balance_readings)} readings)")

            except Exception as exc:
                print(f"Could not save balance CSV: {exc}")

        result_dict["balance_readings"] = balance_readings
        result_dict["csv_path"] = csv_path
        result_dict["balance_complete"] = True

    except KeyboardInterrupt:
        print("Balance monitoring interrupted by user.")
        result_dict["balance_readings"] = balance_readings
        result_dict["csv_path"] = csv_path if balance_readings else None
        result_dict["balance_complete"] = True

    except Exception as exc:
        print(f"Balance monitoring error: {exc}")
        result_dict["balance_readings"] = []
        result_dict["csv_path"] = None
        result_dict["balance_complete"] = True
        result_dict["balance_error"] = str(exc)


# ---------------------------------------------------------------------------
# Opentrons protocol monitor
# ---------------------------------------------------------------------------

def _normalize_cmd_type(ctype: str) -> str:
    """Map raw Opentrons command type strings to a canonical name."""
    cl = ctype.lower()
    if "aspirate" in cl:
        return "aspirate"
    if "dispense" in cl:
        return "dispense"
    if "pick" in cl and "tip" in cl:
        return "pickUpTip"
    if "drop" in cl and "tip" in cl:
        return "dropTip"
    if "delay" in cl or "pausing" in cl or "wait" in cl:
        return "delay"
    if "touch" in cl and "tip" in cl:
        return "touchTip"
    if "blow" in cl:
        return "blowout"
    return ctype


def _parse_cmd(cmd: dict, start_time: float) -> dict | None:
    """
    Parse a single Opentrons command dict.

    Returns a command record dict if the command is one we track, else None.
    Prints a human-readable summary of the command as a side-effect.
    """
    ctype = cmd.get("commandType", "")
    params = cmd.get("params", {})
    volume = params.get("volume")
    seconds = params.get("seconds")
    minutes = params.get("minutes")

    # Extract location
    well = params.get("wellName") or params.get("well") or params.get("wellLocation")
    labware = params.get("labwareId") or params.get("labware") or params.get("labwareLocation")
    if isinstance(well, dict):
        well = well.get("wellName") or well.get("well") or well.get("name")
    if isinstance(labware, dict):
        labware = labware.get("labwareId") or labware.get("labware") or labware.get("name")
    parts = [str(x) for x in (labware, well) if x]
    location = " / ".join(parts) if parts else "Unknown"

    is_delay_by_params = (seconds is not None or minutes is not None) and volume is None and location == "Unknown"

    cl = ctype.lower()
    tracked = (
        "aspirate" in cl or "dispense" in cl
        or ("pick" in cl and "tip" in cl)
        or ("drop" in cl and "tip" in cl)
        or "delay" in cl or "pausing" in cl or "wait" in cl
        or ctype in (
            "aspirate", "dispense", "delay", "touchTip", "blowout",
            "pickUpTip", "dropTip", "pickupTip", "pick_up_tip", "drop_tip",
            "Aspirating", "Dispensing", "Pausing", "Touching tip",
            "Blowing out", "picking up tip", "dropping tip", "wait",
        )
        or is_delay_by_params
    )
    if not tracked:
        return None

    ntype = _normalize_cmd_type(ctype)
    if is_delay_by_params:
        ntype = "delay"

    delay_duration: float | str = ""
    if ntype == "delay":
        if seconds is not None:
            delay_duration = seconds
        elif minutes is not None:
            delay_duration = minutes * 60

    if ntype in ("aspirate", "dispense"):
        vol_str = f" {volume} µL" if volume is not None else ""
        print(f"   🔄 {ntype.capitalize()}{vol_str} | Location: {location}")
    elif ntype == "delay":
        print(f"   ⏱️ Pausing{f' {delay_duration}s' if delay_duration else ''}")
    else:
        print(f"   🔧 {ntype}")

    return {
        "elapsed_time": time.time() - start_time,
        "command_type": ntype,
        "volume": volume if volume is not None else "",
        "location": location,
        "seconds": delay_duration if ntype == "delay" else (seconds if seconds is not None else ""),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }


def monitor_protocol_status_threaded(
    robot_ip: str,
    run_id: str | None = None,
    max_wait_time: int = 600,
    check_interval: int = 2,
    api_base_url: str | None = None,  # unused; kept for API compatibility
    result_dict: dict | None = None,
    stop_event: threading.Event | None = None,
    protocol_start_time: float | None = None,
) -> None:
    """
    Monitor an Opentrons protocol run in a background thread.

    Polls the robot HTTP API for run status and command list, collecting
    aspirate/dispense/delay/tip commands with timestamps.  Sets *stop_event*
    when the protocol reaches a terminal state so that a concurrent
    ``monitor_balance_threaded`` thread knows to stop.

    Args:
        robot_ip:             IP address of the OT-2 robot.
        run_id:               Specific run ID to monitor.  If *None* the most
                              recent (or currently-running) run is used.
        max_wait_time:        Seconds before giving up and timing out.
        check_interval:       Polling interval in seconds.
        api_base_url:         Ignored; present for backward compatibility.
        result_dict:          Updated in-place with ``protocol_status``,
                              ``protocol_complete``, and ``protocol_commands``.
        stop_event:           Set when the protocol finishes so paired threads
                              can exit cleanly.
        protocol_start_time:  ``time.time()`` reference for elapsed timestamps.
    """
    if result_dict is None:
        result_dict = {}
    if stop_event is None:
        stop_event = threading.Event()
    if protocol_start_time is None:
        protocol_start_time = time.time()

    base_url = f"http://{robot_ip}:31950"
    hdrs = {"opentrons-version": "*"}

    print("🤖 Starting protocol status and command monitoring...")
    print(f"   Robot IP: {robot_ip}")
    print(f"   Run ID: {run_id or 'None (will use latest run)'}")
    print("   📊 Protocol execution status updates will be shown below:\n")
    print("   ⏳ Waiting 5 seconds for protocol to initialize...")
    time.sleep(5)

    seen_ids: set[str] = set()
    commands: list[dict] = []
    last_status: str | None = None
    initial_run_id = run_id
    run_id_verified = False
    monitoring_start = time.time()
    last_warning = 0.0
    conn_errors = 0
    elapsed = 0
    protocol_complete = False

    def _finish(status: str) -> None:
        nonlocal protocol_complete
        print(f"✅ Protocol completed with status: {status}")
        result_dict.update(
            protocol_status=status,
            protocol_complete=True,
            protocol_commands=commands,
        )
        stop_event.set()
        protocol_complete = True

    def _collect_commands(rid: str) -> None:
        resp = requests.get(f"{base_url}/runs/{rid}/commands", headers=hdrs, timeout=3)
        if not resp.ok:
            return
        for cmd in resp.json().get("data", []):
            cid = cmd["id"]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            record = _parse_cmd(cmd, protocol_start_time)
            if record:
                commands.append(record)

    try:
        while elapsed < max_wait_time and not protocol_complete:
            status: str | None = None
            current_run_id = run_id

            try:
                # --- Try the specific run first ---
                if run_id:
                    resp = requests.get(f"{base_url}/runs/{run_id}", headers=hdrs, timeout=3)
                    if resp.ok:
                        data = resp.json().get("data", {})
                        status = data.get("status", "unknown")
                        current_run_id = data.get("id", run_id)
                        if not run_id_verified:
                            run_id_verified = True
                            print(f"   ✅ Verified monitoring run ID: {current_run_id}")
                        if status != last_status:
                            print(f"   📊 Protocol status: {status}")
                            last_status = status
                        _collect_commands(run_id)
                        conn_errors = 0
                    elif resp.status_code == 404:
                        conn_errors += 1  # triggers fallback below
                    else:
                        conn_errors += 1
                        if conn_errors == 1:
                            print(f"   ⚠️ Error getting run status: {resp.status_code}")

                # --- Fallback: scan all runs ---
                if not run_id or conn_errors > 0:
                    runs_resp = requests.get(f"{base_url}/runs", headers=hdrs, timeout=3)
                    if runs_resp.ok:
                        all_runs = runs_resp.json().get("data", [])
                        if not all_runs:
                            conn_errors += 1
                            if conn_errors == 1:
                                print("   ⚠️ No runs found on robot")
                        else:
                            # Prefer our initial run; then most-recent running; then latest
                            target = (
                                next((r for r in all_runs if r.get("id") == initial_run_id), None)
                                or max(
                                    (r for r in all_runs if r.get("status") == "running"),
                                    key=lambda r: r.get("createdAt", ""),
                                    default=None,
                                )
                                or all_runs[0]
                            )
                            run_id = target.get("id")
                            status = target.get("status", "unknown")
                            current_run_id = run_id
                            if not run_id_verified:
                                if not initial_run_id:
                                    initial_run_id = run_id
                                run_id_verified = True
                                print(f"   ✅ Using run ID: {run_id}")
                            conn_errors = 0
                            _collect_commands(run_id)
                            if status != last_status:
                                print(f"   📊 Protocol status: {status}")
                                last_status = status
                    else:
                        conn_errors += 1
                        if conn_errors == 1:
                            print(f"   ⚠️ Error getting runs list: {runs_resp.status_code}")

                # --- Check for terminal status ---
                if status in ("succeeded", "failed", "stopped"):
                    if run_id_verified:
                        _finish(status)
                        break
                    else:
                        now = time.time()
                        if now - last_warning >= 30:
                            print(f"   ⚠️ Run {current_run_id} is {status}; waiting to verify our run")
                            last_warning = now
                elif status == "running" and elapsed > 0 and elapsed % 10 == 0:
                    print(f"   🤖 Protocol still running… ({elapsed}s elapsed, {len(commands)} commands)")

            except requests.exceptions.Timeout:
                conn_errors += 1
                if conn_errors == 1:
                    print(f"   ⚠️ Timeout connecting to robot at {robot_ip}:31950")
            except requests.exceptions.ConnectionError as exc:
                conn_errors += 1
                if conn_errors == 1:
                    print(f"   ⚠️ Cannot connect to robot at {robot_ip}:31950\n      {exc}")
            except Exception as exc:
                conn_errors += 1
                if conn_errors <= 3:
                    print(f"   ⚠️ Protocol monitoring error: {exc}")

            time.sleep(check_interval)
            elapsed += check_interval

        if not protocol_complete:
            print("⚠️ Timeout waiting for protocol completion")
            result_dict.update(protocol_status="timeout", protocol_complete=True, protocol_commands=commands)
            stop_event.set()

    except Exception as exc:
        print(f"❌ Protocol monitoring error: {exc}")
        result_dict.update(
            protocol_status="error",
            protocol_complete=True,
            protocol_commands=commands,
            protocol_error=str(exc),
        )
        stop_event.set()


# ---------------------------------------------------------------------------
# Command-type normalisation helpers
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = {"succeeded", "failed", "stopped"}

_COMMAND_NORM: dict[str, str] = {
    "aspirate": "aspirate", "aspirating": "aspirate",
    "dispense": "dispense", "dispensing": "dispense",
    "pickuptip": "pickUpTip", "pick_up_tip": "pickUpTip", "picking up tip": "pickUpTip",
    "droptip": "dropTip", "drop_tip": "dropTip", "dropping tip": "dropTip",
    "delay": "delay", "pausing": "delay", "wait": "delay",
    "touchtip": "touchTip", "touching tip": "touchTip",
    "blowout": "blowout", "blowing out": "blowout",
}

_TRACKED = frozenset(_COMMAND_NORM.keys())


def _normalize_command(raw: str) -> str | None:
    """Return a normalised command label, or None if not a tracked type."""
    key = raw.lower().replace("-", "").replace(" ", " ").strip()
    if key in _COMMAND_NORM:
        return _COMMAND_NORM[key]
    for fragment, label in (
        ("aspirat", "aspirate"), ("dispens", "dispense"),
        ("pickup", "pickUpTip"), ("pickuptip", "pickUpTip"),
        ("droptip", "dropTip"), ("delay", "delay"),
        ("paus", "delay"), ("wait", "delay"),
        ("touchtip", "touchTip"), ("blowout", "blowout"),
    ):
        if fragment in key:
            return label
    return None


def _extract_location(params: dict) -> str:
    well = params.get("wellName") or params.get("well") or params.get("wellLocation")
    labware = params.get("labwareId") or params.get("labware") or params.get("labwareLocation")
    if isinstance(well, dict):
        well = well.get("wellName") or well.get("well") or well.get("name")
    if isinstance(labware, dict):
        labware = labware.get("labwareId") or labware.get("labware") or labware.get("name")
    parts = [str(x) for x in (labware, well) if x]
    return " / ".join(parts) if parts else "Unknown"


def _parse_command(cmd: dict, protocol_start_time: float) -> dict | None:
    """Parse a raw OT-2 command dict into a normalised record, or None if not tracked."""
    ctype = cmd.get("commandType", "")
    params = cmd.get("params", {})
    volume = params.get("volume")
    seconds = params.get("seconds")
    minutes = params.get("minutes")
    location = _extract_location(params)

    # Detect delay-by-params: has time fields, no volume, no location
    is_delay_params = (seconds is not None or minutes is not None) and volume is None and location == "Unknown"
    norm = _normalize_command(ctype) or ("delay" if is_delay_params else None)
    if norm is None:
        return None

    delay_duration: float | str = ""
    if norm == "delay":
        if seconds is not None:
            delay_duration = seconds
        elif minutes is not None:
            delay_duration = minutes * 60

    return {
        "elapsed_time": time.time() - protocol_start_time,
        "command_type": norm,
        "volume": volume if volume is not None else "",
        "location": location,
        "seconds": delay_duration if norm == "delay" else (seconds if seconds is not None else ""),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }


# ---------------------------------------------------------------------------
# Protocol status monitor
# ---------------------------------------------------------------------------

def monitor_protocol_status_threaded(
    robot_ip: str,
    run_id: str,
    *,
    stop_event: threading.Event | None = None,
    result_dict: dict | None = None,
    protocol_start_time: float | None = None,
    max_wait_time: float = 600,
    check_interval: float = 2,
) -> None:
    """
    Poll OT-2 run status and collect protocol commands in a background thread.

    Sets *stop_event* as soon as the run reaches a terminal state
    (``succeeded``, ``failed``, or ``stopped``), which signals
    ``monitor_balance_threaded`` to stop recording.

    Args:
        robot_ip:             IP address of the OT-2.
        run_id:               Run ID returned by the runs API before ``play``.
        stop_event:           Shared event — set when the run is terminal.
        result_dict:          Updated in-place with ``protocol_status``,
                              ``protocol_commands``, and ``protocol_complete``.
        protocol_start_time:  ``time.time()`` recorded just before ``play``
                              (used to timestamp each command).
        max_wait_time:        Timeout in seconds before giving up. Default 600.
        check_interval:       Seconds between status polls. Default 2.

    Result keys written to *result_dict*:
        ``protocol_status``   — final run status string.
        ``protocol_commands`` — list of normalised command dicts.
        ``protocol_complete`` — always ``True`` when the thread exits.
        ``protocol_error``    — only present on unexpected exception.

    Usage::

        from balance_thread import monitor_balance_threaded, monitor_protocol_status_threaded

        balance_stop = threading.Event()
        balance_result, protocol_result = {}, {}

        bt = threading.Thread(target=monitor_balance_threaded,
                              kwargs=dict(driver=driver, sample_name=sample_name,
                                          stop_event=balance_stop, max_duration=120,
                                          result_dict=balance_result), daemon=True)

        pt = threading.Thread(target=monitor_protocol_status_threaded,
                              kwargs=dict(robot_ip=robot_ip, run_id=run_id,
                                          stop_event=balance_stop,
                                          protocol_start_time=time.time(),
                                          result_dict=protocol_result), daemon=True)

        bt.start()
        pt.start()
        ot2_client.play(run_id)

        pt.join()
        balance_stop.set()   # safety: ensure balance thread stops if pt already set it
        bt.join()
    """
    if requests is None:
        raise RuntimeError("requests library is required for monitor_protocol_status_threaded")

    if result_dict is None:
        result_dict = {}
    if stop_event is None:
        stop_event = threading.Event()
    if protocol_start_time is None:
        protocol_start_time = time.time()

    base_url = f"http://{robot_ip}:31950"
    headers = {"opentrons-version": "*"}
    seen_ids: set[str] = set()
    commands: list[dict] = []
    last_status: str = ""
    elapsed = 0.0

    print(f"Protocol monitor started — run {run_id} on {robot_ip}")

    try:
        while elapsed < max_wait_time:
            try:
                resp = requests.get(f"{base_url}/runs/{run_id}", headers=headers, timeout=3)
                if not resp.ok:
                    print(f"  Protocol monitor: HTTP {resp.status_code} fetching run status")
                    time.sleep(check_interval)
                    elapsed += check_interval
                    continue

                run_data = resp.json().get("data", {})
                status = run_data.get("status", "unknown")

                if status != last_status:
                    print(f"  Protocol status: {status}")
                    last_status = status

                # Collect new commands
                cmd_resp = requests.get(f"{base_url}/runs/{run_id}/commands", headers=headers, timeout=3)
                if cmd_resp.ok:
                    for raw in cmd_resp.json().get("data", []):
                        cid = raw.get("id", "")
                        if cid in seen_ids:
                            continue
                        seen_ids.add(cid)
                        record = _parse_command(raw, protocol_start_time)
                        if record is None:
                            continue
                        commands.append(record)
                        norm = record["command_type"]
                        if norm in ("aspirate", "dispense"):
                            vol = record["volume"]
                            vol_str = f" {vol} uL" if vol != "" else ""
                            print(f"  {norm.capitalize()}{vol_str} @ {record['location']}")
                        elif norm == "delay":
                            print(f"  Delay {record['seconds']} s")
                        else:
                            print(f"  {norm}")

                if status in _TERMINAL_STATUSES:
                    print(f"Protocol completed: {status} ({len(commands)} commands collected)")
                    result_dict["protocol_status"] = status
                    result_dict["protocol_commands"] = commands
                    result_dict["protocol_complete"] = True
                    stop_event.set()
                    return

            except requests.exceptions.RequestException as exc:
                print(f"  Protocol monitor connection error: {exc}")

            time.sleep(check_interval)
            elapsed += check_interval

        print(f"Protocol monitor: timeout after {max_wait_time} s")
        result_dict["protocol_status"] = "timeout"
        result_dict["protocol_commands"] = commands
        result_dict["protocol_complete"] = True
        stop_event.set()

    except Exception as exc:
        print(f"Protocol monitor error: {exc}")
        result_dict["protocol_status"] = "error"
        result_dict["protocol_commands"] = commands
        result_dict["protocol_complete"] = True
        result_dict["protocol_error"] = str(exc)
        stop_event.set()
