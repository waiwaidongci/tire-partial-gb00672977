from enum import Enum


class Role(str, Enum):
    analyst = 'analyst'
    reviewer = 'reviewer'
    viewer = 'viewer'


class State(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
