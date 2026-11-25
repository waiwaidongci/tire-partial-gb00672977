from src.models.database import cache

if not cache.get('worker:heartbeat'):
    raise SystemExit('Missing worker heartbeat')
