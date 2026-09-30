import importlib.util
from pathlib import Path
import pytest
spec = importlib.util.spec_from_file_location('four_cpu', Path(__file__).with_name('run.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

@pytest.mark.parametrize('count,affinity,quota,machine', [
    (2, 2, None, 'x86_64'), (4, 2, None, 'x86_64'),
    (4, 4, 2, 'x86_64'), (8, 4, None, 'x86_64'), (4, 4, None, 'aarch64'),
])
def test_rejects_wrong_capacity(count, affinity, quota, machine):
    with pytest.raises(ValueError):
        module.validate_capacity(count, affinity, quota, machine)

@pytest.mark.parametrize('quota', [None, 4])
def test_accepts_four_cpu(quota):
    module.validate_capacity(4, 4, quota, 'x86_64')
