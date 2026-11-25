from redis import Redis
from sqlalchemy import create_engine, insert, inspect, select, text

from src.config.settings import DATABASE_URL, REDIS_URL
from src.models.tables import audit

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
cache = Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2)


def fetch_one(connection, table, key):
    return connection.execute(select(table).where(table.c.id == key)).mappings().one_or_none()


def add_event(connection, actor, action, subject, at):
    connection.execute(insert(audit).values(actor=actor, action=action, subject=subject, at=at))


def ensure_schema():
    """Add columns introduced after the initial snapshot without requiring a MySQL volume reset."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if 'analysis_runs' in tables:
        columns = {column['name'] for column in inspector.get_columns('analysis_runs')}
        if 'snapshot_id' not in columns:
            with engine.begin() as connection:
                connection.execute(text('ALTER TABLE analysis_runs ADD COLUMN snapshot_id INTEGER'))
                connection.execute(text('CREATE INDEX ix_analysis_runs_snapshot_id ON analysis_runs (snapshot_id)'))
