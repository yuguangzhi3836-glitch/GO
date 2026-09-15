#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile


def _run_contract_assertions() -> None:
    # Import only after GO_MEDIA_CACHE_DIR is resolved. media_harvester creates its
    # local cache service at module import time, so the release gate must never
    # require the candidate source tree to be writable.
    from go_hotel.core.r8_implementation_alignment import snapshot
    from go_hotel.services.media_harvester import PUBLISHABLE_RIGHTS

    s = snapshot()
    assert s['release_train'] == 'R8.1'
    assert s['control_version'] == 'V6.1'
    assert 'HOTEL_REGISTRATION_AND_OFFICIAL_ASSOCIATION' in s['day1_hotel_coverage_pipeline']
    assert 'HOTEL_CLAIM' not in s['day1_hotel_coverage_pipeline']
    assert s['inventory_priority'] == ['GO_DIRECT', 'THIRD_PARTY_API_FALLBACK', 'DEEP_LINK_FALLBACK']
    assert s['after_sales_model']['call_center'] is False
    assert s['identity_truth']['admin_first_enrollment_ui_delivered'] is False
    assert 'DISTRIBUTION_LICENSE' in PUBLISHABLE_RIGHTS


def main() -> None:
    configured = os.environ.get('GO_MEDIA_CACHE_DIR')
    if configured:
        _run_contract_assertions()
    else:
        # TemporaryDirectory gives an absolute /tmp-style writable cache and
        # removes it on normal/exceptional gate exit.
        with tempfile.TemporaryDirectory(prefix='go-r8-contract-media-') as tmp:
            os.environ['GO_MEDIA_CACHE_DIR'] = tmp
            try:
                _run_contract_assertions()
            finally:
                os.environ.pop('GO_MEDIA_CACHE_DIR', None)
    print('R8.1_IMPLEMENTATION_ALIGNMENT_CONTRACT_GATE: PASS')


if __name__ == '__main__':
    main()
