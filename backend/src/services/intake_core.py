"""Pure parsing, version selection and window joining for the three source ledgers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import defaultdict
from datetime import date
from typing import Any

HISTORY = 'history'
PRESSURE = 'pressure'
BRAKE_LOAD = 'brake_load'

SOURCE_ORDER = (HISTORY, PRESSURE, BRAKE_LOAD)
SOURCE_LABELS = {
    HISTORY: '轮胎履历',
    PRESSURE: '胎压巡检',
    BRAKE_LOAD: '制动载荷',
}
SOURCE_ALIASES = {
    HISTORY: {HISTORY, 'tire_history', 'tire-history', 'tirehistory', 'tyre_history', 'tyre-history', 'tyrehistory', '履历', '轮胎履历', '轮胎履历台账'},
    PRESSURE: {PRESSURE, 'pressure_inspection', 'pressure-inspection', 'inspection', 'tire_pressure',
               '胎压', '胎压巡检', '冷态胎压巡检'},
    BRAKE_LOAD: {BRAKE_LOAD, 'brake-load', 'brakeload', 'brake_load', 'brakes_load', 'brake_and_load',
                 '制动', '载荷', '制动载荷', '急制动与载荷', '车载急制动与客流载荷'},
}
FIELD_LABELS = {
    'tire_id': '轮胎编号',
    'route': '线路',
    'window_end': '窗口截止日',
    'mileage_km': '窗口里程',
    'tire_age_days': '期初胎龄',
    'route_load_pct': '线路载荷率',
    'low_pressure_pct': '低胎压检测占比',
    'hard_brakes_per_1000km': '急制动频次',
    'tread_loss_mm': '胎纹磨耗',
}
HEADER_ALIASES = {
    'tire_id': 'tire_id', '轮胎编号': 'tire_id', '胎号': 'tire_id',
    'route': 'route', '线路': 'route', '车组线路': 'route',
    'window_end': 'window_end', '窗口截止日': 'window_end', '窗口截止日期': 'window_end',
    '观测窗口': 'window_end', '盘点窗口': 'window_end',
    'version': 'version', 'source_version': 'version', 'record_version': 'version',
    '版本': 'version', '来源版本': 'version', '记录版本': 'version',
    'mileage_km': 'mileage_km', '窗口里程（公里）': 'mileage_km', '窗口里程(公里)': 'mileage_km',
    '里程': 'mileage_km', '里程公里': 'mileage_km',
    'tire_age_days': 'tire_age_days', '期初胎龄（天）': 'tire_age_days',
    '期初胎龄(天)': 'tire_age_days', '胎龄': 'tire_age_days',
    'route_load_pct': 'route_load_pct', '车组在线路上的平均载荷率（%）': 'route_load_pct',
    '车组在线路上的平均载荷率(%)': 'route_load_pct', '线路载荷率（%）': 'route_load_pct',
    '线路载荷率(%)': 'route_load_pct', '载荷率': 'route_load_pct',
    'low_pressure_pct': 'low_pressure_pct', '低胎压检测占比（%）': 'low_pressure_pct',
    '低胎压检测占比(%)': 'low_pressure_pct', '低胎压检测占比': 'low_pressure_pct', '胎压异常占比': 'low_pressure_pct',
    'hard_brakes_per_1000km': 'hard_brakes_per_1000km', '急制动频次（次/千公里）': 'hard_brakes_per_1000km',
    '急制动频次(次/千公里)': 'hard_brakes_per_1000km', '急制动频次': 'hard_brakes_per_1000km',
    'tread_loss_mm': 'tread_loss_mm', '胎纹磨耗（毫米）': 'tread_loss_mm',
    '胎纹磨耗(毫米)': 'tread_loss_mm', '胎纹磨耗': 'tread_loss_mm', '磨耗': 'tread_loss_mm',
    'tread_depth_start_mm': 'tread_depth_start_mm', '期初胎纹深度': 'tread_depth_start_mm',
    '期初胎纹深度（mm）': 'tread_depth_start_mm', '期初胎纹深度(mm)': 'tread_depth_start_mm',
    'tread_start_mm': 'tread_depth_start_mm',
    'tread_depth_end_mm': 'tread_depth_end_mm', '期末胎纹深度': 'tread_depth_end_mm',
    '期末胎纹深度（mm）': 'tread_depth_end_mm', '期末胎纹深度(mm)': 'tread_depth_end_mm',
    'tread_end_mm': 'tread_depth_end_mm',
}
SOURCE_FIELDS = {
    HISTORY: ('route', 'mileage_km', 'tire_age_days', 'tread_loss_mm'),
    PRESSURE: ('low_pressure_pct',),
    BRAKE_LOAD: ('hard_brakes_per_1000km', 'route_load_pct'),
}


def canonical_source(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    folded = text.casefold()
    compact = re.sub(r'[\s_\-]+', '', folded)
    for source, aliases in SOURCE_ALIASES.items():
        alias_variants: set[str] = set()
        for alias in aliases:
            alias_folded = alias.casefold()
            alias_variants.update({alias, alias_folded, re.sub(r'[\s_\-]+', '', alias_folded)})
        if text in alias_variants or folded in alias_variants or compact in alias_variants or compact == source:
            return source
    raise ValueError('来源类型须为轮胎履历、胎压巡检或制动载荷。')


def source_label(source: str) -> str:
    return SOURCE_LABELS[source]


def infer_source(fieldnames: list[str] | None) -> str | None:
    if not fieldnames:
        return None
    mapped = {HEADER_ALIASES.get(name.strip().lstrip('﻿'), name.strip().lstrip('﻿')) for name in fieldnames}
    if 'low_pressure_pct' in mapped:
        return PRESSURE
    if 'hard_brakes_per_1000km' in mapped:
        return BRAKE_LOAD
    if {'mileage_km', 'tire_age_days', 'tread_loss_mm', 'tread_depth_start_mm'} & mapped:
        return HISTORY
    return None


def version_key(version: Any) -> str:
    """Return a lexicographically sortable key for common version notations."""
    if version is None or str(version).strip() == '':
        return '0:unversioned'
    text = str(version).strip()
    try:
        parsed = date.fromisoformat(text[:10])
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}.*', text):
            return f'1:{parsed.toordinal():010d}:{text[10:]}'
    except ValueError:
        pass
    numbers = re.findall(r'\d+', text)
    if numbers:
        return '2:' + '.'.join(part.zfill(12) for part in numbers)
    return '3:' + text.casefold()


def content_fingerprint(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _number(raw: Any, field: str, issues: list[str]) -> float | int | None:
    label = FIELD_LABELS.get(field, field)
    if raw is None or isinstance(raw, bool) or str(raw).strip() == '':
        issues.append(f'{label}不能为空')
        return None
    text = str(raw).strip()
    try:
        if field == 'tire_age_days':
            if not re.fullmatch(r'[+-]?\d+', text):
                raise ValueError
            value: float | int = int(text)
        else:
            value = float(text)
    except (ValueError, TypeError, OverflowError):
        issues.append(f'{label}不是有效数值（{text}）')
        return None
    if not math.isfinite(float(value)):
        issues.append(f'{label}必须为有限数值')
        return None
    if float(value) < 0:
        issues.append(f'{label}不能为负数')
        return None
    if field == 'mileage_km' and float(value) == 0:
        issues.append('窗口里程不能为零或负数')
        return None
    if field == 'low_pressure_pct' and float(value) > 100:
        issues.append(f'{label}须在 0–100% 之间')
        return None
    return value


def _headers(reader: csv.DictReader) -> dict[str, str]:
    if not reader.fieldnames:
        raise ValueError('CSV 缺少表头。')
    mapping: dict[str, str] = {}
    for header in reader.fieldnames:
        if header is None:
            continue
        clean = header.strip().lstrip('﻿')
        canonical = HEADER_ALIASES.get(clean, HEADER_ALIASES.get(clean.casefold()))
        if canonical and canonical not in mapping:
            mapping[canonical] = header
    if 'tire_id' not in mapping:
        raise ValueError('CSV 表头须包含 tire_id（轮胎编号）。')
    return mapping


def parse_source_csv(text: str, source: str | None = None, default_window: str | None = None,
                     default_version: Any = None) -> dict[str, Any]:
    """Parse one source CSV.

    Row-level business problems are returned on each observation so the tire can be
    quarantined with a reason. Structural CSV/header problems remain ValueErrors.
    """
    if not text or not text.strip():
        raise ValueError('上传内容为空，请选择 CSV 文件。')
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip('﻿'), newline=''), strict=True)
        mapping = _headers(reader)
        source = canonical_source(source) or infer_source(reader.fieldnames)
        if source is None:
            raise ValueError('无法识别来源，请选择轮胎履历、胎压巡检或制动载荷。')
        rows: list[dict[str, Any]] = []
        windows: set[date] = set()
        for row in reader:
            if None in row:
                raise ValueError(f'第 {reader.line_num} 行列数多于表头。')
            if not any(str(value or '').strip() for value in row.values()):
                continue
            tire_id = str(row.get(mapping['tire_id'], '') or '').strip()
            if not tire_id:
                raise ValueError(f'第 {reader.line_num} 行缺少轮胎编号，无法进入隔离名单。')
            raw_version = row.get(mapping['version']) if 'version' in mapping else None
            version_label = str(raw_version).strip() if raw_version not in (None, '') else (
                str(default_version).strip() if default_version not in (None, '') else None)

            raw_window = row.get(mapping['window_end']) if 'window_end' in mapping else None
            window_text = str(raw_window).strip() if raw_window not in (None, '') else (default_window or '')
            if not window_text:
                raise ValueError(f'第 {reader.line_num} 行缺少窗口截止日 window_end。')
            try:
                window = date.fromisoformat(window_text)
                if window.isoformat() != window_text:
                    raise ValueError
            except ValueError as error:
                raise ValueError(f'第 {reader.line_num} 行窗口截止日无效，请按 YYYY-MM-DD 填写。') from error
            windows.add(window)
            if len(windows) > 1:
                raise ValueError('同一来源文件不能混入多个观测窗口，请按 window_end 拆分后上传。')

            issues: list[str] = []
            raw_payload: dict[str, Any] = {}
            payload: dict[str, Any] = {}

            if source == HISTORY:
                route_header = mapping.get('route')
                route = str(row.get(route_header, '') or '').strip() if route_header else ''
                raw_payload['route'] = route
                if not route:
                    issues.append('线路不能为空')
                else:
                    payload['route'] = route

                for field in ('mileage_km', 'tire_age_days'):
                    header = mapping.get(field)
                    raw_value = row.get(header) if header else None
                    raw_payload[field] = '' if raw_value is None else str(raw_value).strip()
                    value = _number(raw_value, field, issues)
                    if value is not None:
                        payload[field] = value

                loss_header = mapping.get('tread_loss_mm')
                start_header = mapping.get('tread_depth_start_mm')
                end_header = mapping.get('tread_depth_end_mm')
                if loss_header:
                    raw_loss = row.get(loss_header)
                    raw_payload['tread_loss_mm'] = '' if raw_loss is None else str(raw_loss).strip()
                    loss = _number(raw_loss, 'tread_loss_mm', issues)
                    if loss is not None:
                        payload['tread_loss_mm'] = loss
                elif start_header and end_header:
                    start_issues: list[str] = []
                    end_issues: list[str] = []
                    start = _number(row.get(start_header), 'tread_depth_start_mm', start_issues)
                    end = _number(row.get(end_header), 'tread_depth_end_mm', end_issues)
                    issues.extend(start_issues + end_issues)
                    raw_payload['tread_depth_start_mm'] = str(row.get(start_header, '') or '').strip()
                    raw_payload['tread_depth_end_mm'] = str(row.get(end_header, '') or '').strip()
                    if start is not None and end is not None:
                        loss = round(float(start) - float(end), 4)
                        if loss < 0:
                            issues.append('胎纹磨耗不能为负数（期初深度应不小于期末深度）')
                        else:
                            payload['tread_loss_mm'] = loss
                            raw_payload['tread_loss_mm'] = loss
                else:
                    issues.append('胎纹磨耗不能为空（可提供 tread_loss_mm，或期初/期末胎纹深度）')
            else:
                for field in SOURCE_FIELDS[source]:
                    header = mapping.get(field)
                    raw_value = row.get(header) if header else None
                    raw_payload[field] = '' if raw_value is None else str(raw_value).strip()
                    value = _number(raw_value, field, issues)
                    if value is not None:
                        payload[field] = value

            # Preserve overlapping identifiers/metrics if a ledger happens to include them.
            # This lets the joiner detect cross-ledger conflicts in addition to duplicate
            # same-version rows within one source.
            for extra_field in ('route', 'mileage_km', 'tire_age_days', 'route_load_pct',
                                'low_pressure_pct', 'hard_brakes_per_1000km', 'tread_loss_mm'):
                if extra_field in raw_payload or extra_field not in mapping:
                    continue
                header = mapping[extra_field]
                raw_value = row.get(header)
                raw_payload[extra_field] = '' if raw_value is None else str(raw_value).strip()
                if extra_field == 'route':
                    value_text = str(raw_value or '').strip()
                    if value_text:
                        payload[extra_field] = value_text
                    else:
                        issues.append('线路不能为空')
                else:
                    value = _number(raw_value, extra_field, issues)
                    if value is not None:
                        payload[extra_field] = value

            fingerprint_data = {key: payload.get(key, raw_payload.get(key)) for key in raw_payload}
            rows.append({
                'tire_id': tire_id,
                'window_end': window.isoformat(),
                'source': source,
                'version_label': version_label,
                'version_key': version_key(version_label),
                'raw_payload': raw_payload,
                'payload': payload,
                'issues': issues,
                'valid': not issues,
                'fingerprint': content_fingerprint(fingerprint_data),
            })
        if not rows:
            raise ValueError('CSV 需要至少一条数据。')
        if len(rows) > 5000:
            raise ValueError('单份来源数据最多 5000 行。')
        return {'source': source, 'window_end': next(iter(windows)).isoformat(), 'rows': rows}
    except csv.Error as error:
        raise ValueError('CSV 引号或字段格式有误。') from error


def normalize_expected_counts(expected_total: int | None = None,
                              expected_counts: dict[str, int] | None = None) -> dict[str, int | None]:
    counts: dict[str, int | None] = {source: expected_total for source in SOURCE_ORDER}
    if expected_counts:
        for key, value in expected_counts.items():
            source = canonical_source(key)
            if source is None:
                raise ValueError(f'未知来源类型：{key}')
            if value is None:
                counts[source] = None
                continue
            try:
                number = int(value)
            except (TypeError, ValueError) as error:
                raise ValueError('申报条数必须是整数。') from error
            if number < 0 or number > 5000:
                raise ValueError('申报条数须在 0–5000 之间。')
            counts[source] = number
    return counts


def source_counts(observations: list[dict[str, Any]]) -> dict[str, set[str]]:
    counts: dict[str, set[str]] = {source: set() for source in SOURCE_ORDER}
    for observation in observations:
        source = canonical_source(observation['source'])
        if source in counts:
            counts[source].add(str(observation['tire_id']))
    return counts


def source_progress(observations: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Count current-version facts and distinct tires per source.

    Exact duplicate facts are represented once by the persistence layer. Conflicting
    same-version facts remain separate because they must drive quarantine. Older
    versions do not count toward the declared current batch after a newer one exists.
    """
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {source: defaultdict(list) for source in SOURCE_ORDER}
    for observation in observations:
        source = canonical_source(observation['source'])
        grouped[source][str(observation['tire_id'])].append(observation)
    progress: dict[str, dict[str, int]] = {}
    for source in SOURCE_ORDER:
        records = 0
        tires = len(grouped[source])
        for items in grouped[source].values():
            latest_key = max(str(item.get('version_key') or version_key(item.get('version_label'))) for item in items)
            latest = [item for item in items
                      if str(item.get('version_key') or version_key(item.get('version_label'))) == latest_key]
            records += len({str(item['fingerprint']) for item in latest})
        progress[source] = {'received': records, 'tire_count': tires}
    return progress


