import pytest
from go_hotel.core import master_baseline as m

pytestmark = pytest.mark.no_db

def test_v61_master_identity():
    assert m.MASTER_VERSION == "V6.1"
    assert m.STRATEGIC_POSITIONING == ("AI时代的全球旅行入口", "AI时代的全球旅行基础设施", "AI时代的全球旅行官方直订平台")
    assert m.IDENTITY_TRANSACTION_INFRASTRUCTURE_EXPLANATION == "旅行身份与交易基础设施是AI时代全球旅行基础设施的核心能力内涵"
    assert m.AI_TRAVEL_INFRASTRUCTURE_PRINCIPLE == "EVERY_AI_CAN_UNDERSTAND_TRAVEL_GO_COMPLETES_TRAVEL"
