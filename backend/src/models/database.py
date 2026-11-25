from redis import Redis
from sqlalchemy import create_engine, insert, select

from src.config.settings import DATABASE_URL, REDIS_URL
from src.models.tables import audit

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
cache = Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2)


def fetch_one(connection, table, key):
    return connection.execute(select(table).where(table.c.id == key)).mappings().one_or_none()


def add_event(connection, actor, action, subject, at):
    connection.execute(insert(audit).values(actor=actor, action=action, subject=subject, at=at))
