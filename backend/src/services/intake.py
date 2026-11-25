"""Transactional three-source intake and atomic window switching."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import insert, select, update

from src.models.database import add_event, engine
from src.models.tables import (
    batches,
    declarations,
    datasets,
    observations,
    snapshots,
    upload_parts,
    upload_sessions,
)
from src.services.intake_core import (
    SOURCE_ORDER,
    SOURCE_LABELS,
    build_snapshot,
    canonical_source,
    content_fingerprint,
    normalize_expected_counts,
    parse_source_csv,
    source_progress,
    version_key,
)


def _now() -> float:
    return time.time()


def _first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != '':
            return value
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 'final', 'commit'}


def _jsonable(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _declaration_view(row: dict[str, Any] | None, progress: dict[str, dict[str, int]] | None = None) -> dict[str, Any] | None:
    if row is None:
        return None
    expected = row['expected_counts'] or {}
    progress = progress or {}
    counts = {source: int(progress.get(source, {}).get('received', 0)) for source in SOURCE_ORDER}
    tire_counts = {source: int(progress.get(source, {}).get('tire_count', 0)) for source in SOURCE_ORDER}
    sources = {}
    complete = row['status'] == 'switched'
    for source in SOURCE_ORDER:
        wanted = expected.get(source)
        got = counts[source]
        source_complete = wanted is not None and got == wanted
        if row['status'] != 'switched' and not source_complete:
            complete = False
        sources[source] = {
            'key': source,
            'label': SOURCE_LABELS[source],
            'expected': wanted,
            'received': got,
            'record_count': got,
            'tire_count': tire_counts[source],
            'complete': row['status'] == 'switched' or source_complete,
            'difference': None if wanted is None else got - wanted,
        }
    return {
        'window_end': row['window_end'],
        'round': row['round_no'],
        'expected_total': row['expected_total'],
        'expected_counts': expected,
        'status': row['status'],
        'snapshot_id': row['snapshot_id'],
        'owner': row['owner'],
        'created': row['created'],
        'updated': row['updated'],
        'received_counts': counts,
        'sources': sources,
        'complete': complete,
    }


def _active_snapshot(connection, window_end: str) -> dict[str, Any] | None:
    row = connection.execute(
        select(snapshots).where(snapshots.c.window_end == window_end, snapshots.c.is_active == 1)
        .order_by(snapshots.c.id.desc()).limit(1)
    ).mappings().one_or_none()
    return _jsonable(row) if row else None


def _observations(connection, window_end: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        select(observations).where(observations.c.window_end == window_end).order_by(observations.c.id)
    ).mappings().all()
    return [dict(row) for row in rows]


def _batch_view(row: dict[str, Any]) -> dict[str, Any]:
    data = _jsonable(row)
    data['source_label'] = SOURCE_LABELS.get(data.get('source'), data.get('source'))
    data['ignored_count'] = data.get('stale_count', 0)
    data['is_stale'] = bool(data.get('stale_count'))
    return data


def _window_detail_connection(connection, window_end: str, include_candidate: bool = True) -> dict[str, Any]:
    declaration_row = connection.execute(
        select(declarations).where(declarations.c.window_end == window_end)
    ).mappings().one_or_none()
    obs = _observations(connection, window_end)
    progress = source_progress(obs)
    declaration = _declaration_view(dict(declaration_row) if declaration_row else None, progress)
    batch_rows = connection.execute(
        select(batches).where(batches.c.window_end == window_end).order_by(batches.c.id.desc()).limit(100)
    ).mappings().all()
    snapshot_rows = connection.execute(
        select(snapshots.c.id, snapshots.c.window_end, snapshots.c.revision, snapshots.c.dataset_id,
               snapshots.c.sample_count, snapshots.c.quarantine_count, snapshots.c.stats,
               snapshots.c.checksum, snapshots.c.is_active, snapshots.c.owner,
               snapshots.c.created, snapshots.c.switched_at)
        .where(snapshots.c.window_end == window_end).order_by(snapshots.c.id.desc()).limit(30)
    ).mappings().all()
    active = _active_snapshot(connection, window_end)
    candidate = None
    if include_candidate and declaration and declaration['status'] == 'collecting':
        candidate = build_snapshot(window_end, obs, declaration['expected_counts'])
    return {
        'window_end': window_end,
        'declaration': declaration,
        'sources': list((declaration or {}).get('sources', {}).values()) or [
            {'key': source, 'label': SOURCE_LABELS[source],
             'received': progress[source]['received'], 'record_count': progress[source]['received'],
             'tire_count': progress[source]['tire_count'], 'expected': None, 'complete': False}
            for source in SOURCE_ORDER
        ],
        'received_counts': {source: progress[source]['received'] for source in SOURCE_ORDER},
        'tire_counts': {source: progress[source]['tire_count'] for source in SOURCE_ORDER},
        'batches': [_batch_view(dict(row)) for row in batch_rows],
        'snapshots': [dict(row) for row in snapshot_rows],
        'active_snapshot': active,
        'candidate': candidate,
    }


def window_detail(window_end: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return _window_detail_connection(connection, window_end)


def list_windows() -> list[dict[str, Any]]:
    with engine.connect() as connection:
        window_ids = set(connection.execute(select(declarations.c.window_end)).scalars())
        window_ids.update(connection.execute(select(batches.c.window_end).distinct()).scalars())
        window_ids.update(connection.execute(select(snapshots.c.window_end).distinct()).scalars())
        details = [_window_detail_connection(connection, window, include_candidate=False) for window in window_ids]
    details.sort(key=lambda item: item['window_end'], reverse=True)
    return details


def upsert_declaration(window_end: str, actor: str, expected_total: int | None = 60,
                       expected_counts: dict[str, int] | None = None, reopen: bool = False) -> dict[str, Any]:
    counts = normalize_expected_counts(expected_total, expected_counts)
    missing = [source for source, value in counts.items() if value is None]
    if missing and expected_counts is None and expected_total is None:
        raise ValueError('请填写申报总条数，或分来源填写申报条数。')
    now = _now()
    with engine.begin() as connection:
        row = connection.execute(select(declarations).where(declarations.c.window_end == window_end)
                                 ).mappings().one_or_none()
        if row is None:
            connection.execute(insert(declarations).values(
                window_end=window_end, round_no=1, expected_total=expected_total,
                expected_counts=counts, status='collecting', owner=actor, created=now, updated=now))
            add_event(connection, actor, 'declare', 0, now)
        else:
            next_round = int(row['round_no']) + 1 if reopen or row['status'] == 'switched' else int(row['round_no'])
            status = 'collecting' if reopen or row['status'] == 'collecting' else 'switched'
            # An explicit new declaration after a switch starts a correction round.
            if row['status'] == 'switched' and (reopen or expected_total is not None or expected_counts is not None):
                status = 'collecting'
            connection.execute(update(declarations).where(declarations.c.window_end == window_end).values(
                round_no=next_round, expected_total=expected_total, expected_counts=counts,
                status=status, updated=now))
        detail = _window_detail_connection(connection, window_end)
    return detail


def _publish_if_complete(connection, declaration_row: dict[str, Any], actor: str, now: float,
                          force: bool = False) -> dict[str, Any] | None:
    window_end = declaration_row['window_end']
    if declaration_row['status'] == 'switched' and not force:
        snapshot = _active_snapshot(connection, window_end)
        return {'switched': False, 'reason': 'already_switched', 'snapshot': snapshot}

    obs = _observations(connection, window_end)
    built = build_snapshot(window_end, obs, declaration_row['expected_counts'])
    if not force and not built['stats']['complete']:
        return {'switched': False, 'reason': 'waiting_for_declared_count', 'progress': built['stats']}

    checksum = content_fingerprint(built['samples'])
    dataset_id = connection.scalar(select(datasets.c.id).where(datasets.c.checksum == checksum))
    if dataset_id is None:
        dataset_id = connection.execute(insert(datasets).values(
            name=f'三源合窗 {window_end} 第{declaration_row["round_no"]}批',
            checksum=checksum, records=built['samples'], owner=actor, created=now
        )).inserted_primary_key[0]

    revision = int(connection.scalar(
        select(snapshots.c.revision).where(snapshots.c.window_end == window_end)
        .order_by(snapshots.c.revision.desc()).limit(1)
    ) or 0) + 1
    connection.execute(update(snapshots).where(
        snapshots.c.window_end == window_end, snapshots.c.is_active == 1).values(is_active=0))
    snapshot_id = connection.execute(insert(snapshots).values(
        window_end=window_end, revision=revision, dataset_id=dataset_id,
        sample_count=len(built['samples']), quarantine_count=len(built['quarantine']),
        samples=built['samples'], quarantine=built['quarantine'], stats=built['stats'],
        checksum=checksum, is_active=1, owner=actor, created=now, switched_at=now
    )).inserted_primary_key[0]
    connection.execute(update(declarations).where(declarations.c.window_end == window_end).values(
        status='switched', snapshot_id=snapshot_id, updated=now))
    add_event(connection, actor, 'switch', snapshot_id, now)
    snapshot = connection.execute(select(snapshots).where(snapshots.c.id == snapshot_id)).mappings().one()
    return {'switched': True, 'snapshot': dict(snapshot), 'dataset_id': dataset_id, 'progress': built['stats']}


def switch_window(window_end: str, actor: str, force: bool = True) -> dict[str, Any]:
    now = _now()
    with engine.begin() as connection:
        row = connection.execute(select(declarations).where(
            declarations.c.window_end == window_end).with_for_update()).mappings().one_or_none()
        if row is None:
            counts = normalize_expected_counts(None, {})
            connection.execute(insert(declarations).values(
                window_end=window_end, round_no=1, expected_total=None, expected_counts=counts,
                status='collecting', owner=actor, created=now, updated=now))
            row = connection.execute(select(declarations).where(
                declarations.c.window_end == window_end)).mappings().one()
        result = _publish_if_complete(connection, dict(row), actor, now, force=force)
        detail = _window_detail_connection(connection, window_end)
    return {'window': detail, **(result or {})}


def submit_batch(payload: dict[str, Any], actor: str, idempotency_key: str | None = None) -> dict[str, Any]:
    """Validate, idempotently stage one batch and atomically switch when complete."""
    payload = dict(payload)
    if not payload.get('source'):
        payload['source'] = _first_value(payload, 'source_type', 'sourceType', 'type', 'kind')
    if not payload.get('window_end'):
        payload['window_end'] = _first_value(payload, 'window', 'windowEnd', 'window_end_date', 'date')
    csv_text = _first_value(payload, 'csv', 'csv_text', 'content', 'text')
    rows = payload.get('rows') or payload.get('records')
    if isinstance(csv_text, list) and rows is None:
        rows = csv_text
        csv_text = None
    if csv_text is None and rows is not None:
        # JSON callers may provide already-structured rows; encode as CSV through DictWriter
        # is unnecessary because parse function can accept list via a small adapter below.
        parsed = _parse_rows_payload(rows, payload.get('source'), payload.get('window_end'), payload.get('version'))
    else:
        parsed = parse_source_csv(csv_text or '', payload.get('source'),
                                  payload.get('window_end'), payload.get('version'))
    source = parsed['source']
    window_end = payload.get('window_end') or parsed['window_end']
    if window_end != parsed['window_end']:
        raise ValueError('申报窗口与 CSV 内 window_end 不一致。')

    batch_uid = (payload.get('batch_uid') or payload.get('upload_id') or payload.get('client_token')
                 or payload.get('resume_token') or payload.get('request_id')
                 or idempotency_key or f'auto-{uuid4().hex}')
    filename = (payload.get('filename') or f'{SOURCE_LABELS[source]}-{window_end}.csv')[:220]
    version_label = payload.get('version')
    if version_label is not None:
        version_label = str(version_label)[:80]
    row_version_keys = {row['version_key'] for row in parsed['rows']}
    if version_label is None:
        row_version_labels = {row['version_label'] for row in parsed['rows'] if row.get('version_label')}
        if len(row_version_labels) == 1:
            version_label = str(next(iter(row_version_labels)))[:80]
    batch_group_key = next(iter(row_version_keys)) if len(row_version_keys) == 1 else version_key(version_label)
    checksum = content_fingerprint({'source': source, 'window': window_end, 'rows': parsed['rows']})
    expected_total = _first_value(
        payload, 'expected_total', 'expected_count', 'expected_rows', 'total_count',
        'total_rows', 'declared_total', 'declared_rows')
    declared_count = _first_value(payload, 'declared_count', 'count')
    if declared_count is None and payload.get('declare_received_rows'):
        declared_count = len(parsed['rows'])
    if expected_total is None and declared_count is not None and int(declared_count) != len(parsed['rows']):
        # A declared total that differs from this batch's row count describes the whole source/window.
        expected_total = declared_count
    batch_level_declared = declared_count is not None and int(declared_count) == len(parsed['rows'])
    now = _now()

    with engine.begin() as connection:
        existing = connection.execute(select(batches).where(
            batches.c.window_end == window_end, batches.c.source == source,
            batches.c.batch_uid == str(batch_uid)
        )).mappings().one_or_none()
        duplicate_reason = 'batch_uid'
        if existing is None:
            existing = connection.execute(select(batches).where(
                batches.c.window_end == window_end, batches.c.source == source,
                batches.c.checksum == checksum
            ).order_by(batches.c.id.desc()).limit(1)).mappings().one_or_none()
            duplicate_reason = 'checksum'
        if existing is not None:
            detail = _window_detail_connection(connection, window_end)
            return {
                'id': existing['id'], 'batch_uid': existing['batch_uid'], 'duplicate': True,
                'duplicate_reason': duplicate_reason, 'switched': False,
                'window': detail, 'snapshot': detail['active_snapshot'],
            }

        expected_counts = payload.get('expected_counts')
        has_explicit_declaration = expected_total is not None or expected_counts is not None
        declaration = connection.execute(select(declarations).where(
            declarations.c.window_end == window_end)).mappings().one_or_none()
        if declaration is None and (has_explicit_declaration or batch_level_declared):
            if has_explicit_declaration:
                counts = normalize_expected_counts(
                    int(expected_total) if expected_total is not None else None, expected_counts)
            else:
                counts = normalize_expected_counts(None, {source: int(declared_count)})
            connection.execute(insert(declarations).values(
                window_end=window_end, round_no=1,
                expected_total=int(expected_total) if expected_total is not None else None,
                expected_counts=counts, status='collecting', owner=actor, created=now, updated=now))
            declaration = connection.execute(select(declarations).where(
                declarations.c.window_end == window_end)).mappings().one()
        elif declaration is not None and declaration['status'] == 'collecting' and has_explicit_declaration:
            counts = normalize_expected_counts(
                int(expected_total) if expected_total is not None else declaration['expected_total'],
                expected_counts or declaration['expected_counts'])
            connection.execute(update(declarations).where(declarations.c.window_end == window_end).values(
                expected_counts=counts,
                expected_total=int(expected_total) if expected_total is not None else declaration['expected_total'],
                updated=now))
            declaration = connection.execute(select(declarations).where(
                declarations.c.window_end == window_end)).mappings().one()

        existing_facts = {
            (tire_id, version_key_value, fingerprint)
            for tire_id, version_key_value, fingerprint in connection.execute(
                select(observations.c.tire_id, observations.c.version_key, observations.c.fingerprint).where(
                    observations.c.window_end == window_end, observations.c.source == source)
            ).all()
        }
        seen_facts: set[tuple[str, str, str]] = set()
        new_rows: list[dict[str, Any]] = []
        duplicate_fact_count = 0
        auto_declared_rows = payload.get('declare_received_rows') and _first_value(
            payload, 'declared_count', 'count') is None
        for row in parsed['rows']:
            row_version_label = row['version_label'] or version_label
            row_version_key = row['version_key']
            fact_key = (row['tire_id'], row_version_key, row['fingerprint'])
            if fact_key in existing_facts or fact_key in seen_facts:
                duplicate_fact_count += 1
                continue
            seen_facts.add(fact_key)
            row['_version_label'] = row_version_label
            row['_version_key'] = row_version_key
            new_rows.append(row)

        if auto_declared_rows:
            # Exact repeated facts are idempotent and should not hold the declared
            # current batch open; genuine same-version conflicts have distinct fingerprints.
            declared_count = len(new_rows)

        batch_id = connection.execute(insert(batches).values(
            batch_uid=str(batch_uid)[:120], window_end=window_end, source=source,
            version_label=version_label, filename=filename, checksum=checksum,
            declared_count=int(declared_count) if declared_count is not None else None,
            row_count=len(parsed['rows']), accepted_count=len(new_rows), stale_count=0,
            status='accepted', detail={'content_checksum': checksum, 'batch_version_key': batch_group_key,
                                       'duplicate_fact_count': duplicate_fact_count},
            owner=actor, created=now
        )).inserted_primary_key[0]

        for row in new_rows:
            connection.execute(insert(observations).values(
                batch_id=batch_id, window_end=window_end, source=source, tire_id=row['tire_id'],
                version_label=row['_version_label'], version_key=row['_version_key'],
                fingerprint=row['fingerprint'], raw_payload=row['raw_payload'], payload=row['payload'],
                issues=row['issues'], valid=1 if row['valid'] else 0, owner=actor, created=now))

        stale_count = 0
        all_source_obs = _observations(connection, window_end)
        source_obs = [item for item in all_source_obs if item['source'] == source]
        latest_keys: dict[str, str] = {}
        for item in source_obs:
            current = latest_keys.get(item['tire_id'])
            if current is None or item['version_key'] > current:
                latest_keys[item['tire_id']] = item['version_key']
        inserted_fact_keys = {(row['tire_id'], row['_version_key'], row['fingerprint']) for row in new_rows}
        for item in source_obs:
            fact_key = (item['tire_id'], item['version_key'], item['fingerprint'])
            if fact_key in inserted_fact_keys and item['version_key'] < latest_keys[item['tire_id']]:
                stale_count += 1
        if stale_count:
            connection.execute(update(batches).where(batches.c.id == batch_id).values(stale_count=stale_count))
        add_event(connection, actor, 'import', batch_id, now)

        if (declaration is not None and batch_level_declared and not has_explicit_declaration
                and declaration['status'] == 'collecting' and declaration['expected_total'] is None):
            source_batches = connection.execute(select(
                batches.c.version_label, batches.c.declared_count, batches.c.detail
            ).where(batches.c.window_end == window_end, batches.c.source == source)).mappings().all()
            groups: dict[str, int] = {}
            for item in source_batches:
                detail = item['detail'] or {}
                group_key = detail.get('batch_version_key') or version_key(item['version_label'])
                if item['declared_count'] is not None:
                    groups[group_key] = groups.get(group_key, 0) + int(item['declared_count'])
            if groups:
                latest_group = max(groups)
                counts = dict(declaration['expected_counts'] or {})
                # A full newer version replaces the older generation's declaration;
                # split batches belonging to the same version still add together.
                counts[source] = groups[latest_group]
                connection.execute(update(declarations).where(
                    declarations.c.window_end == window_end).values(expected_counts=counts, updated=now))

        force_requested = any(_truthy(payload.get(key)) for key in (
            'force', 'final', 'is_final', 'final_batch', 'last_batch', 'complete', 'commit', 'publish', 'switch_now'))
        if declaration is None and force_requested:
            counts = normalize_expected_counts(None, {})
            connection.execute(insert(declarations).values(
                window_end=window_end, round_no=1, expected_total=None, expected_counts=counts,
                status='collecting', owner=actor, created=now, updated=now))
            declaration = connection.execute(select(declarations).where(
                declarations.c.window_end == window_end)).mappings().one()

        switch_result = None
        if declaration is not None:
            declaration = connection.execute(select(declarations).where(
                declarations.c.window_end == window_end).with_for_update()).mappings().one()
            switch_result = _publish_if_complete(connection, dict(declaration), actor, now)
            if not switch_result.get('switched') and force_requested:
                current = source_progress(_observations(connection, window_end))
                all_sources_present = all(current[item]['tire_count'] > 0 for item in SOURCE_ORDER)
                if all_sources_present:
                    switch_result = _publish_if_complete(connection, dict(declaration), actor, now, force=True)
        detail = _window_detail_connection(connection, window_end)

    return {
        'id': batch_id,
        'batch_uid': str(batch_uid)[:120],
        'duplicate': False,
        'rows': len(parsed['rows']),
        'accepted_count': len(new_rows),
        'duplicate_fact_count': duplicate_fact_count,
        'stale_count': stale_count,
        'ignored_count': stale_count,
        'is_stale': bool(stale_count),
        'switched': bool(switch_result and switch_result.get('switched')),
        'switch': switch_result,
        'snapshot': (switch_result or {}).get('snapshot') if switch_result and switch_result.get('switched') else detail['active_snapshot'],
        'window': detail,
    }


def _parse_rows_payload(rows: list[dict[str, Any]], source: str | None,
                        window_end: str | None, version: Any) -> dict[str, Any]:
    """Adapt JSON row callers to the same validation path as CSV uploads."""
    from src.utils.exports import write_csv
    if not isinstance(rows, list) or not rows:
        raise ValueError('rows 必须是非空对象数组。')
    fields = list(dict.fromkeys(key for row in rows for key in row))
    csv_bytes = write_csv(rows, fields)
    return parse_source_csv(csv_bytes.decode('utf-8-sig'), source, window_end, version)


def get_snapshot(key: int) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(select(snapshots).where(snapshots.c.id == key)).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, '窗口快照不存在。')
    return dict(row)


def active_snapshot_for_window(window_end: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = _active_snapshot(connection, window_end)
    if row is None:
        raise HTTPException(404, '该窗口尚未完成整批切换。')
    return row


def _upload_session_detail(connection, row: dict[str, Any]) -> dict[str, Any]:
    parts = connection.execute(
        select(upload_parts.c.chunk_index, upload_parts.c.checksum, upload_parts.c.created)
        .where(upload_parts.c.upload_id == row['upload_id']).order_by(upload_parts.c.chunk_index)
    ).mappings().all()
    received = [part['chunk_index'] for part in parts]
    total = row['chunk_total']
    missing = [index for index in range(total) if index not in set(received)] if total else []
    return {
        'upload_id': row['upload_id'],
        'window_end': row['window_end'],
        'source': row['source'],
        'version': row['version_label'],
        'filename': row['filename'],
        'chunk_total': total,
        'received_chunks': received,
        'received_count': len(received),
        'missing_chunks': missing,
        'complete': total is not None and not missing,
        'status': row['status'],
        'batch_id': row['batch_id'],
        'created': row['created'],
        'updated': row['updated'],
    }


def create_upload_session(payload: dict[str, Any], actor: str) -> dict[str, Any]:
    upload_id = str(payload.get('upload_id') or payload.get('batch_uid')
                    or payload.get('idempotency_key') or f'up-{uuid4().hex}')[:120]
    now = _now()
    source = payload.get('source')
    if source:
        source = canonical_source(source)
    chunk_total = payload.get('chunk_total')
    chunk_total = int(chunk_total) if chunk_total not in (None, '') else None
    options = {key: value for key, value in payload.items()
               if key not in {'chunk', 'chunk_index', 'chunk_total', 'upload_id'}}
    with engine.begin() as connection:
        existing = connection.execute(select(upload_sessions).where(
            upload_sessions.c.upload_id == upload_id)).mappings().one_or_none()
        if existing is not None:
            return {**_upload_session_detail(connection, dict(existing)), 'duplicate': True}
        connection.execute(insert(upload_sessions).values(
            upload_id=upload_id, window_end=payload.get('window_end'), source=source,
            version_label=str(payload['version'])[:80] if payload.get('version') is not None else None,
            filename=(payload.get('filename') or '')[:220] or None, chunk_total=chunk_total,
            options=options, status='uploading', batch_id=None, owner=actor, created=now, updated=now))
        row = connection.execute(select(upload_sessions).where(
            upload_sessions.c.upload_id == upload_id)).mappings().one()
        return _upload_session_detail(connection, dict(row))


def get_upload_session(upload_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(select(upload_sessions).where(
            upload_sessions.c.upload_id == upload_id)).mappings().one_or_none()
        if row is None:
            raise HTTPException(404, '续跑上传会话不存在。')
        return _upload_session_detail(connection, dict(row))


def put_upload_part(upload_id: str, chunk_index: int, content: str) -> dict[str, Any]:
    if chunk_index < 0 or chunk_index > 10000:
        raise ValueError('分块编号无效。')
    if not isinstance(content, str) or not content:
        raise ValueError('分块内容不能为空。')
    checksum = content_fingerprint({'index': chunk_index, 'content': content})
    now = _now()
    with engine.begin() as connection:
        session = connection.execute(select(upload_sessions).where(
            upload_sessions.c.upload_id == upload_id)).mappings().one_or_none()
        if session is None:
            raise HTTPException(404, '续跑上传会话不存在。')
        existing = connection.execute(select(upload_parts).where(
            upload_parts.c.upload_id == upload_id, upload_parts.c.chunk_index == chunk_index
        )).mappings().one_or_none()
        if existing is not None:
            if existing['checksum'] != checksum:
                raise ValueError(f'分块 {chunk_index} 已上传但内容不一致；请使用原文件续跑。')
            row = connection.execute(select(upload_sessions).where(
                upload_sessions.c.upload_id == upload_id)).mappings().one()
            return {**_upload_session_detail(connection, dict(row)), 'duplicate': True}
        connection.execute(insert(upload_parts).values(
            upload_id=upload_id, chunk_index=chunk_index, content=content,
            checksum=checksum, created=now))
        connection.execute(update(upload_sessions).where(
            upload_sessions.c.upload_id == upload_id).values(updated=now))
        row = connection.execute(select(upload_sessions).where(
            upload_sessions.c.upload_id == upload_id)).mappings().one()
        return _upload_session_detail(connection, dict(row))


def complete_upload_session(upload_id: str, actor: str) -> dict[str, Any]:
    with engine.begin() as connection:
        session = connection.execute(select(upload_sessions).where(
            upload_sessions.c.upload_id == upload_id)).mappings().one_or_none()
        if session is None:
            raise HTTPException(404, '续跑上传会话不存在。')
        session = dict(session)
        parts = connection.execute(select(upload_parts).where(
            upload_parts.c.upload_id == upload_id).order_by(upload_parts.c.chunk_index)).mappings().all()
        if not parts:
            raise ValueError('还没有可合并的上传分块。')
        indexes = [part['chunk_index'] for part in parts]
        if indexes != list(range(len(indexes))) or len(set(indexes)) != len(indexes):
            raise ValueError('上传分块不连续，请续跑缺失分块。')
        if session['chunk_total'] is not None and len(parts) != session['chunk_total']:
            detail = _upload_session_detail(connection, session)
            raise ValueError(f"尚有分块未上传：{detail['missing_chunks']}")
        csv_text = ''.join(part['content'] for part in parts)
        options = dict(session['options'] or {})

    result = submit_batch({
        **options,
        'csv': csv_text,
        'source': session['source'] or options.get('source'),
        'window_end': session['window_end'] or options.get('window_end'),
        'version': session['version_label'] or options.get('version'),
        'filename': session['filename'] or options.get('filename'),
        'batch_uid': upload_id,
    }, actor, upload_id)
    with engine.begin() as connection:
        connection.execute(update(upload_sessions).where(upload_sessions.c.upload_id == upload_id).values(
            status='completed', batch_id=result.get('id'), updated=_now()))
    return {**result, 'upload_id': upload_id, 'resumed': True}
