import importlib.util
from pathlib import Path

SCRIPT=Path(__file__).parents[1]/'scripts'/'aoluguya_firecrawl_media_discovery.py'
spec=importlib.util.spec_from_file_location('aoluguya_discovery_202',SCRIPT)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_capacity_and_scene_budgets_sum_to_160():
    assert module.TARGET_CANDIDATE_CAPACITY==160
    assert sum(module.SCENE_BUDGETS.values())==100
    assert set(module.SCENE_BUDGETS)=={'EXTERIOR','LOBBY','ROOM','DINING','WELLNESS','SIGNATURE_SPACE'}

def test_budget_selector_enforces_all_six_scenes():
    keywords={
      'EXTERIOR':'hotel exterior','LOBBY':'hotel lobby','ROOM':'guestroom',
      'DINING':'restaurant','WELLNESS':'swimming pool','SIGNATURE_SPACE':'banquet hall',
    }
    items=[]
    for scene,budget in module.SCENE_BUDGETS.items():
        for i in range(budget):
            items.append({'source_url':f'https://img.test/media/{i}-{scene[0]}.jpg','source_group':f'SOURCE_{i%2}','title':keywords[scene]})
    for i in range(60):
        items.append({'source_url':f'https://img.test/flex/{i}.jpg','source_group':f'FLEX_{i%3}','title':'guestroom'})
    selected,evidence=module.select_to_scene_budgets(items,160,module.SCENE_BUDGETS)
    assert len(selected)==160
    assert evidence['scene_budget_gate_pass'] is True
    assert all(evidence['scene_budget_checks'].values())

def test_budget_selector_holds_when_one_scene_is_missing():
    items=[{'source_url':f'https://img.test/room/{i}.jpg','source_group':'OTA','title':'guestroom'} for i in range(160)]
    selected,evidence=module.select_to_scene_budgets(items,160,module.SCENE_BUDGETS)
    assert len(selected)==160
    assert evidence['scene_budget_gate_pass'] is False
    assert evidence['scene_budget_checks']['EXTERIOR'] is False
