"""Read-only APIs for the precomputed concept-temperature dataset."""
from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = PROJECT_ROOT / 'data/derived/datasets/final/dataset_concept_temperature_current.json'
VALID_WINDOWS = {'3', '5', '10', '20', '60'}


def _load() -> dict:
    if not DATASET_PATH.exists():
        raise FileNotFoundError('概念温度数据尚未构建，请先运行 build_concept_temperature.py')
    return json.loads(DATASET_PATH.read_text(encoding='utf-8'))


def handle_concept_temperature(query: str) -> dict:
    params = {key: values[0] for key, values in parse_qs(query).items() if values}
    window = str(params.get('window', '10'))
    if window not in VALID_WINDOWS:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'window must be 3, 5, 10, 20, or 60'}
    temperature_raw = params.get('temperature', '').strip()
    if temperature_raw and temperature_raw not in {'0', '1', '2', '3', '4', '5'}:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'temperature must be 0 through 5'}
    try:
        data = _load(); section = data['windows'][window]
        concepts = section['concepts']
        if temperature_raw:
            concepts = [row for row in concepts if row.get('temperature') == int(temperature_raw)]
        return {'ok': True, 'as_of_date': data['as_of_date'], 'window': int(window), 'price_basis': data['price_basis'], 'min_members': data['min_members'], 'concepts': concepts}
    except Exception as exc:
        return {'ok': False, 'status': HTTPStatus.INTERNAL_SERVER_ERROR, 'error': str(exc)}


def handle_concept_temperature_members(query: str) -> dict:
    params = {key: values[0] for key, values in parse_qs(query).items() if values}
    window = str(params.get('window', '10')); concept_code = str(params.get('concept_code', '')).strip()
    if window not in VALID_WINDOWS or not concept_code:
        return {'ok': False, 'status': HTTPStatus.BAD_REQUEST, 'error': 'window and concept_code required'}
    try:
        data = _load(); section = data['windows'][window]
        concept = next((row for row in section['concepts'] if row['concept_code'] == concept_code), None)
        if not concept:
            return {'ok': False, 'status': HTTPStatus.NOT_FOUND, 'error': 'concept not found'}
        return {'ok': True, 'as_of_date': data['as_of_date'], 'window': int(window), 'price_basis': data['price_basis'], 'concept': concept, 'stocks': section['members'].get(concept_code, [])}
    except Exception as exc:
        return {'ok': False, 'status': HTTPStatus.INTERNAL_SERVER_ERROR, 'error': str(exc)}
