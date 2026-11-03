from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import os
import platform

from .scoring import _solver_timeout_seconds

SCHEDULER_REVISION = "2026-11-03-relocation-2"


def scheduler_runtime_diagnostics() -> dict:
    try:
        ortools_version = version("ortools")
    except PackageNotFoundError:
        ortools_version = None
    load_error = None
    try:
        from ortools.sat.python import cp_model
        cp_model.CpModel()
    except (ImportError, OSError) as exc:
        load_error = type(exc).__name__
    return {
        "scheduler_revision": SCHEDULER_REVISION,
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "search_budget_seconds": _solver_timeout_seconds(),
        "ortools_version": ortools_version,
        "cp_sat_available": load_error is None,
        "cp_sat_load_error": load_error,
    }