def build_snapshot(window_end: str, observations: list[dict[str, Any]],
                   expected_counts: dict[str, int | None] | None = None) -> dict[str, Any]:
    """Join same-window/same-tire records and produce samples + quarantine."""
    expected = normalize_expected_counts(None, expected_counts or {}) if expected_counts else {
        source: None for source in SOURCE_ORDER}
    by_tire: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    tire_ids: set[str] = set()
    for observation in observations:
        if observation.get('window_end') != window_end:
            continue
        source = canonical_source(observation['source'])
        tire_id = str(observation['tire_id'])
        by_tire[tire_id][source].append(observation)
        tire_ids.add(tire_id)

    samples: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    missing_total = conflict_total = invalid_total = 0
    for tire_id in sorted(tire_ids):
        reasons: list[str] = []
        missing_sources: list[str] = []
        conflict_sources: list[str] = []
        invalid_sources: list[str] = []
        merged: dict[str, Any] = {'tire_id': tire_id, 'window_end': window_end}
        field_sources: dict[str, str] = {}

        for source in SOURCE_ORDER:
            items = by_tire[tire_id].get(source, [])
            label = source_label(source)
            if not items:
                missing_sources.append(source)
                reasons.append(f'缺来源：{label}')
                continue
            latest_key = max(str(item.get('version_key') or version_key(item.get('version_label'))) for item in items)
            latest = [item for item in items
                      if str(item.get('version_key') or version_key(item.get('version_label'))) == latest_key]
            fingerprints = {str(item['fingerprint']) for item in latest}
            version_text = next((item.get('version_label') for item in latest if item.get('version_label')), None)
            version_suffix = f'版本 {version_text} ' if version_text else '同版本'
            if len(fingerprints) > 1:
                conflict_sources.append(source)
                fields = SOURCE_FIELDS[source]
                changed = []
                for field in fields:
                    values = []
                    for item in latest:
                        value = item.get('payload', {}).get(field, item.get('raw_payload', {}).get(field))
                        if value not in values:
                            values.append(value)
                    if len(values) > 1:
                        changed.append(FIELD_LABELS.get(field, field) + '=' + ' / '.join(map(str, values[:4])))
                detail = '；'.join(changed[:3]) if changed else '同版记录的数值指纹不同'
                reasons.append(f'同版数值冲突：{label}{version_suffix}存在不一致（{detail}）')
                continue

            chosen = latest[0]
            issues = list(chosen.get('issues') or [])
            if not chosen.get('valid', not issues) or issues:
                invalid_sources.append(source)
                reasons.extend(f'{label}：{issue}' for issue in issues)
                missing_sources.append(source)
                reasons.append(f'缺来源：{label}（该来源记录无效）')
                continue
            for field, value in chosen['payload'].items():
                if field in ('tire_id', 'window_end'):
                    continue
                if field in merged and merged[field] != value:
                    previous_label = SOURCE_LABELS.get(field_sources.get(field, ''), field_sources.get(field, ''))
                    conflict_sources.append(source)
                    reasons.append(
                        f'同版数值冲突：{FIELD_LABELS.get(field, field)}在{previous_label or "其他来源"}'
                        f'与{label}之间不一致（{merged[field]} ≠ {value}）'
                    )
                else:
                    merged[field] = value
                    field_sources[field] = source

        codes = []
        if missing_sources:
            codes.append('missing_source')
        if conflict_sources:
            codes.append('same_version_conflict')
        if invalid_sources:
            codes.append('invalid_value')
        entry = {
            'tire_id': tire_id,
            'window_end': window_end,
            'quarantined': True,
            'codes': codes,
            'reason_codes': codes,
            'missing_sources': list(dict.fromkeys(missing_sources)),
            'conflict_sources': list(dict.fromkeys(conflict_sources)),
            'invalid_sources': list(dict.fromkeys(invalid_sources)),
            'reasons': reasons,
            'reason': '；'.join(reasons),
            'isolation_reason': '；'.join(reasons),
        }
        if reasons:
            quarantine.append(entry)
            missing_total += bool(missing_sources)
            conflict_total += bool(conflict_sources)
            invalid_total += bool(invalid_sources)
        else:
            samples.append(merged)

    progress = source_progress(observations)
    source_stats = {}
    complete = True
    for source in SOURCE_ORDER:
        received = progress[source]['received']
        tire_count = progress[source]['tire_count']
        wanted = expected.get(source)
        source_complete = wanted is not None and received == wanted
        if wanted is None:
            source_complete = False
            complete = False
        elif received != wanted:
            complete = False
        source_stats[source] = {
            'key': source,
            'label': source_label(source),
            'received': received,
            'record_count': received,
            'tire_count': tire_count,
            'expected': wanted,
            'complete': source_complete,
            'difference': None if wanted is None else received - wanted,
        }

    stats = {
        'window_end': window_end,
        'total_tires': len(tire_ids),
        'sample_count': len(samples),
        'quarantine_count': len(quarantine),
        'missing_source_tires': missing_total,
        'conflict_tires': conflict_total,
        'invalid_tires': invalid_total,
        'sources': source_stats,
        'complete': complete,
    }
    return {'samples': samples, 'quarantine': quarantine, 'stats': stats}
