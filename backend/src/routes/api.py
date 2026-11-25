from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select

from src.config.settings import ARTIFACTS
from src.constants.enums import Role
from src.controllers.query import delivery_status, jobs, recent_activity, require_row, revisions
from src.models.database import engine
from src.models.tables import datasets, runs, snapshots as snapshot_table
from src.schemas.requests import Chunk, Delivery, Declaration, Import, IntakeBatch, Login, Review, Run, UploadSession
from src.services.data import PROFILE, csv_records, save_revision
from src.services.domain import sample_rows
from src.services.intake import (
    active_snapshot_for_window,
    complete_upload_session,
    create_upload_session,
    get_snapshot,
    get_upload_session,
    list_windows,
    put_upload_part,
    submit_batch,
    switch_window,
    upsert_declaration,
    window_detail,
)
from src.services.intake_core import SOURCE_FIELDS, SOURCE_LABELS, canonical_source
from src.services.workflow import add_run, cancel_schedule, recompute_run, review_run, schedule_report
from src.utils.exports import write_csv
from src.utils.security import allowed, authenticate, signed_in

router = APIRouter()
analyst = allowed(Role.analyst.value)
reviewer = allowed(Role.reviewer.value)


@router.post('/login')
def login(body: Login):
    return authenticate(body.username, body.password)


@router.get('/me')
def current(account=Depends(signed_in)):
    return dict(account)


@router.get('/profile')
def profile():
    return PROFILE


def download_csv(data, name):
    return Response(data, media_type='text/csv; charset=utf-8',
                    headers={'content-disposition': "attachment; filename*=UTF-8''" + quote(name)})


@router.get('/example.csv')
def example(account=Depends(signed_in)):
    return download_csv(write_csv(sample_rows(), [c['key'] for c in PROFILE['columns']], False), PROFILE['filename'])


@router.get('/datasets')
def list_datasets(account=Depends(signed_in)):
    return revisions()


@router.get('/datasets/{key}')
def get_dataset(key: int, account=Depends(signed_in)):
    dataset = require_row(datasets, key, '数据版本')
    records = dataset.pop('records')
    with engine.connect() as connection:
        linked = connection.execute(
            select(snapshot_table).where(snapshot_table.c.dataset_id == key)
            .order_by(snapshot_table.c.is_active.desc(), snapshot_table.c.id.desc()).limit(1)
        ).mappings().one_or_none()
    extra = {}
    if linked is not None:
        extra = {
            'snapshot_id': linked['id'],
            'window_end': linked['window_end'],
            'quarantine': linked['quarantine'],
            'sample_count': linked['sample_count'],
            'quarantine_count': linked['quarantine_count'],
            'snapshot_is_active': bool(linked['is_active']),
        }
    return {**dataset, **extra, 'count': len(records), 'records': records[:100]}


@router.post('/datasets', status_code=201)
def import_data(body: Import, account=Depends(analyst),
                idempotency_key: str | None = Header(default=None, alias='Idempotency-Key')):
    # New three-source callers can use the familiar endpoint; legacy wide CSV stays supported.
    if body.source or body.expected_total is not None or body.expected_counts is not None or body.batch_uid:
        return submit_batch(body.model_dump(), account['username'], idempotency_key)
    rows = csv_records(body.csv)
    key, created = save_revision(body.name or PROFILE['filename'], rows, account['username'])
    return {'id': key, 'created': created, 'rows': len(rows)}


@router.get('/intake/sources')
def intake_sources(account=Depends(signed_in)):
    return [{'key': key, 'label': SOURCE_LABELS[key], 'fields': list(SOURCE_FIELDS[key])}
            for key in ('history', 'pressure', 'brake_load')]


@router.get('/intake/windows')
def intake_windows(account=Depends(signed_in)):
    return list_windows()


