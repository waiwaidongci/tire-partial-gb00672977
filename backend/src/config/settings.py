import os
from pathlib import Path

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:////tmp/batch-analysis.db')
REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
SECRET = os.environ.get('JWT_SECRET', 'only-for-local-development-rotate-before-deployment')
ARTIFACTS = Path(os.environ.get('ARTIFACTS_DIR', '/artifacts'))
SEED = os.environ.get('SEED_DEMO', 'true').lower() == 'true'
