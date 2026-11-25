import json

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from src.constants.enums import Role
from src.models.database import engine
from src.models.tables import datasets, users
from src.services.data import PROFILE, convert, save_revision
from src.services.domain import sample_rows
from src.utils.security import protect


def seed():
    for role in Role:
        try:
            with engine.begin() as connection:
                if not connection.scalar(select(users.c.username).where(users.c.username == role.value)):
                    connection.execute(insert(users).values(username=role.value, role=role.value,
                                                            password=protect(f'{role.value}-demo-24')))
        except IntegrityError:
            with engine.connect() as connection:
                if not connection.scalar(select(users.c.username).where(users.c.username == role.value)):
                    raise
    records = [{field['key']: convert(row[field['key']], field) for field in PROFILE['columns']} for row in sample_rows()]
    revision, created = save_revision(PROFILE['filename'], records, 'seed')
    with engine.connect() as connection:
        counts = {table.name: connection.scalar(select(func.count()).select_from(table)) for table in (users, datasets)}
    return {'revision': revision, 'created': created, **counts, 'rows': len(records)}


if __name__ == '__main__':
    print(json.dumps(seed(), ensure_ascii=False))
