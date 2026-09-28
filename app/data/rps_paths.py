"""Resolve RPS datasets through the atomically published generation manifest."""
from __future__ import annotations

import json
from pathlib import Path

RPS_MANIFEST_FILENAME = "dataset_stock_rps_manifest.json"


def rps_manifest_path(final_dir: Path) -> Path:
    return final_dir / RPS_MANIFEST_FILENAME


def resolve_rps_dataset_path(final_dir: Path, dataset_name: str) -> Path:
    """Return the active generation's dataset, or the legacy top-level path.

    A present manifest is authoritative: falling back after a malformed or
    incomplete publication could combine files from different generations.
    """
    manifest_path = rps_manifest_path(final_dir)
    if not manifest_path.exists():
        return final_dir / dataset_name
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        generation = manifest["generation"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError(f"Invalid RPS generation manifest: {manifest_path}") from exc
    if not isinstance(generation, str) or not generation:
        raise RuntimeError(f"Invalid RPS generation manifest: {manifest_path}")
    generation_path = (final_dir / generation).resolve()
    if final_dir.resolve() not in generation_path.parents:
        raise RuntimeError(f"Invalid RPS generation path in manifest: {generation}")
    dataset_path = generation_path / dataset_name
    if not dataset_path.is_file():
        raise FileNotFoundError(f"RPS generation manifest points to missing dataset: {dataset_path}")
    return dataset_path
