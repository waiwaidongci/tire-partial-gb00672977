from sqlalchemy import JSON, Column, Double, Integer, MetaData, String, Table, Text, UniqueConstraint

metadata = MetaData()
users = Table('workspace_users', metadata, Column('username', String(40), primary_key=True),
              Column('role', String(20), nullable=False), Column('password', String(160), nullable=False))
datasets = Table('data_revisions', metadata, Column('id', Integer, primary_key=True),
                 Column('name', String(180), nullable=False), Column('checksum', String(64), nullable=False, unique=True),
                 Column('records', JSON, nullable=False), Column('owner', String(40), nullable=False),
                 Column('created', Double, nullable=False))
runs = Table('analysis_runs', metadata, Column('id', Integer, primary_key=True),
             Column('dataset_id', Integer, nullable=False, index=True), Column('snapshot_id', Integer, index=True),
             Column('options', JSON, nullable=False),
             Column('state', String(16), nullable=False, index=True), Column('owner', String(40), nullable=False),
             Column('created', Double, nullable=False), Column('started', Double), Column('finished', Double),
             Column('result', JSON), Column('error', Text), Column('decision', String(16)),
             Column('reviewer', String(40)), Column('review_note', Text), Column('reviewed', Double))
schedules = Table('report_schedules', metadata, Column('id', Integer, primary_key=True),
                  Column('run_id', Integer, nullable=False), Column('recipient', String(100), nullable=False),
                  Column('cadence', String(16), nullable=False), Column('next_at', Double, nullable=False, index=True),
                  Column('active', Integer, nullable=False), Column('owner', String(40), nullable=False))
deliveries = Table('report_deliveries', metadata, Column('id', Integer, primary_key=True),
                   Column('schedule_id', Integer, nullable=False), Column('run_id', Integer, nullable=False),
                   Column('recipient', String(100), nullable=False), Column('scheduled', Double, nullable=False),
                   Column('delivered', Double, nullable=False), UniqueConstraint('schedule_id', 'scheduled'))
audit = Table('operation_audit', metadata, Column('id', Integer, primary_key=True),
              Column('at', Double, nullable=False), Column('actor', String(40), nullable=False),
              Column('action', String(30), nullable=False), Column('subject', Integer, nullable=False))

# Three-source month-end intake. Raw observations stay immutable; a window snapshot
# is the atomic switch unit containing both joined samples and quarantine reasons.
declarations = Table('intake_declarations', metadata,
                     Column('window_end', String(10), primary_key=True),
                     Column('round_no', Integer, nullable=False, default=1),
                     Column('expected_total', Integer),
                     Column('expected_counts', JSON, nullable=False),
                     Column('status', String(20), nullable=False, default='collecting'),
                     Column('snapshot_id', Integer),
                     Column('owner', String(40), nullable=False),
                     Column('created', Double, nullable=False), Column('updated', Double, nullable=False))
batches = Table('intake_batches', metadata, Column('id', Integer, primary_key=True),
                Column('batch_uid', String(120), nullable=False),
                Column('window_end', String(10), nullable=False, index=True),
                Column('source', String(20), nullable=False, index=True),
                Column('version_label', String(80)), Column('filename', String(220)),
                Column('checksum', String(64), nullable=False, index=True),
                Column('declared_count', Integer), Column('row_count', Integer, nullable=False),
                Column('accepted_count', Integer, nullable=False, default=0),
                Column('stale_count', Integer, nullable=False, default=0),
                Column('status', String(20), nullable=False, default='accepted'),
                Column('detail', JSON), Column('owner', String(40), nullable=False),
                Column('created', Double, nullable=False),
                UniqueConstraint('window_end', 'source', 'batch_uid', name='uq_intake_batch_uid'))
observations = Table('intake_observations', metadata, Column('id', Integer, primary_key=True),
                     Column('batch_id', Integer, nullable=False, index=True),
                     Column('window_end', String(10), nullable=False, index=True),
                     Column('source', String(20), nullable=False, index=True),
                     Column('tire_id', String(80), nullable=False, index=True),
                     Column('version_label', String(80)), Column('version_key', String(500), nullable=False),
                     Column('fingerprint', String(64), nullable=False),
                     Column('raw_payload', JSON, nullable=False), Column('payload', JSON, nullable=False),
                     Column('issues', JSON, nullable=False), Column('valid', Integer, nullable=False),
                     Column('owner', String(40), nullable=False), Column('created', Double, nullable=False))
snapshots = Table('window_snapshots', metadata, Column('id', Integer, primary_key=True),
                  Column('window_end', String(10), nullable=False, index=True),
                  Column('revision', Integer, nullable=False), Column('dataset_id', Integer),
                  Column('sample_count', Integer, nullable=False),
                  Column('quarantine_count', Integer, nullable=False),
                  Column('samples', JSON, nullable=False), Column('quarantine', JSON, nullable=False),
                  Column('stats', JSON, nullable=False), Column('checksum', String(64), nullable=False),
                  Column('is_active', Integer, nullable=False, index=True),
                  Column('owner', String(40), nullable=False),
                  Column('created', Double, nullable=False), Column('switched_at', Double, nullable=False),
                  UniqueConstraint('window_end', 'revision', name='uq_window_revision'))
upload_sessions = Table('intake_upload_sessions', metadata,
                        Column('id', Integer, primary_key=True),
                        Column('upload_id', String(120), nullable=False, unique=True, index=True),
                        Column('window_end', String(10), index=True), Column('source', String(20)),
                        Column('version_label', String(80)), Column('filename', String(220)),
                        Column('chunk_total', Integer), Column('options', JSON, nullable=False),
                        Column('status', String(20), nullable=False, default='uploading'),
                        Column('batch_id', Integer), Column('owner', String(40), nullable=False),
                        Column('created', Double, nullable=False), Column('updated', Double, nullable=False))
upload_parts = Table('intake_upload_parts', metadata, Column('id', Integer, primary_key=True),
                     Column('upload_id', String(120), nullable=False, index=True),
                     Column('chunk_index', Integer, nullable=False), Column('content', Text, nullable=False),
                     Column('checksum', String(64), nullable=False), Column('created', Double, nullable=False),
                     UniqueConstraint('upload_id', 'chunk_index', name='uq_upload_part'))
