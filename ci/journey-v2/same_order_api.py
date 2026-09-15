"""Six real API orders, three authenticated actors, and an independent SQL audit.

This does not drive a browser or certify a native device. The database and
credentials are disposable; only synthetic business observations are retained.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from ledger import audit


def main():
    root = Path(__file__).resolve().parents[2]
    evidence = Path(sys.argv[1]).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    binding = json.loads(Path(sys.argv[2]).read_text())
    if 'commit' not in binding: binding['commit'] = binding['candidate_commit']
    with tempfile.TemporaryDirectory(prefix='go-depth48-api-') as temporary:
        state = Path(temporary)
        env = {k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL','TZ'}}
        env.update(PYTHONPATH=os.pathsep.join([str(root/'ci/retention/guard'),
            str(root/'application/src'),str(root/'application'),str(root/'application/tests')]),
            GO_TEST_DB_PATH=str(state/'acceptance.db'),
            GO_JOURNEY_EVIDENCE=str(evidence/'six-order-observations.json'),
            # This step runs pytest with cwd=application, i.e. with the product
            # source tree as the process cwd. MediaHarvesterService defaults its
            # cache dir to the relative path `var/media_cache`, which would land
            # inside `application/` and then break the strict source-identity
            # check performed by the next step. Keep every runtime cache in the
            # disposable state directory instead.
            GO_MEDIA_CACHE_DIR=str(state/'media_cache'),
            PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',APP_ENV='test',
            MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false')
        with (evidence/'pytest.log').open('w') as log:
            result = subprocess.run([sys.executable,'-m','pytest','-p','pytest_asyncio.plugin',
                '-p','no:cacheprovider','-o','addopts=','-q',
                'tests/test_depth42_cross_end_journeys.py::test_six_vertical_paid_refunded_money_and_three_actor_same_order',
                '--junitxml='+str(evidence/'junit.xml')], cwd=root/'application',env=env,
                stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError('SAME_ORDER_API_FAILED: inspect pytest.log')
        rows = json.loads((evidence/'six-order-observations.json').read_text())
        report = dict(binding, input_kind='API_TESTCLIENT_NOT_BROWSER', order_checks=[
            {'vertical':row['vertical'],'order_id':row['order_id'],
             'quoted_refund_minor':row['refund_minor'],
             'final':row['actor_views']['/v1/consumer']['final']} for row in rows])
        (state/'runtime-binding.json').write_text(json.dumps(binding))
        (evidence/'api-results.json').write_text(json.dumps(report,indent=2)+'\n')
        audit(state,evidence,'api-results.json')
        print(json.dumps({'same_order_api':'PASS','verticals':len(rows),'actor_details':18,
            'refresh_checks':18,'relogin_checks':18,'independent_sql':'PASS',
            'browser':'NOT_EXECUTED','native_device':'NOT_EXECUTED'}))


if __name__ == '__main__':
    main()
