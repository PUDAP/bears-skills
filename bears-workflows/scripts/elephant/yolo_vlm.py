"""Thin launcher for the Elephant laptop-only YOLO/VLM workflow.

This wrapper intentionally does not copy the large operational runner. It finds
and runs the workspace runner so workflow docs can point to one stable command
without duplicating experimental code.
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_source() -> Path:
    return _repo_root() / "elephant" / "yolo_vlm.py"


def _edge_env_values() -> set[str]:
    env_path = _repo_root() / "elephant" / "edge" / ".env"
    if not env_path.exists():
        return set()

    names: set[str] = set()
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() and value.strip():
            names.add(name.strip())
    return names


def _env_status() -> list[str]:
    edge_env_names = _edge_env_values()
    required = [
        ("OPENROUTER_API_KEY", "from elephant/edge/.env"),
        ("MINIPC_SSH_HOST", ""),
        ("PI_HOST_FROM_MINIPC", ""),
        ("LOCAL_PI_SSH_PORT", ""),
        ("LOCAL_CAM0_PORT", "CAM0"),
        ("LOCAL_ROBOT_PORT", ""),
        ("ELEPHANT_COMBINED_VIEWER_PORT", "combined viewer"),
        ("ELEPHANT_FRONT_STREAM_URL", "front cam"),
        ("ELEPHANT_SIDE_STREAM_URL", "side cam"),
    ]
    lines: list[str] = []
    for name, label in required:
        value = os.environ.get(name)
        suffix = f" ({label})" if label else ""
        if value or name in edge_env_names:
            lines.append(f"OK      {name}{suffix}")
        else:
            lines.append(f"MISSING {name}{suffix}")
    optional = [
        ("ELEPHANT_COMBINED_VIEWER_URL", "combined viewer base URL"),
        ("ELEPHANT_FRONT_BROWSER_URL", "front cam browser"),
        ("ELEPHANT_SIDE_BROWSER_URL", "side cam browser"),
    ]
    for name, label in optional:
        value = os.environ.get(name)
        suffix = f" ({label})" if label else ""
        if value:
            lines.append(f"OK      {name}{suffix}")
        else:
            lines.append(f"OPTIONAL {name}{suffix}")
    return lines


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or check the Elephant YOLO/VLM laptop workflow.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=_default_source(),
        help="Path to the operational Elephant YOLO/VLM runner.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate source path and print environment status without running hardware.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    source = args.source.resolve()

    if not source.exists():
        print(f"Operational runner not found: {source}", file=sys.stderr)
        return 2

    if args.check:
        print(f"Operational runner: {source}")
        for line in _env_status():
            print(line)
        return 0

    sys.argv = [str(source)]
    runpy.run_path(str(source), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
