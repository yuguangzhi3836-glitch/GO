"""Admin-authenticated queue controls for the reviewed 14-cell observation set."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from go_hotel.autonomy.durable import ExecutionError
from go_hotel.autonomy.operations import application_executor
from go_hotel.security.deps import current_principal
from go_hotel.security.service import Principal


router = APIRouter(prefix='/internal/v1/autonomy', tags=['autonomy-execution'])


def reader(response: Response, p: Principal = Depends(current_principal)):
    if p.actor_type != 'GO_ADMIN' or 'admin:read' not in p.permissions:
        raise HTTPException(403, 'AUTONOMY_ADMIN_READ_REQUIRED')
    response.headers['Cache-Control'] = 'no-store, private'
    return p


def operator(p: Principal = Depends(reader)):
    if 'admin:rules' not in p.permissions:
        raise HTTPException(403, 'AUTONOMY_ADMIN_RULES_REQUIRED')
    return p


def invoke(fn, *args, **kwargs):
    try:
        return {'data': fn(*args, **kwargs)}
    except ExecutionError as exc:
        raise HTTPException(404 if str(exc) == 'TASK_NOT_FOUND' else 409, str(exc)) from exc


class ObserveBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160)
    cell_ids: list[str] = Field(min_length=1, max_length=14)


class PauseBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    paused: bool
    expected_version: int = Field(ge=1)


@router.get('/cells')
def cells(p: Principal = Depends(reader)):
    return invoke(application_executor().cells)


@router.get('/tasks')
def tasks(cell_id: str | None = None, limit: int = Query(default=100, ge=1, le=200), p: Principal = Depends(reader)):
    return invoke(application_executor().list_tasks, cell_id=cell_id, limit=limit)


@router.get('/tasks/{task_id}')
def task(task_id: str, p: Principal = Depends(reader)):
    return invoke(application_executor().inspect, task_id)


@router.post('/observe')
def observe(body: ObserveBody, p: Principal = Depends(operator)):
    runtime = application_executor()
    if len(set(body.cell_ids)) != len(body.cell_ids) or any(c + '.OPERATIONS_OBSERVE' not in runtime.handlers for c in body.cell_ids):
        raise HTTPException(422, 'DISTINCT_KNOWN_CELLS_REQUIRED')
    # A disconnected client repeats the same cycle key. Previously enqueued
    # cells keep their IDs; the remaining cells are added without duplication.
    return invoke(lambda: [runtime.submit(c + '.OPERATIONS_OBSERVE', idempotency_key=body.idempotency_key,
                                         submitted_by=p.user_id) for c in body.cell_ids])


@router.post('/cells/{cell_id}/control')
def control(cell_id: str, body: PauseBody, p: Principal = Depends(operator)):
    runtime = application_executor()
    if cell_id + '.OPERATIONS_OBSERVE' not in runtime.handlers:
        raise HTTPException(404, 'CELL_NOT_FOUND')
    return invoke(runtime.set_paused, cell_id, paused=body.paused, actor=p.user_id, expected_version=body.expected_version)


@router.post('/tasks/{task_id}/resume')
def resume(task_id: str, p: Principal = Depends(operator)):
    return invoke(application_executor().resume, task_id, actor=p.user_id)


@router.post('/tasks/{task_id}/cancel')
def cancel(task_id: str, p: Principal = Depends(operator)):
    return invoke(application_executor().cancel, task_id, actor=p.user_id)
