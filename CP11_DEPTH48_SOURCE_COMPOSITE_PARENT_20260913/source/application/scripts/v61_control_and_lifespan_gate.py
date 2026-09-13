#!/usr/bin/env python3
from __future__ import annotations
import asyncio, os
from pathlib import Path
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:////tmp/go_v61_control_gate_{os.getpid()}.db")
from go_hotel.core import master_baseline as m
from go_hotel.core import v61_commercial_policy as p


def approx(a,b,rel=1e-6):
    return abs(a-b) <= max(abs(b)*rel, rel)

def static_checks():
    assert m.MASTER_VERSION == 'V6.1'
    assert m.MASTER_DATE == '2026-08-22'
    assert m.AI_BASE_INFRASTRUCTURE_CALL_PRICE_CNY == 0
    assert m.T20_FINAL_COMPLETION_TARGET == 1.0
    assert m.EQUIVALENT_BILLING_MONTHS == 10
    assert m.STRATEGIC_POSITIONING == ('AI时代的全球旅行入口','AI时代的全球旅行基础设施','AI时代的全球旅行官方直订平台')
    assert m.IDENTITY_TRANSACTION_INFRASTRUCTURE_EXPLANATION == '旅行身份与交易基础设施是AI时代全球旅行基础设施的核心能力内涵'
    assert m.AI_TRAVEL_INFRASTRUCTURE_PRINCIPLE == 'EVERY_AI_CAN_UNDERSTAND_TRAVEL_GO_COMPLETES_TRAVEL'
    assert 'HOTEL_OWNS_PRICE_AND_GO_MUST_NOT_AUTO_CHANGE_IT' in m.LOCKED_INVARIANTS
    assert 'GO_DOES_NOT_BUY_AI_DISTRIBUTION' in m.LOCKED_INVARIANTS
    assert p.monthly_subscription_cny('UP_TO_TWO_DIAMOND', year=1) == 399
    assert p.monthly_subscription_cny('THREE_DIAMOND', year=1) == 699
    assert p.monthly_subscription_cny('FOUR_DIAMOND', year=1) == 999
    assert p.monthly_subscription_cny('FIVE_DIAMOND', year=1) == 1999
    assert p.monthly_subscription_cny('FOUR_DIAMOND',130,year=2) == 999
    assert p.monthly_subscription_cny('FOUR_DIAMOND',131,year=2) == 1299
    assert p.monthly_subscription_cny('FIVE_DIAMOND',199,year=2) == 1999
    assert p.monthly_subscription_cny('FIVE_DIAMOND',250,year=2) == 2999
    assert p.monthly_subscription_cny('FIVE_DIAMOND',301,year=2) == 3999
    assert approx(p.y1_weighted_monthly_cny(),667.965517)
    assert approx(p.mature_weighted_monthly_cny(),740.379310)
    assert approx(p.base_subscription_revenue_cny('Y1'),400_779_310.34)
    assert approx(p.base_subscription_revenue_cny('Y2'),2_221_137_931.03)
    assert approx(p.base_subscription_revenue_cny('Y3'),3_998_048_275.86)
    assert p.Y1_TOTAL_OPERATING_BUDGET_CNY == 160_000_000
    assert p.Y1_ADVERTISING_BRAND_BUDGET_CNY == 30_000_000
    assert p.star_equivalent_label(3) == 'GO ★★★'
    assert p.star_equivalent_label(4) == 'GO ★★★★'
    assert p.star_equivalent_label(5) == 'GO ★★★★★'
    assert p.star_equivalent_label(6) == 'GO ★★★★★+'
    source=Path('src/go_hotel/main.py').read_text(encoding='utf-8')
    assert '@app.on_event("startup")' not in source
    assert '@app.on_event("shutdown")' not in source
    assert '@asynccontextmanager' in source and 'lifespan=lifespan' in source and 'identity_service.bootstrap()' in source

def main():
    static_checks()
    print('V61_CONTROL_AND_LIFESPAN_STATIC_GATE_OK')

if __name__=='__main__': main()
