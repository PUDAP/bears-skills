"""
Balance data processing utilities for viscosity optimization workflows.

The raw data stream stores balance readings in mg and protocol command timing.
This module can merge protocol commands onto balance readings, process the
aspiration-to-delay window, generate a normalized mass-change CSV, and compute
summary metrics for the optimizer.
"""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional runtime dependency
    np = None

try:
    import pandas as pd
except ImportError:  # pragma: no cover - optional runtime dependency
    pd = None

try:
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover - optional runtime dependency
    plt = None


IMPORTANT_COMMANDS = {"aspirate", "dispense"}
DEFAULT_COMMAND_TOLERANCE_SECONDS = 1.5
DEFAULT_OUTLIER_THRESHOLD_MG = 10000.0
DEFAULT_PROCESSING_WINDOW_SECONDS = 30.0


def _viscosity_data_root() -> Path:
    return Path(
        os.environ.get(
            "VISCOSITY_DATA_DIR",
            os.path.join("reports", "SynologyDrive", "viscosity_optimization"),
        )
    )


def _require_pandas() -> bool:
    if pd is None:
        print("Cannot process balance data: pandas is not installed")
        return False
    return True


def _require_numpy() -> bool:
    if np is None:
        print("Cannot process balance data: numpy is not installed")
        return False
    return True


def _reading_time(reading: dict[str, Any]) -> float:
    return float(reading.get("time", reading.get("timestamp", 0.0)))


def _ensure_mass_mg_columns(df: Any) -> Any:
    """Ensure a dataframe has a numeric mass_mg column."""
    if "mass_mg" in df.columns:
        df["mass_mg"] = pd.to_numeric(df["mass_mg"], errors="coerce")
        return df
    if "mass_g" in df.columns:
        df["mass_mg"] = pd.to_numeric(df["mass_g"], errors="coerce") * 1000.0
        return df
    raise ValueError("Expected a 'mass_mg' column, or 'mass_g' to convert from grams.")


def _set_command_row(df: Any, row_idx: int, command: dict[str, Any]) -> None:
    df.at[row_idx, "command_type"] = command.get("command_type", "")
    df.at[row_idx, "command_volume_uL"] = command.get("volume", "")
    df.at[row_idx, "command_location"] = command.get("location", "")
    df.at[row_idx, "command_duration_sec"] = command.get("seconds", "")


def _set_command_reading(reading: dict[str, Any], command: dict[str, Any]) -> None:
    reading["command_type"] = command.get("command_type", "")
    reading["command_volume_uL"] = command.get("volume", "")
    reading["command_location"] = command.get("location", "")
    reading["command_duration_sec"] = command.get("seconds", "")


