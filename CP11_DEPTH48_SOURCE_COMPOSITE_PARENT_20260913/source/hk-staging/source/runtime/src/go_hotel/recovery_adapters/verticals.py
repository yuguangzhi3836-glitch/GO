from __future__ import annotations
from .deterministic import DeterministicRecoveryAdapter

class FlightRecoveryAdapter(DeterministicRecoveryAdapter):
    def __init__(self): super().__init__('FLIGHT')
class RailRecoveryAdapter(DeterministicRecoveryAdapter):
    def __init__(self): super().__init__('RAIL')
class MobilityRideRecoveryAdapter(DeterministicRecoveryAdapter):
    def __init__(self): super().__init__('RIDE')
class MobilityRentalRecoveryAdapter(DeterministicRecoveryAdapter):
    def __init__(self): super().__init__('RENTAL')
class HotelRecoveryAdapter(DeterministicRecoveryAdapter):
    def __init__(self): super().__init__('HOTEL')
class AttractionRecoveryAdapter(DeterministicRecoveryAdapter):
    def __init__(self): super().__init__('ATTRACTION')