@router.post('/intake/declaration', status_code=201)
@router.post('/intake/declarations', status_code=201)
def create_declaration(body: Declaration, account=Depends(analyst)):
    if not body.window_end:
        raise HTTPException(422, '请填写盘点窗口 window_end。')
    return upsert_declaration(body.window_end, account['username'], body.expected_total,
                              body.expected_counts, body.reopen)


@router.get('/intake/windows/{window_end}')
def intake_window(window_end: str, account=Depends(signed_in)):
    return window_detail(window_end)


@router.post('/intake/batches', status_code=201)
@router.post('/intake/uploads', status_code=201)
@router.post('/intake/upload', status_code=201)
@router.post('/intake/source-uploads', status_code=201)
def create_batch(body: IntakeBatch, account=Depends(analyst), force: bool = False,
                 idempotency_key: str | None = Header(default=None, alias='Idempotency-Key')):
    data = body.model_dump()
    if force:
        data['force'] = True
    key = data.pop('idempotency_key', None) or idempotency_key
    return submit_batch(data, account['username'], key)


@router.post('/intake/resumable', status_code=201)
@router.post('/intake/upload-sessions', status_code=201)
def create_resumable(body: UploadSession, account=Depends(analyst)):
    return create_upload_session(body.model_dump(), account['username'])


@router.get('/intake/resumable/{upload_id}')
@router.get('/intake/upload-sessions/{upload_id}')
def read_resumable(upload_id: str, account=Depends(signed_in)):
    return get_upload_session(upload_id)


@router.put('/intake/resumable/{upload_id}/chunks/{chunk_index}')
@router.put('/intake/upload-sessions/{upload_id}/chunks/{chunk_index}')
def upload_chunk(upload_id: str, chunk_index: int, body: Chunk, account=Depends(analyst)):
    return put_upload_part(upload_id, chunk_index, body.chunk)


@router.post('/intake/resumable/{upload_id}/complete', status_code=201)
@router.post('/intake/upload-sessions/{upload_id}/complete', status_code=201)
def finish_resumable(upload_id: str, account=Depends(analyst)):
    return complete_upload_session(upload_id, account['username'])


@router.put('/intake/windows/{window_end}/declaration')
@router.post('/intake/windows/{window_end}/declaration')
def window_declaration(window_end: str, body: Declaration, account=Depends(analyst)):
    return upsert_declaration(body.window_end or window_end, account['username'], body.expected_total,
                              body.expected_counts, body.reopen)


@router.post('/intake/windows/{window_end}/switch', status_code=201)
@router.post('/intake/windows/{window_end}/complete', status_code=201)
@router.post('/intake/windows/{window_end}/activate', status_code=201)
@router.post('/intake/windows/{window_end}/publish', status_code=201)
@router.post('/windows/{window_end}/switch', status_code=201)
@router.post('/windows/{window_end}/complete', status_code=201)
@router.post('/windows/{window_end}/activate', status_code=201)
@router.post('/windows/{window_end}/publish', status_code=201)
def manual_switch(window_end: str, account=Depends(analyst), force: bool = True):
    return switch_window(window_end, account['username'], force=force)


@router.get('/intake/windows/{window_end}/samples')
def window_samples(window_end: str, account=Depends(signed_in)):
    snapshot = active_snapshot_for_window(window_end)
    return snapshot['samples']


@router.get('/intake/windows/{window_end}/quarantine')
def window_quarantine(window_end: str, account=Depends(signed_in)):
    snapshot = active_snapshot_for_window(window_end)
    return snapshot['quarantine']


@router.get('/quarantine')
@router.get('/intake/quarantine')
def quarantine(window_end: str | None = None, account=Depends(signed_in)):
    if window_end:
        snapshot = active_snapshot_for_window(window_end)
        return snapshot['quarantine']
    with engine.connect() as connection:
        rows = connection.execute(select(snapshot_table).where(snapshot_table.c.is_active == 1)).mappings().all()
        return [{'window_end': row['window_end'], 'snapshot_id': row['id'], 'quarantine': row['quarantine']}
                for row in rows]