def _command_window(
    command: dict[str, Any],
    *,
    time_offset: float,
    next_command_time: float | None,
) -> tuple[float, float]:
    command_type = command.get("command_type", "")
    start = float(command.get("elapsed_time", 0.0)) + time_offset
    if command_type == "delay":
        try:
            duration = float(command.get("seconds") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        end = start + duration if duration > 0 else (next_command_time or start + 1.0)
    else:
        end = next_command_time if next_command_time is not None else start + 1.0
    return start, end


def _active_command_at_time(
    reading_time: float,
    protocol_commands: list[dict[str, Any]],
    *,
    time_offset: float,
) -> dict[str, Any] | None:
    sorted_commands = sorted(
        protocol_commands,
        key=lambda command: float(command.get("elapsed_time", 0.0)),
    )
    active: dict[str, Any] | None = None
    for idx, command in enumerate(sorted_commands):
        command_type = command.get("command_type", "")
        if not command_type:
            continue
        next_time = None
        if idx + 1 < len(sorted_commands):
            next_time = (
                float(sorted_commands[idx + 1].get("elapsed_time", 0.0)) + time_offset
            )
        start, end = _command_window(
            command,
            time_offset=time_offset,
            next_command_time=next_time,
        )
        if start <= reading_time < end:
            active = command
    return active


def _status_at_time(
    reading_time: float,
    status_history: list[dict[str, Any]],
    *,
    fallback_status: str = "",
) -> str:
    status = fallback_status
    for snapshot in sorted(
        status_history,
        key=lambda item: float(item.get("elapsed_time", 0.0)),
    ):
        elapsed = float(snapshot.get("elapsed_time", 0.0))
        snapshot_status = snapshot.get("status", "")
        if elapsed <= reading_time and snapshot_status:
            status = snapshot_status
    return status


def _merge_commands_onto_readings(
    balance_readings: list[dict[str, Any]],
    protocol_commands: list[dict[str, Any]],
    *,
    balance_start_time: float,
    protocol_start_time: float,
) -> tuple[list[dict[str, Any]], int, int]:
    """Label balance readings with matched protocol command metadata."""
    annotated = [dict(reading) for reading in balance_readings]
    for reading in annotated:
        reading.setdefault("command_type", "")
        reading.setdefault("command_volume_uL", "")
        reading.setdefault("command_location", "")
        reading.setdefault("command_duration_sec", "")

    time_offset = float(protocol_start_time) - float(balance_start_time)
    matched_commands: set[int] = set()
    sorted_commands = sorted(
        protocol_commands,
        key=lambda command: float(command.get("elapsed_time", 0.0)),
    )

    for command in sorted_commands:
        command_type = command.get("command_type", "")
        if not command_type:
            continue

        command_time = float(command.get("elapsed_time", 0.0)) + time_offset

        if command_type == "delay":
            try:
                delay_duration = float(command.get("seconds") or 0.0)
            except (TypeError, ValueError):
                delay_duration = 0.0

            delay_start = command_time
            delay_end = delay_start + delay_duration

            for idx, reading in enumerate(annotated):
                reading_time = _reading_time(reading)
                if delay_start <= reading_time <= delay_end:
                    current_command = reading.get("command_type", "")
                    if current_command in ("", "delay"):
                        reading["command_type"] = command_type
                        reading["command_duration_sec"] = (
                            delay_duration if delay_duration > 0 else ""
                        )
                        matched_commands.add(id(command))

            if id(command) not in matched_commands and annotated:
                closest_idx = _closest_reading_index(
                    annotated,
                    command_time,
                    tolerance_seconds=DEFAULT_COMMAND_TOLERANCE_SECONDS,
                )
                if closest_idx is not None:
                    current_command = annotated[closest_idx].get("command_type", "")
                    if current_command in ("", "delay"):
                        annotated[closest_idx]["command_type"] = command_type
                        annotated[closest_idx]["command_duration_sec"] = (
                            delay_duration if delay_duration > 0 else ""
                        )
                        matched_commands.add(id(command))
            continue

        closest_idx = _closest_reading_index(
            annotated,
            command_time,
            tolerance_seconds=DEFAULT_COMMAND_TOLERANCE_SECONDS,
        )

        if closest_idx is None and command_type in IMPORTANT_COMMANDS and annotated:
            closest_idx = min(
                range(len(annotated)),
                key=lambda idx: abs(_reading_time(annotated[idx]) - command_time),
            )

        if closest_idx is None:
            continue

        current_command_type = annotated[closest_idx].get("command_type", "")
        if current_command_type == "" or (
            command_type in IMPORTANT_COMMANDS and current_command_type == "delay"
        ):
            _set_command_reading(annotated[closest_idx], command)
            matched_commands.add(id(command))

    return annotated, len(matched_commands), len(protocol_commands)


def annotate_balance_readings_with_protocol(
    balance_readings: list[dict[str, Any]],
    protocol_commands: list[dict[str, Any]],
    *,
    protocol_status: str = "",
    status_history: list[dict[str, Any]] | None = None,
    balance_start_time: float,
    protocol_start_time: float,
) -> list[dict[str, Any]]:
    """Combine balance readings with OT-2 status and active command labels."""
    merged, matched_count, total_commands = _merge_commands_onto_readings(
        balance_readings,
        protocol_commands,
        balance_start_time=balance_start_time,
        protocol_start_time=protocol_start_time,
    )
    time_offset = float(protocol_start_time) - float(balance_start_time)
    history = status_history or []

    for reading in merged:
        reading_time = _reading_time(reading)
        reading["ot2_status"] = _status_at_time(
            reading_time,
            history,
            fallback_status=protocol_status,
        )
        active_command = _active_command_at_time(
            reading_time,
            protocol_commands,
            time_offset=time_offset,
        )
        reading["ot2_command"] = (
            active_command.get("command_type", "") if active_command else ""
        )

    print(
        "Annotated balance readings with OT-2 status/commands — "
        f"{matched_count}/{total_commands} command labels matched"
    )
    if matched_count < total_commands:
        print(f"{total_commands - matched_count} commands could not be matched")
    return merged


def combine_balance_and_protocol_results(
    balance_result: dict[str, Any],
    protocol_result: dict[str, Any],
    *,
    balance_start_time: float | None = None,
    protocol_start_time: float | None = None,
    save_csv: bool = True,
) -> dict[str, Any]:
    """
    Merge OT-2 protocol status/commands into balance readings and CSV.

    Updates *balance_result* in place with combined ``balance_readings`` and
    rewrites ``csv_path`` when present.
    """
    balance_readings = balance_result.get("balance_readings", [])
    protocol_commands = protocol_result.get("protocol_commands", [])
    protocol_status = protocol_result.get("protocol_status", "")
    status_history = protocol_result.get("status_history", [])

    if balance_start_time is None:
        balance_start_time = float(balance_result.get("balance_start_time", 0.0))
    if protocol_start_time is None:
        protocol_start_time = float(protocol_result.get("protocol_start_time", 0.0))

    if not balance_readings:
        print("No balance readings to combine with protocol data.")
        return {
            "balance_readings": [],
            "csv_path": balance_result.get("csv_path"),
            "protocol_status": protocol_status,
            "protocol_commands": protocol_commands,
            "combined": False,
        }

    combined_readings = annotate_balance_readings_with_protocol(
        balance_readings,
        protocol_commands,
        protocol_status=protocol_status,
        status_history=status_history,
        balance_start_time=balance_start_time,
        protocol_start_time=protocol_start_time,
    )

    balance_result["balance_readings"] = combined_readings
    balance_result["combined_with_protocol"] = True

    csv_path = balance_result.get("csv_path")
    if save_csv and csv_path and _require_pandas():
        try:
            pd.DataFrame(combined_readings).to_csv(csv_path, index=False)
            print(f"Combined balance/protocol CSV saved: {csv_path}")
        except Exception as exc:
            print(f"Could not save combined CSV: {exc}")

    return {
        "balance_readings": combined_readings,
        "csv_path": csv_path,
        "protocol_status": protocol_status,
        "protocol_commands": protocol_commands,
        "combined": True,
    }


def merge_protocol_commands_with_balance_readings(
    csv_path: str | Path,
    balance_readings: list[dict[str, Any]],
    protocol_commands: list[dict[str, Any]],
    balance_start_time: float,
    protocol_start_time: float,
    *,
    protocol_status: str = "",
    status_history: list[dict[str, Any]] | None = None,
):
    """
    Merge protocol commands with balance readings in an existing CSV file.

    Commands are matched to balance readings by elapsed time. Delay commands mark
    every reading within the delay window when possible. Aspirate and dispense
    commands can overwrite delay labels because they are the key commands for
    viscosity analysis.

    Also updates *balance_readings* in place with ``ot2_status`` and
    ``ot2_command`` columns when protocol status metadata is supplied.
    """
    balance_result = {
        "balance_readings": balance_readings,
        "csv_path": str(csv_path),
        "balance_start_time": balance_start_time,
    }
    protocol_result = {
        "protocol_commands": protocol_commands,
        "protocol_status": protocol_status,
        "status_history": status_history or [],
        "protocol_start_time": protocol_start_time,
    }
    combined = combine_balance_and_protocol_results(
        balance_result,
        protocol_result,
        balance_start_time=balance_start_time,
        protocol_start_time=protocol_start_time,
        save_csv=True,
    )
    if not _require_pandas():
        return None
    if not combined.get("combined"):
        return None
    try:
        return pd.read_csv(csv_path)
    except Exception as exc:  # pragma: no cover - preserves diagnostic behavior
        print(f"Error reading merged CSV: {exc}")
        return None


def _closest_reading_index(
    balance_readings: list[dict[str, Any]],
    target_time: float,
    *,
    tolerance_seconds: float,
) -> int | None:
    closest_idx: int | None = None
    min_diff = float("inf")

    for idx, reading in enumerate(balance_readings):
        diff = abs(_reading_time(reading) - target_time)
        if diff < min_diff and diff <= tolerance_seconds:
            min_diff = diff
            closest_idx = idx

    return closest_idx


def analyze_viscosity_data(
    csv_file_path: str | Path,
    output_dir: str | Path,
    *,
    outlier_threshold_mg: float = DEFAULT_OUTLIER_THRESHOLD_MG,
    window_seconds: float = DEFAULT_PROCESSING_WINDOW_SECONDS,
):
    """
    Process one raw viscosity CSV into normalized time and mass-change data.

    Processing steps:
    1. Strip apostrophes from serial output.
    2. Convert mass_g to mass_mg if needed.
    3. Remove rows below outlier_threshold_mg.
    4. Select data from the first aspirate command to the last delay after it.
    5. Average delay-period readings per second.
    6. Normalize time and mass to start at 0.
    7. Keep 0-window_seconds and extend the final value if the run is shorter.
    8. Save the processed CSV with the same filename in output_dir.
    """
    if not (_require_pandas() and _require_numpy()):
        return None

    csv_file_path = Path(csv_file_path)
    print(f"Processing: {csv_file_path}")

    try:
        content = csv_file_path.read_text(encoding="utf-8").replace("'", "")
        df = pd.read_csv(StringIO(content))
        df = _ensure_mass_mg_columns(df)
    except Exception as exc:
        print(f"Error reading or parsing CSV file: {exc}")
        return None

    if "command_type" not in df.columns:
        print(f"Error: 'command_type' column not found. Available columns: {list(df.columns)}")
        return None
    if "time" not in df.columns:
        print(f"Error: 'time' column not found. Available columns: {list(df.columns)}")
        return None

    df["time"] = pd.to_numeric(df["time"], errors="coerce")
    df = df.dropna(subset=["time", "mass_mg"]).copy()
    df_cleaned = df[df["mass_mg"] >= float(outlier_threshold_mg)].copy()

    if df_cleaned.empty:
        print(f"Warning: no data remains after filtering mass_mg < {outlier_threshold_mg}")
        return None

    aspirate_indices = df_cleaned[df_cleaned["command_type"] == "aspirate"].index
    if len(aspirate_indices) == 0:
        unique_commands = df_cleaned["command_type"].dropna().unique()
        print(f"Warning: no 'aspirate' command found in {csv_file_path}")
        print(f"Available command types: {unique_commands}")
        return None

    aspirate_start_idx = aspirate_indices[0]
    aspirate_time = df_cleaned.loc[aspirate_start_idx, "time"]

    delay_indices = df_cleaned[df_cleaned["command_type"] == "delay"].index
    delay_indices_after_aspirate = delay_indices[delay_indices > aspirate_start_idx]
    if len(delay_indices_after_aspirate) == 0:
        print(f"Warning: no 'delay' command found after 'aspirate' in {csv_file_path}")
        return None

    first_delay_idx = delay_indices_after_aspirate[0]
    last_delay_idx = delay_indices_after_aspirate[-1]
    first_delay_time = df_cleaned.loc[first_delay_idx, "time"]
    last_delay_time = df_cleaned.loc[last_delay_idx, "time"]

    df_aspirate_to_delay = df_cleaned[
        (df_cleaned["time"] >= aspirate_time)
        & (df_cleaned["time"] < first_delay_time)
    ].copy()
    df_delay_range = df_cleaned[
        (df_cleaned["time"] >= first_delay_time)
        & (df_cleaned["time"] <= last_delay_time)
    ].copy()

    if df_delay_range.empty:
        print(f"Warning: no data in delay range for {csv_file_path}")
        return None

    df_delay_range["time_second"] = df_delay_range["time"].round().astype(int)
    df_delay_averaged = (
        df_delay_range.groupby("time_second")
        .agg({"time": "mean", "mass_mg": "mean"})
        .reset_index(drop=True)
    )

    frames = []
    if not df_aspirate_to_delay.empty:
        frames.append(df_aspirate_to_delay[["time", "mass_mg"]])
    frames.append(df_delay_averaged[["time", "mass_mg"]])

    df_combined = pd.concat(frames, ignore_index=True).sort_values("time")
    df_combined = df_combined.reset_index(drop=True)

    if df_combined.empty:
        print(f"Warning: no data after combining for {csv_file_path}")
        return None

    result_df = _normalize_and_window_data(
        df_combined["time"].to_numpy(),
        df_combined["mass_mg"].to_numpy(),
        window_seconds=float(window_seconds),
    )
    if result_df is None:
        print(f"Warning: no data remains after filtering to 0-{window_seconds}s")
        return None

    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / csv_file_path.name
        result_df.to_csv(output_path, index=False)
    except Exception as exc:
        print(f"Error saving processed CSV: {exc}")
        return None

    print(f"Saved processed data to: {output_path}")
    print(
        "Data points: "
        f"{len(result_df)}, Time range: {result_df['Time'].min():.2f}s "
        f"to {result_df['Time'].max():.2f}s"
    )
    print(
        "Mass range: "
        f"{result_df['Weight'].min():.2f} mg to {result_df['Weight'].max():.2f} mg"
    )
    return result_df


def _normalize_and_window_data(times: Any, masses_mg: Any, *, window_seconds: float):
    if len(times) == 0:
        return None

    normalized_times = times - times[0]
    normalized_masses = masses_mg - masses_mg[0]

    time_mask = (normalized_times >= 0) & (normalized_times <= window_seconds)
    normalized_times = normalized_times[time_mask]
    normalized_masses = normalized_masses[time_mask]

    if len(normalized_times) == 0:
        return None

    normalized_times[0] = 0.0
    normalized_masses[0] = 0.0

    last_time = normalized_times[-1]
    last_mass = normalized_masses[-1]
    if last_time < window_seconds:
        if len(normalized_times) > 1:
            time_step = float(np.mean(np.diff(normalized_times)))
            if time_step <= 0:
                time_step = 1.0
        else:
            time_step = 1.0

        extension_times = np.arange(last_time + time_step, window_seconds + time_step, time_step)
        extension_times = extension_times[extension_times <= window_seconds]
        extension_masses = np.full_like(extension_times, last_mass)

        normalized_times = np.concatenate([normalized_times, extension_times])
        normalized_masses = np.concatenate([normalized_masses, extension_masses])
        print(f"Extended data from {last_time:.2f}s to {window_seconds:.2f}s")

    return pd.DataFrame({"Time": normalized_times, "Weight": normalized_masses})


def analyze_latest_viscosity_experiment(
    csv_file_path: str | Path | None = None,
    base_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Analyze a viscosity experiment CSV, defaulting to the latest raw CSV.
    """
    if not _require_pandas():
        return {"success": False, "message": "pandas not installed"}

    if csv_file_path is None:
        raw_data_dir = _viscosity_data_root() / "viscosity_raw_data"
        if not raw_data_dir.exists():
            return {
                "success": False,
                "message": f"Directory '{raw_data_dir}' not found.",
            }

        csv_files = list(raw_data_dir.glob("*.csv"))
        if not csv_files:
            return {
                "success": False,
                "message": f"No CSV files found in '{raw_data_dir}'.",
            }

        csv_file_path = max(csv_files, key=lambda path: path.stat().st_mtime)
        print(f"Found latest CSV file: {csv_file_path}")

    csv_file_path = Path(csv_file_path)

    if base_output_dir is None:
        processed_dir = _viscosity_data_root() / "viscosity_processed_data"
    else:
        processed_dir = Path(base_output_dir) / "viscosity_processed_data"

    try:
        processed_dir = processed_dir.resolve()
        processed_dir.mkdir(parents=True, exist_ok=True)
        print(f"Processed data directory: {processed_dir}")
    except Exception as exc:
        return {
            "success": False,
            "message": f"Failed to create output directory: {exc}",
        }

    result_df = analyze_viscosity_data(csv_file_path, processed_dir)
    if result_df is None:
        return {"success": False, "message": "Failed to analyze viscosity data"}
    if result_df.empty:
        return {"success": False, "message": "No data points after processing"}

    max_weight = float(result_df["Weight"].max())
    min_weight = float(result_df["Weight"].min())
    weight_change = max_weight - min_weight

    return {
        "success": True,
        "message": "Analysis complete",
        "data_points": len(result_df),
        "max_weight_mg": max_weight,
        "min_weight_mg": min_weight,
        "weight_change_mg": weight_change,
        "processed_csv_path": str(processed_dir / csv_file_path.name),
        "source_csv_path": str(csv_file_path),
        "result_df": result_df,
    }


def plot_and_save_viscosity_graph(
    result_df: Any,
    csv_file_path: str | Path,
    graph_output_dir: str | Path | None = None,
) -> str | None:
    """
    Plot normalized mass change vs time and save it as a PNG.
    """
    if plt is None:
        print("Cannot plot: matplotlib is not installed")
        return None
    if result_df is None or len(result_df) == 0:
        print("No data to plot")
        return None

    if graph_output_dir is None:
        graph_output_dir = _viscosity_data_root() / "viscosity_graphs"
    else:
        graph_output_dir = Path(graph_output_dir)

    try:
        graph_output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"Error creating graph output directory: {exc}")
        return None

    csv_file_path = Path(csv_file_path)
    graph_path = graph_output_dir / f"{csv_file_path.stem}_graph.png"

    try:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(
            result_df["Time"],
            result_df["Weight"],
            linewidth=2,
            color="#2ecc71",
            marker="o",
            markersize=3,
        )
        ax.set_xlabel("Time (s)", fontsize=12)
        ax.set_ylabel("Relative Mass Change (mg)", fontsize=12)
        ax.set_title("Normalized Mass Change vs Time", fontsize=14, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, min(30, max(1.0, float(result_df["Time"].max()))))
        fig.tight_layout()
        fig.savefig(graph_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as exc:
        print(f"Error saving graph: {exc}")
        plt.close("all")
        return None

    print(f"Graph saved to: {graph_path}")
    return str(graph_path)


def analyze_balance_data(
    balance_readings: list[dict[str, Any]],
    target_mass: float | None = None,
    target_volume_uL: float | None = None,
    density_g_per_mL: float = 1.0,
) -> dict[str, Any] | None:
    """Analyze balance readings and calculate mass and volume error metrics.

    ``density_g_per_mL`` is numerically equivalent to mg/uL, so delivered
    volume is ``mass_mg / density_g_per_mL``.
    """
    if not balance_readings or not _require_pandas():
        return None
    density = _validate_density(density_g_per_mL)

    df = pd.DataFrame(balance_readings)
    if df.empty:
        return None

    df = _ensure_mass_mg_columns(df)
    max_weight = float(df["mass_mg"].max())
    min_weight = float(df["mass_mg"].min())
    relative_mass_change = max_weight - min_weight
    relative_volume_change = calculate_volume_from_mass(relative_mass_change, density)

    mass_error = None
    if target_mass is not None and target_mass > 0:
        mass_error = float(target_mass) - relative_mass_change

    signed_error_uL = None
    absolute_error_uL = None
    if target_volume_uL is not None and target_volume_uL > 0:
        signed_error_uL = relative_volume_change - float(target_volume_uL)
        absolute_error_uL = abs(signed_error_uL)

    return {
        "relative_mass_change_mg": relative_mass_change,
        "relative_volume_change_uL": relative_volume_change,
        "density_g_per_mL": density,
        "target_volume_uL": target_volume_uL,
        "target_volume_ul": target_volume_uL,
        "signed_error_uL": signed_error_uL,
        "signed_error_ul": signed_error_uL,
        "absolute_error_uL": absolute_error_uL,
        "absolute_error_ul": absolute_error_uL,
        "mass_error_mg": mass_error,
        "max_weight_mg": max_weight,
        "min_weight_mg": min_weight,
        "readings_count": len(df),
    }


def _validate_density(density_g_per_mL: float) -> float:
    density = float(density_g_per_mL)
    if density <= 0:
        raise ValueError("density_g_per_mL must be greater than 0.")
    return density


def calculate_volume_from_mass(mass_mg: float, density_g_per_mL: float = 1.0) -> float:
    """
    Convert mass change in mg to delivered volume in uL.

    Because 1 g/mL is equal to 1 mg/uL, the conversion is:
    volume_uL = mass_mg / density_g_per_mL.
    """
    return float(mass_mg) / _validate_density(density_g_per_mL)


def calculate_signed_volume_error(
    actual_mass_change_mg: float,
    target_volume_uL: float,
    density_g_per_mL: float = 1.0,
) -> float:
    """
    Calculate signed volume error in uL from gravimetric mass change.

    Positive means over-transfer; negative means under-transfer.
    """
    actual_volume_uL = calculate_volume_from_mass(
        actual_mass_change_mg,
        density_g_per_mL,
    )
    return actual_volume_uL - float(target_volume_uL)


def calculate_signed_error(actual_mass_change_mg: float, target_mass_mg: float) -> float:
    """
    Calculate signed error between actual and target mass change in mg.

    Positive means over-transfer; negative means under-transfer.

    For viscosity optimization, prefer ``calculate_signed_volume_error`` so
    non-water samples use their measured density.
    """
    return float(actual_mass_change_mg) - float(target_mass_mg)
