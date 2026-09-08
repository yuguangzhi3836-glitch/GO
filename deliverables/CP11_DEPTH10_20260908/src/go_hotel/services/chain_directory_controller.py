"""Resumable whole-directory controller for autonomous chain ingestion."""
from __future__ import annotations

from .chain_autonomous_build import chain_autonomous_build_service
from .chain_hotel_registry import ChainCode


class ChainDirectoryController:
    def enqueue_entire_directory(self, *, chain: ChainCode, fetch_page, cursor: str | None = None,
                                 actor: str = "SYSTEM", max_pages: int = 500) -> dict:
        if not 1 <= int(max_pages) <= 5000:
            raise ValueError("CHAIN_DIRECTORY_MAX_PAGES_INVALID")
        current = cursor
        pages = 0
        enumerated = 0
        task_ids = []
        seen_cursors = set()
        while pages < int(max_pages):
            if current and current in seen_cursors:
                raise ValueError("CHAIN_DIRECTORY_CURSOR_LOOP")
            if current:
                seen_cursors.add(current)
            result = chain_autonomous_build_service.enumerate_and_enqueue(
                chain=chain, fetch_page=fetch_page, cursor=current, actor=actor,
            )
            pages += 1
            enumerated += int(result.get("enumerated") or 0)
            task_ids.extend(str(x["task_id"]) for x in result.get("tasks") or [])
            next_cursor = result.get("next_cursor")
            if result.get("directory_complete"):
                return {
                    "chain": chain.value, "directory_complete": True,
                    "pages": pages, "enumerated": enumerated,
                    "unique_tasks": len(set(task_ids)), "next_cursor": None,
                }
            if not next_cursor or next_cursor == current:
                raise ValueError("CHAIN_DIRECTORY_PROGRESS_REQUIRED")
            current = next_cursor
        return {
            "chain": chain.value, "directory_complete": False,
            "pages": pages, "enumerated": enumerated,
            "unique_tasks": len(set(task_ids)), "next_cursor": current,
            "hold_reason": "CHAIN_DIRECTORY_PAGE_BUDGET_EXHAUSTED",
        }


chain_directory_controller = ChainDirectoryController()
