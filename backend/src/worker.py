import json
import logging
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

from src.config.settings import ARTIFACTS
from src.models.database import cache
from src.services.domain import compute
from src.services.workflow import claim_run, finish_run, publish_due
from src.utils.exports import write_csv


def calculate(job):
    key, claim, rows, options = job
    try:
        report = compute(rows, options)
        report['columns'] = list(dict.fromkeys(key for row in report['rows'] for key in row))
        report['metric_order'] = list(report['metrics'])
        json.dumps(report, allow_nan=False)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=ARTIFACTS, delete=False) as temporary:
            temporary.write(write_csv(report['rows'], report['columns']))
        Path(temporary.name).replace(ARTIFACTS / f'run-{key}-{claim.hex()}.csv')
    except ValueError as error:
        finish_run(key, claim, None, str(error))
    except Exception:
        logging.exception('Analysis %s failed', key)
        finish_run(key, claim, None, '计算失败，请核对数据并重新提交。')
    else:
        finish_run(key, claim, report, None)


def work():
    while True:
        try:
            job = claim_run()
            if job:
                calculate(job)
            publish_due()
            cache.set('worker:heartbeat', str(time.time()), ex=25)
        except Exception:
            logging.exception('Worker iteration failed')
        time.sleep(0.8)


if __name__ == '__main__':
    work()
