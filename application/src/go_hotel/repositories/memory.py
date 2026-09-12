from __future__ import annotations
from dataclasses import asdict
from typing import Any
from go_hotel.domain.models import Offer, Prebook, Order, Payment, Event


class MemoryRepository:
    def __init__(self) -> None:
        self.offers: dict[str, Offer] = {}
        self.prebooks: dict[str, Prebook] = {}
        self.orders: dict[str, Order] = {}
        self.payments: dict[str, Payment] = {}
        self.events: list[Event] = []
        self.idempotency: dict[tuple[str, str], dict[str, Any]] = {}

    def reset(self) -> None:
        self.__init__()

    def append_event(self, event: Event) -> None:
        self.events.append(event)

    def event_dicts(self, aggregate_id: str) -> list[dict[str, Any]]:
        return [asdict(e) for e in self.events if e.aggregate_id == aggregate_id]

repo = MemoryRepository()
