"""Fixed HK Staging handler registry. No caller-supplied commands are executed."""
from __future__ import annotations

import importlib


def _call(module: str, function: str, payload: dict):
    fn = getattr(importlib.import_module(module), function, None)
    if not callable(fn):
        raise RuntimeError("HK_CONTROL_GATE_HANDLER_NOT_AVAILABLE")
    result = fn(payload)
    return result if isinstance(result, dict) else {"result": result}


def release_gate(payload):
    return _call("go_hotel.services.production_bindings", "production_authorities", payload)


def postgres_crash_recovery(payload):
    return _call("go_hotel.control.runtime_gates", "postgres_crash_recovery_gate", payload)


def hyatt_10_real_e2e(payload):
    return _call("go_hotel.control.runtime_gates", "hyatt_10_real_e2e_gate", payload)


def masterpiece_browser_gate(payload):
    return _call("go_hotel.control.runtime_gates", "hotel_masterpiece_browser_gate", payload)


def round_trip_gate(payload):
    return {"round_trip": "PASS", "echo_digest": payload.get("echo_digest")}


def build_hk_control_handlers():
    return {
        "DEPTH10_RELEASE_GATE": release_gate,
        "POSTGRES_CRASH_RECOVERY_GATE": postgres_crash_recovery,
        "HYATT_10_REAL_E2E": hyatt_10_real_e2e,
        "HOTEL_MASTERPIECE_BROWSER_GATE": masterpiece_browser_gate,
        "CONTROL_PLANE_ROUND_TRIP_GATE": round_trip_gate,
    }
