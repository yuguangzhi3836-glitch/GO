#!/usr/bin/env python3
"""Run one bounded batch using only the explicit isolated fleet simulator."""
import argparse
import json
from go_hotel.mobility.ride.flight_sync import flight_ride_sync
from go_hotel.mobility.ride.isolated_fleet import IsolatedFleetAdapter


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--simulate', action='store_true', required=True)
    p.add_argument('--receipt-db', required=True, help='Persistent isolated fleet receipt database path')
    p.add_argument('--limit', type=int, default=100)
    args = p.parse_args()
    adapter = IsolatedFleetAdapter(args.receipt_db)
    results = [flight_ride_sync.process(x, adapter) for x in flight_ride_sync.pending(args.limit)]
    print(json.dumps({'data_mode': 'SIMULATION', 'external_live': False, 'results': results}, ensure_ascii=False))


if __name__ == '__main__': main()
