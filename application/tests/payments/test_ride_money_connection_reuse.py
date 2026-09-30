from pathlib import Path

SOURCE=Path(__file__).parents[1]/'src/go_hotel/services/vertical_transaction_bridge.py'

def test_ride_reuses_one_postgres_connection_without_collapsing_commits():
    text=SOURCE.read_text()
    body=text.split('def _ride_money_graph',1)[1].split('def checkout_contract',1)[0]
    assert 'with engine.connect() as conn:' in body
    assert body.count('create_in_session(')==2
    assert body.count('s.commit()')==2
    assert body.index("movement_type':'AUTHORIZATION'") < body.index('s.commit()') < body.index("movement_type':'CAPTURE'")
    assert "if engine.dialect.name=='sqlite':" in body

def test_other_verticals_keep_existing_money_boundary():
    text=SOURCE.read_text()
    checkout=text.split('def checkout_contract',1)[1]
    assert "if vertical=='RIDE':" in checkout
    assert "unified_money_movement_service.create(iid" in checkout
