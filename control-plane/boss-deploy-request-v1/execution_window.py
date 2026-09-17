"""Closed proof of timely start and bounded completion for migration DEPLOY."""
import datetime as dt
import hashlib
import json
import re

BUDGET_SECONDS=900
FIELDS={'schema','task_sha256','candidate_contract_sha256','claimed_at','started_at',
        'completed_at','elapsed_milliseconds','budget_seconds'}
SHA=re.compile(r'[0-9a-f]{64}\Z')

class Invalid(ValueError):
    pass

def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

def task_digest(task):
    return hashlib.sha256(canonical({k:v for k,v in task.items() if not k.startswith('_')})).hexdigest()

def stamp(value):
    try:
        when=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        if when.tzinfo is None: raise ValueError()
        return when
    except (AttributeError,ValueError,TypeError) as exc: raise Invalid('execution_window_time') from exc

def applies(task):
    return (task.get('action_id')=='HK_STAGING_DEPLOY'
            and 'candidate_contract_sha256' in task.get('parameters',{}))

def validate(task,evidence):
    if not applies(task): raise Invalid('execution_window_scope')
    proof=evidence.get('execution_window')
    if not isinstance(proof,dict) or set(proof)!=FIELDS or proof['schema']!='go.hk-execution-window.v1':
        raise Invalid('execution_window_missing')
    identity=task['parameters']['candidate_contract_sha256']
    if (not isinstance(identity,str) or not SHA.fullmatch(identity)
        or proof['candidate_contract_sha256']!=identity
        or evidence.get('candidate_contract_sha256')!=identity
        or proof['task_sha256']!=task_digest(task)):
        raise Invalid('execution_window_binding')
    if type(proof['budget_seconds']) is not int or proof['budget_seconds']!=BUDGET_SECONDS:
        raise Invalid('execution_window_budget')
    elapsed=proof['elapsed_milliseconds']
    if type(elapsed) is not int or not 0<=elapsed<=BUDGET_SECONDS*1000:
        raise Invalid('execution_window_elapsed')
    issued,expires=stamp(task.get('issued_at')),stamp(task.get('expires_at'))
    claimed,started,completed=(stamp(proof[k]) for k in ('claimed_at','started_at','completed_at'))
    if not issued<=claimed<=started<expires or completed<started:
        raise Invalid('execution_window_late_start')
    if proof['started_at']!=evidence.get('started_at') or proof['completed_at']!=evidence.get('completed_at'):
        raise Invalid('execution_window_evidence_time')
    wall_ms=(completed-started).total_seconds()*1000
    if wall_ms>BUDGET_SECONDS*1000 or abs(wall_ms-elapsed)>2000:
        raise Invalid('execution_window_clock_or_budget')
    return proof