@router.get('/intake/snapshots/{key}')
def intake_snapshot(key: int, account=Depends(signed_in)):
    return get_snapshot(key)


@router.get('/intake/examples/{source_name}')
def intake_example(source_name: str, account=Depends(signed_in)):
    source_key = canonical_source(source_name.removesuffix('.csv'))
    rows = sample_rows()
    if source_key == 'history':
        fields = ['tire_id', 'route', 'window_end', 'mileage_km', 'tire_age_days', 'tread_loss_mm']
        filename = 'tire-history-2026-10.csv'
    elif source_key == 'pressure':
        fields = ['tire_id', 'window_end', 'low_pressure_pct']
        filename = 'pressure-inspection-2026-10.csv'
    else:
        fields = ['tire_id', 'window_end', 'hard_brakes_per_1000km', 'route_load_pct']
        filename = 'brake-load-2026-10.csv'
    return download_csv(write_csv(rows, fields, False), filename)


# Short semantic aliases for integrations that name the bounded context “sources”.
@router.get('/sources')
def source_list(account=Depends(signed_in)):
    return intake_sources(account)


@router.post('/sources/{source_name}/batches', status_code=201)
@router.post('/sources/{source_name}/upload', status_code=201)
def source_batch(source_name: str, body: IntakeBatch, account=Depends(analyst),
                 idempotency_key: str | None = Header(default=None, alias='Idempotency-Key')):
    data = body.model_dump()
    data['source'] = source_name
    return submit_batch(data, account['username'], data.pop('idempotency_key', None) or idempotency_key)


@router.post('/sources/upload', status_code=201)
def source_upload(body: IntakeBatch, account=Depends(analyst),
                  idempotency_key: str | None = Header(default=None, alias='Idempotency-Key')):
    data = body.model_dump()
    return submit_batch(data, account['username'], data.pop('idempotency_key', None) or idempotency_key)


@router.get('/windows')
def windows_alias(account=Depends(signed_in)):
    return list_windows()


@router.get('/windows/{window_end}')
def window_alias(window_end: str, account=Depends(signed_in)):
    return window_detail(window_end)


@router.post('/runs/{key}/recompute', status_code=202)
@router.post('/runs/{key}/retry', status_code=202)
def recompute(key: int, account=Depends(analyst)):
    return recompute_run(key, account['username'])


@router.get('/runs')
def list_runs(account=Depends(signed_in)):
    return jobs()


@router.post('/runs', status_code=202)
def queue(body: Run, account=Depends(analyst)):
    return add_run(body, account['username'])


@router.get('/runs/{key}')
def result(key: int, account=Depends(signed_in)):
    return require_row(runs, key, '分析任务')


@router.post('/runs/{key}/review')
def review(key: int, body: Review, account=Depends(reviewer)):
    return review_run(key, body, account['username'])


@router.post('/runs/{key}/schedules', status_code=201)
def schedule(key: int, body: Delivery, account=Depends(reviewer)):
    return schedule_report(key, body, account['username'])


@router.get('/delivery')
def delivery(account=Depends(signed_in)):
    return delivery_status()


@router.delete('/schedules/{key}')
def stop_schedule(key: int, account=Depends(reviewer)):
    return cancel_schedule(key, account['username'])


@router.get('/audit')
def activity(account=Depends(signed_in)):
    return recent_activity()


@router.get('/runs/{key}/report.csv')
def report(key: int, account=Depends(signed_in)):
    run = require_row(runs, key, '分析任务')
    if run['decision'] != 'approved' and account['role'] == Role.viewer.value:
        raise HTTPException(403, '只读账号可导出已批准的报告。')
    if not run['result']:
        raise HTTPException(409, '分析结果尚不可导出。')
    path = ARTIFACTS / f"run-{key}-{run['started'].hex()}.csv"
    data = path.read_bytes() if path.exists() else write_csv(run['result']['rows'], run['result'].get('columns'))
    return download_csv(data, f"{PROFILE['title']}-{key}.csv")
