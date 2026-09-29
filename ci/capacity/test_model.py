import copy
import json
from pathlib import Path
import pytest
from model import calculate, check_database_budget

MODEL = json.loads((Path(__file__).parent / "planning-example.json").read_text())


def test_million_online_request_math():
    result = calculate(MODEL["traffic"])
    assert result["steady_dynamic_rps"] == 100000
    assert result["peak_dynamic_rps"] == 300000
    assert sum(result["peak_by_request_class"].values()) == 300000
    assert result["provisioned_rps_target"] == pytest.approx(428571.428571)


def test_rollout_and_background_pools_are_counted():
    result = check_database_budget(MODEL["database"])
    assert result["required"] == 100
    assert result["available"] == 150


def test_scaling_without_database_budget_is_rejected():
    model = copy.deepcopy(MODEL["database"])
    model["services"][0]["max_replicas"] = 100
    with pytest.raises(ValueError, match="exceeded"):
        check_database_budget(model)


@pytest.mark.parametrize("field,value", [("pool_size", 0), ("max_overflow", -1),
    ("processes_per_replica", 1.5), ("max_replicas", True), ("rollout_surge_replicas", -1)])
def test_invalid_pool_budgets_are_rejected(field, value):
    model = copy.deepcopy(MODEL["database"])
    model["services"][0][field] = value
    with pytest.raises(ValueError):
        check_database_budget(model)


@pytest.mark.parametrize("field,value", [("online_users", 0),
    ("request_interval_seconds", 0), ("peak_multiplier", float("nan")),
    ("capacity_reserve_fraction", 1), ("request_mix", {"read": 0.9})])
def test_invalid_traffic_assumptions_are_rejected(field, value):
    model = copy.deepcopy(MODEL["traffic"])
    model[field] = value
    with pytest.raises(ValueError):
        calculate(model)
