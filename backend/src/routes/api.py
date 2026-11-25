from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response

from src.config.settings import ARTIFACTS
from src.constants.enums import Role
from src.controllers.query import delivery_status, jobs, recent_activity, require_row, revisions
from src.models.tables import datasets, runs
from src.schemas.requests import Delivery, Import, Login, Review, Run
from src.services.data import PROFILE, csv_records, save_revision
from src.services.domain import sample_rows
from src.services.workflow import add_run, cancel_schedule, review_run, schedule_report
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
    return {**dataset, 'count': len(records), 'records': records[:100]}


@router.post('/datasets', status_code=201)
def import_data(body: Import, account=Depends(analyst)):
    rows = csv_records(body.csv)
    key, created = save_revision(body.name, rows, account['username'])
    return {'id': key, 'created': created, 'rows': len(rows)}


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
