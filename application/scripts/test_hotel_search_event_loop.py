"""Targeted no-DB concurrency regression, executed against actual source AST.

Only external collaborators are faked. Selected production classes/functions are
compiled unchanged, avoiding import-time database setup. This is NOT a database
integration or 1000-user capacity test. Run with --source-root application/src.
"""
from __future__ import annotations
import argparse
import ast
import asyncio
import contextvars
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from starlette.concurrency import run_in_threadpool
from anyio import CapacityLimiter, to_thread

ROOT = Path(__file__).resolve().parents[1] / 'src'
CTX = contextvars.ContextVar('test_request', default=None)


def load(relative, names, env):
    tree = ast.parse((ROOT / 'go_hotel' / relative).read_text())
    tree.body = [x for x in tree.body if (isinstance(x, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and x.name in names) or (isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_search_write_limiter' for t in x.targets))]
    for item in tree.body:
        if hasattr(item, 'decorator_list'): item.decorator_list = []
    env = {'__name__': 'isolated_production_code', 'asyncio': asyncio,
           'run_in_threadpool': run_in_threadpool, **env}
    exec(compile(ast.fix_missing_locations(tree), str(ROOT / relative), 'exec', flags=__import__('__future__').annotations.compiler_flag), env)
    return env


class SearchConcurrency(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.loop_thread = threading.get_ident()
        self.calls = []
        self.block_threads = []
        self.connector_threads = []
        self.failure_point = None
        self.offer = NS(offer_id='off-1', hotel_id='hotel-1', connector_id=None,
                        supplier_id=None, official_direct=True, total_amount_minor=12345, currency='CNY')
        self.sla = NS(health_status='HEALTHY')
        self.decision = NS(decision_id='route-1')
        outer = self

        def blocking(name, result=None):
            def call(*args, **kwargs):
                outer.calls.append((name, args))
                outer.block_threads.append(threading.get_ident())
                assert CTX.get() == 'request-1'
                time.sleep(.025)
                if outer.failure_point == name:
                    raise RuntimeError('injected-' + name)
                return result
            return call
        self.blocking = blocking

        class Connector:
            def __init__(self, *args): pass
            async def search(self, *args):
                outer.connector_threads.append(threading.get_ident())
                await asyncio.sleep(.001)
                return [outer.offer]
        class Candidate:
            def __init__(self, cid, offer, sid, authorized, rollout, sla, rank):
                self.connector_id, self.offer, self.supplier_id = cid, offer, sid
            def ranking_key(self): return 1
        def decision(*args):
            return NS(decision_id=args[0], selected_connector_id=args[3], fallback_connector_ids=args[6])
        router_env = load('routing/router.py', {'TrafficRouter'}, {
            'registry': NS(get=lambda cid: cid), 'ResilientConnector': Connector,
            'sla_service': NS(get=blocking('sla', self.sla)),
            'RouteCandidate': Candidate, 'RoutingDecision': decision, 'new_id': lambda p: p + '-1'})
        self.router = router_env['TrafficRouter']()
        self.router._active = blocking('active', [{'connector_id':'conn-1','supplier_id':'sup-1','rollout_percent':100}])
        self.router._save = blocking('routing-save')
        self.router._reason_codes = lambda c: ['UNCHANGED']
        merge_decision = NS(selected_offer_id='off-1', decision_id='merge-1')
        env = load('services/booking.py', {'BookingService'}, {
            'traffic_router':self.router, 'to_thread':to_thread, 'CapacityLimiter':CapacityLimiter,
            'offer_merge_engine':NS(merge=blocking('merge', ([self.offer], [merge_decision]))),
            'repo': NS(save_offer_with_event=blocking('offer-save')),
            'fare_snapshot':NS(seed_mock_offer=blocking('fare-seed')),
            'new_id':lambda p:p + '-1', 'Event':lambda *a:a})
        self.booking = env['BookingService']()
        summary = {'go_score':88,'recommendation_status':'ELIGIBLE','judgment_id':'judgment-1'}
        env = load('api/routes/hotel.py', {'search_hotels', '_search_response'}, {
            'booking_service':self.booking,
            'judgment_service':NS(public_summary_or_default=blocking('judgment', summary))})
        self.route = env['search_hotels']
        self.body = NS(destination=NS(city_code='TYO'), stay=NS(check_in='2026-10-01',check_out='2026-10-02'), currency='CNY')
        CTX.set('request-1')

    async def test_search_all_sync_work_off_loop_and_business_effects_retained(self):
        ticks=[]
        done=False
        async def heartbeat():
            while not done:
                ticks.append(time.monotonic())
                await asyncio.sleep(.002)
        beat=asyncio.create_task(heartbeat())
        try:
            result=await self.route(self.body)
        finally:
            done=True
            await beat
        self.assertTrue(self.block_threads)
        self.assertNotIn(self.loop_thread, self.block_threads, 'sync DB collaborators block the ASGI event loop')
        self.assertEqual(self.connector_threads,[self.loop_thread])
        self.assertEqual([x[0] for x in self.calls],['active','sla','routing-save','merge','offer-save','fare-seed','judgment'])
        self.assertGreater(len(ticks),10)
        self.assertLess(max(b-a for a,b in zip(ticks,ticks[1:])), .10)
        row=result['data']['hotels'][0]
        self.assertEqual(row['judgment_id'],'judgment-1')
        self.assertEqual(row['best_offer']['total_amount_minor'],12345)
        self.assertEqual(self.offer.connector_id,'conn-1')
        self.assertEqual(self.offer.supplier_id,'sup-1')
        event=next(args[1] for name,args in self.calls if name=='offer-save')
        self.assertEqual(event[4]['routing_decision_id'],'route-1')
        self.assertEqual(event[4]['merge_decision_id'],'merge-1')

    async def test_write_failure_propagates_without_false_success(self):
        self.failure_point='offer-save'
        with self.assertRaisesRegex(RuntimeError,'injected-offer-save'):
            await self.route(self.body)
        self.assertNotIn('fare-seed',[x[0] for x in self.calls])
        self.assertNotIn('judgment',[x[0] for x in self.calls])
        self.failure_point=None
        recovered=await self.route(self.body)
        self.assertEqual(len(recovered['data']['hotels']),1)

    async def test_judgment_failure_propagates(self):
        self.failure_point='judgment'
        with self.assertRaisesRegex(RuntimeError,'injected-judgment'):
            await self.route(self.body)

    async def test_empty_search_keeps_decision_without_offer_writes(self):
        self.router._active = self.blocking('active', [])
        self.booking._merge_and_save_search = lambda candidates, decision: []
        result=await self.route(self.body)
        self.assertEqual(result,{'data':{'hotels':[]}})
        self.assertEqual([n for n,a in self.calls],['active','routing-save'])

    async def test_threadpool_bound_preserved_under_concurrent_search(self):
        import anyio.to_thread
        limiter=anyio.to_thread.current_default_thread_limiter()
        old=limiter.total_tokens
        limiter.total_tokens=2
        active=peak=merge_active=merge_peak=router_peak=0
        lock=threading.Lock()
        def measured(name,result=None):
            def call(*a,**kw):
                nonlocal active,peak,merge_active,merge_peak,router_peak
                with lock:
                    active+=1;peak=max(peak,active)
                    if name=='merge':
                        merge_active+=1;merge_peak=max(merge_peak,merge_active)
                    else:
                        router_peak=max(router_peak,active-merge_active)
                try:
                    time.sleep(.01)
                    return result
                finally:
                    with lock:
                        active-=1
                        if name=='merge':merge_active-=1
            return call
        self.router._active=measured('active',[])
        self.router._save=measured('save')
        self.booking._merge_and_save_search=measured('merge',[])
        try:
            results=await asyncio.gather(*(self.route(self.body) for _ in range(12)))
        finally:
            limiter.total_tokens=old
        self.assertEqual(merge_peak,1)
        self.assertEqual(router_peak,2)
        self.assertLessEqual(peak,3)  # shared router pool (2) + dedicated serial writer (1)
        self.assertEqual(results,[{'data':{'hotels':[]}}]*12)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path);opts,rest=p.parse_known_args()
    if opts.source_root:ROOT=opts.source_root
    unittest.main(argv=[__file__,*rest],verbosity=2)
