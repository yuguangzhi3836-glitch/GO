import pytest
from unittest.mock import patch

from go_hotel.services.chain_directory_controller import ChainDirectoryController
from go_hotel.services.chain_hotel_registry import ChainCode


def test_entire_directory_advances_until_complete():
    controller = ChainDirectoryController()
    calls = [
        {"enumerated": 2, "tasks": [{"task_id": "a"}, {"task_id": "b"}], "next_cursor": "c1", "directory_complete": False},
        {"enumerated": 2, "tasks": [{"task_id": "c"}, {"task_id": "d"}], "next_cursor": None, "directory_complete": True},
    ]
    with patch("go_hotel.services.chain_directory_controller.chain_autonomous_build_service.enumerate_and_enqueue", side_effect=calls):
        result = controller.enqueue_entire_directory(chain=ChainCode.HYATT, fetch_page=lambda _: "x")
    assert result["directory_complete"] is True
    assert result["pages"] == 2
    assert result["enumerated"] == 4
    assert result["unique_tasks"] == 4


def test_directory_rejects_nonprogressing_cursor():
    controller = ChainDirectoryController()
    with patch("go_hotel.services.chain_directory_controller.chain_autonomous_build_service.enumerate_and_enqueue", return_value={
        "enumerated": 1, "tasks": [{"task_id": "a"}], "next_cursor": "same", "directory_complete": False,
    }):
        with pytest.raises(ValueError, match="PROGRESS_REQUIRED"):
            controller.enqueue_entire_directory(chain=ChainCode.HYATT, fetch_page=lambda _: "x", cursor="same")


def test_directory_page_budget_returns_resumable_hold():
    controller = ChainDirectoryController()
    values = [
        {"enumerated": 1, "tasks": [{"task_id": "a"}], "next_cursor": "c1", "directory_complete": False},
        {"enumerated": 1, "tasks": [{"task_id": "b"}], "next_cursor": "c2", "directory_complete": False},
    ]
    with patch("go_hotel.services.chain_directory_controller.chain_autonomous_build_service.enumerate_and_enqueue", side_effect=values):
        result = controller.enqueue_entire_directory(chain=ChainCode.HYATT, fetch_page=lambda _: "x", max_pages=2)
    assert result["directory_complete"] is False
    assert result["next_cursor"] == "c2"
    assert result["hold_reason"] == "CHAIN_DIRECTORY_PAGE_BUDGET_EXHAUSTED"
