from pathlib import Path
ROOT=Path(__file__).parents[1]
CAP=(ROOT/"src/go_hotel/services/browser_capture_runner.py").read_text()
RUN=(ROOT/"acceptance/run_hworld_atour_browser_capture.py").read_text()

def test_capture_uses_normal_browser_network_only():
 assert "sync_playwright" in CAP
 assert 'page.on("response",on_response)' in CAP
 assert 'rtype not in {"xhr","fetch","document"}' in CAP

def test_capture_is_official_host_fail_closed():
 assert "BROWSER_CAPTURE_ENTRY_NOT_OFFICIAL" in CAP
 assert "_host_allowed(chain,p.hostname)" in CAP

def test_capture_does_not_encode_login_or_booking_actions():
 for token in ("登录","会员","支付","预订","book now","sign in"):
  assert token in CAP
 assert "BLOCK_TEXT" in CAP

def test_runner_requires_two_independent_rounds_and_frozen_inventory():
 assert "for round_no in (1,2)" in RUN
 assert "compare_independent_captures" in RUN
 assert "frozen_inventory" in RUN
 assert "inventory_sha256" in RUN

def test_capture_pass_does_not_enable_production_adapter():
 assert '"production_adapter_enabled":False' in RUN
 assert '"source_contract_promotion_required":True' in RUN
