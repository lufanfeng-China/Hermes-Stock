"""Read-only APIs for the precomputed concept-temperature dataset."""
from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FINAL_DIR = PROJECT_ROOT / 'data/derived/datasets/final'
DATASET_PATHS = {
    'concept': FINAL_DIR / 'dataset_concept_temperature_current.json',
    'industry': FINAL_DIR / 'dataset_industry_temperature_current.json',
}
DATASET_PATH = DATASET_PATHS['concept']  # 兼容旧引用
VALID_WINDOWS = {'3', '5', '10', '20', '60'}
VALID_SCOPES = {'concept', 'industry'}
SCOPE_LABELS = {'concept': '概念', 'industry': '二级行业'}


def _load(scope: str = 'concept') -> dict:
    path = DATASET_PATHS.get(scope)
    if path is None:
        raise ValueError(f'unknown scope: {scope}')
    if not path.exists():
        raise FileNotFoundError(f'{SCOPE_LABELS[scope]}温度数据尚未构建，请先运行 build_concept_temperature.py --scope {scope}')
    return json.loads(path.read_text(encoding='utf-8'))


def _scope_of(params: dict[str, str]) -> tuple[str, dict | None]:
    scope = str(params.get('scope', 'concept')).strip().lower() or 'concept'
    if scope not in VALID_SCOPES:
        return scope, {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'scope must be concept or industry'}
    return scope, None


def handle_concept_temperature(query: str) -> dict:
    params = {key: values[0] for key, values in parse_qs(query).items() if values}
    window = str(params.get('window', '10'))
    if window not in VALID_WINDOWS:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'window must be 3, 5, 10, 20, or 60'}
    temperature_raw = params.get('temperature', '').strip()
    if temperature_raw and temperature_raw not in {'0', '1', '2', '3', '4', '5'}:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'temperature must be 0 through 5'}
    trend_raw = params.get('trend', '').strip()
    if trend_raw and trend_raw not in {'warming', 'cooling'}:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'trend must be warming or cooling'}
    try:
        min_days = int(params['min_days']) if str(params.get('min_days', '')).strip() else None
        max_days = int(params['max_days']) if str(params.get('max_days', '')).strip() else None
    except ValueError:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'min_days and max_days must be integers'}
    if (min_days is not None and min_days < 1) or (max_days is not None and max_days < 1):
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'min_days and max_days must be >= 1'}
    if min_days is not None and max_days is not None and min_days > max_days:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'min_days must not exceed max_days'}
    scope, scope_error = _scope_of(params)
    if scope_error:
        return scope_error
    try:
        data = _load(scope); section = data['windows'][window]
        concepts = section['concepts']
        if temperature_raw:
            concepts = [row for row in concepts if row.get('temperature') == int(temperature_raw)]
        if trend_raw:
            concepts = [row for row in concepts if row.get('temperature_trend') == trend_raw]
        if min_days is not None or max_days is not None:
            # 启用天数条件时，持续天数未知（当天数据不足）的概念不计入
            concepts = [row for row in concepts
                        if isinstance(row.get('temperature_streak_days'), int)
                        and (min_days is None or row['temperature_streak_days'] >= min_days)
                        and (max_days is None or row['temperature_streak_days'] <= max_days)]
        return {'ok': True, 'scope': scope, 'scope_label': SCOPE_LABELS[scope], 'unit_label': data.get('unit_label', SCOPE_LABELS[scope]),
                'as_of_date': data['as_of_date'], 'window': int(window), 'trend': trend_raw,
                'min_days': min_days, 'max_days': max_days,
                'price_basis': data['price_basis'], 'min_members': data['min_members'], 'concepts': concepts}
    except Exception as exc:
        return {'ok': False, 'status': HTTPStatus.INTERNAL_SERVER_ERROR, 'error': str(exc)}


def handle_concept_temperature_trend(query: str) -> dict:
    params = {key: values[0] for key, values in parse_qs(query).items() if values}
    window = str(params.get('window', '10')); concept_code = str(params.get('concept_code', '')).strip()
    if window not in VALID_WINDOWS or not concept_code:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'window and concept_code required'}
    scope, scope_error = _scope_of(params)
    if scope_error:
        return scope_error
    try:
        data = _load(scope); section = data['windows'][window]
        concept = next((row for row in section['concepts'] if row['concept_code'] == concept_code), None)
        if not concept:
            return {'ok': False, 'status': HTTPStatus.NOT_FOUND, 'error': 'concept not found'}
        points = section.get('heat_history', {}).get(concept_code)
        if not points:
            return {'ok': False, 'status': HTTPStatus.NOT_FOUND, 'error': '热度趋势数据尚未构建，请运行 build_concept_temperature.py'}
        return {'ok': True, 'scope': scope, 'as_of_date': data['as_of_date'], 'window': int(window), 'concept': concept, 'points': points}
    except Exception as exc:
        return {'ok': False, 'status': HTTPStatus.INTERNAL_SERVER_ERROR, 'error': str(exc)}


def handle_concept_temperature_members(query: str) -> dict:
    params = {key: values[0] for key, values in parse_qs(query).items() if values}
    window = str(params.get('window', '10')); concept_code = str(params.get('concept_code', '')).strip()
    if window not in VALID_WINDOWS or not concept_code:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'window and concept_code required'}
    scope, scope_error = _scope_of(params)
    if scope_error:
        return scope_error
    try:
        data = _load(scope); section = data['windows'][window]
        concept = next((row for row in section['concepts'] if row['concept_code'] == concept_code), None)
        if not concept:
            return {'ok': False, 'status': HTTPStatus.NOT_FOUND, 'error': 'concept not found'}
        from app.concept_temperature import fill_member_names

        return {'ok': True, 'scope': scope, 'as_of_date': data['as_of_date'], 'window': int(window),
                'price_basis': data['price_basis'], 'concept': concept,
                'stocks': fill_member_names(section['members'].get(concept_code, []))}
    except Exception as exc:
        return {'ok': False, 'status': HTTPStatus.INTERNAL_SERVER_ERROR, 'error': str(exc)}
