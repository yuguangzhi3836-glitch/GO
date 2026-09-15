from __future__ import annotations
from .verticals import (
    FlightRecoveryAdapter,RailRecoveryAdapter,MobilityRideRecoveryAdapter,
    MobilityRentalRecoveryAdapter,HotelRecoveryAdapter,AttractionRecoveryAdapter,
)
class RecoveryAdapterRegistry:
    def __init__(self): self._items={}
    def register(self,a): self._items[a.metadata.vertical]=a;return a
    def for_vertical(self,vertical):
        if vertical not in self._items: raise KeyError(f'RECOVERY_ADAPTER_NOT_CONFIGURED:{vertical}')
        return self._items[vertical]
    def by_key(self,key):
        for a in self._items.values():
            if a.metadata.adapter_key==key:return a
        raise KeyError(f'RECOVERY_ADAPTER_NOT_CONFIGURED:{key}')
    def list(self): return [a.metadata for a in self._items.values()]
recovery_adapter_registry=RecoveryAdapterRegistry()
for adapter in (FlightRecoveryAdapter(),RailRecoveryAdapter(),MobilityRideRecoveryAdapter(),MobilityRentalRecoveryAdapter(),HotelRecoveryAdapter(),AttractionRecoveryAdapter()):
    recovery_adapter_registry.register(adapter)
