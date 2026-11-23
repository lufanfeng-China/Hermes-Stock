import importlib.util
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "update_financial_ts_package_refresh_under_test",
    ROOT / "scripts" / "update_financial_ts.py",
)
update = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(update)


def test_same_named_source_package_is_changed_when_sha256_changes(tmp_path: Path):
    package = tmp_path / "gpcw20260930.zip"
    package.write_bytes(b"new corrected package")
    meta = {
        "source_packages": {
            package.name: {
                "sha256": "old-sha256",
                "size": len(b"old package"),
            }
        }
    }

    changed = update.changed_source_packages(meta, [package])

    assert [item["path"] for item in changed] == [package]
    assert changed[0]["period"] == "2026Q3"
    assert changed[0]["fingerprint"]["sha256"] != "old-sha256"


def test_unpublished_matching_fingerprint_is_retried(tmp_path: Path, monkeypatch):
    package = tmp_path / "gpcw20260930.zip"
    package.write_bytes(b"x" * 2048)
    out_dir = tmp_path / "by_quarter"
    out_dir.mkdir()
    monkeypatch.setattr(update, "OUT_DIR", out_dir)
    fingerprint = update.source_package_fingerprint(package)
    meta = {"source_packages": {package.name: {**fingerprint, "published": False}}}

    changed = update.changed_source_packages(meta, [package])

    assert len(changed) == 1
    assert changed[0]["reason"] == "incomplete_publication"


def test_unknown_source_package_is_baselined_not_treated_as_revision(tmp_path: Path, monkeypatch):
    package = tmp_path / "gpcw20260930.zip"
    package.write_bytes(b"first observed package")
    empty_out = tmp_path / "empty_warehouse"
    empty_out.mkdir()
    monkeypatch.setattr(update, "OUT_DIR", empty_out)

    assert update.changed_source_packages({"source_packages": {}}, [package]) == []


def test_new_full_size_package_is_loaded_as_complete_period_so_new_stocks_are_not_missed(tmp_path: Path, monkeypatch):
    package = tmp_path / "gpcw20261231.zip"
    package.write_bytes(b"x" * 2048)
    empty_out = tmp_path / "empty_warehouse"
    empty_out.mkdir()
    monkeypatch.setattr(update, "OUT_DIR", empty_out)

    changed = update.changed_source_packages({"source_packages": {}}, [package])

    assert len(changed) == 1
    assert changed[0]["period"] == "2026A"
    assert changed[0]["reason"] == "untracked_new_package"


def test_revision_scan_includes_all_registered_packages_and_only_latest_unknowns(tmp_path: Path):
    packages = []
    for day in ("20261231", "20260930", "20260630", "20260331", "20251231", "20250930"):
        path = tmp_path / f"gpcw{day}.zip"
        path.write_bytes(day.encode() * 200)
        packages.append(path)
    meta = {"source_packages": {"gpcw20250930.zip": {"sha256": "known"}}}

    selected = update.source_packages_to_scan(meta, packages, latest_limit=5)

    assert {path.name for path in selected} == {
        "gpcw20261231.zip", "gpcw20260930.zip", "gpcw20260630.zip",
        "gpcw20260331.zip", "gpcw20251231.zip", "gpcw20250930.zip",
    }


def test_untracked_package_with_existing_period_is_forced_through_full_refresh(tmp_path: Path, monkeypatch):
    package = tmp_path / "gpcw20260930.zip"
    package.write_bytes(b"package newer than legacy parquet")
    out_dir = tmp_path / "by_quarter"
    out_dir.mkdir()
    pd.DataFrame([{"code": "002475", "report_date": 20260930}]).set_index("code").to_parquet(
        out_dir / "2026Q3.parquet"
    )
    monkeypatch.setattr(update, "OUT_DIR", out_dir)

    changed = update.changed_source_packages({"source_packages": {}}, [package])

    assert len(changed) == 1
    assert changed[0]["period"] == "2026Q3"
    assert changed[0]["reason"] == "untracked_existing_period"


def test_refresh_period_replaces_entire_parquet_atomically_and_updates_meta(tmp_path: Path, monkeypatch):
    out_dir = tmp_path / "by_quarter"
    out_dir.mkdir()
    existing = pd.DataFrame(
        [{"code": "002475", "report_date": 20260930, "announce_date": 20261030,
          "近一年归母净利润（万元）": 0.0},
         {"code": "999999", "report_date": 20260930, "announce_date": 20261001,
          "近一年归母净利润（万元）": 1.0}]
    ).set_index("code")
    existing.to_parquet(out_dir / "2026Q3.parquet")
    corrected = pd.DataFrame(
        [{"code": "002475", "report_date": 20260930, "财报公告日期": 261030.0,
          "近一年归母净利润（万元）": 1813846.125},
         {"code": "600519", "report_date": 20260930, "财报公告日期": 261031.0,
          "近一年归母净利润（万元）": 8216074.5}]
    ).set_index("code")
    package = tmp_path / "gpcw20260930.zip"
    package.write_bytes(b"corrected")
    meta = {
        "stocks": {
            "002475": {"latest_period": "2026Q3", "periods": {"2026Q3": {"announce_date": 20261030}}},
            "999999": {"latest_period": "2026Q3", "periods": {"2026Q3": {"announce_date": 20261001}}},
        },
        "stock_count": 2,
        "source_packages": {},
    }
    monkeypatch.setattr(update, "OUT_DIR", out_dir)
    monkeypatch.setattr(update, "MIN_FULL_PERIOD_ROWS", 1)
    monkeypatch.setattr(update, "load_full_period_frame", lambda _path: corrected.copy())

    result = update.refresh_period_from_package(meta, package, allow_large_deletion=True)

    published = pd.read_parquet(out_dir / "2026Q3.parquet")
    assert list(published.index) == ["002475", "600519"]
    assert published.loc["002475", "近一年归母净利润（万元）"] == 1813846.125
    assert published.loc["002475", "announce_date"] == 20261030
    assert result["period"] == "2026Q3"
    assert result["rows"] == 2
    assert result["changed_symbols"] == ["002475", "600519", "999999"]
    assert meta["source_packages"][package.name]["sha256"] == update.source_package_fingerprint(package)["sha256"]
    assert meta["source_packages"][package.name]["published"] is False
    assert meta["stocks"]["002475"]["periods"]["2026Q3"]["file"] == "2026Q3.parquet"
    assert "2026Q3" not in meta["stocks"]["999999"]["periods"]
    backups = list((out_dir.parent / "backups").glob("2026Q3.*.parquet"))
    assert len(backups) == 1


def test_truncated_period_package_cannot_replace_complete_parquet_or_update_meta(tmp_path: Path, monkeypatch):
    out_dir = tmp_path / "by_quarter"
    out_dir.mkdir()
    existing = pd.DataFrame([
        {"code": f"{code:06d}", "report_date": 20260930, "announce_date": 20261030}
        for code in range(1, 101)
    ]).set_index("code")
    target = out_dir / "2026Q3.parquet"
    existing.to_parquet(target)
    package = tmp_path / "gpcw20260930.zip"
    package.write_bytes(b"x" * 2048)
    truncated = pd.DataFrame([{
        "code": "000001", "report_date": 20260930, "announce_date": 20261030,
    }]).set_index("code")
    meta = {"stocks": {}, "source_packages": {}}
    meta_before = {"stocks": {}, "source_packages": {}}
    monkeypatch.setattr(update, "OUT_DIR", out_dir)
    monkeypatch.setattr(update, "MIN_FULL_PERIOD_ROWS", 1)
    monkeypatch.setattr(update, "load_full_period_frame", lambda _path: truncated.copy())

    try:
        update.refresh_period_from_package(meta, package)
    except ValueError as exc:
        assert "coverage" in str(exc)
    else:
        raise AssertionError("truncated package must be rejected")

    pd.testing.assert_frame_equal(pd.read_parquet(target), existing)
    assert meta == meta_before
    assert not list((out_dir.parent / "backups").glob("2026Q3.*.parquet"))


def test_period_refresh_rejects_even_one_removed_code_without_explicit_override(monkeypatch):
    monkeypatch.setattr(update, "MIN_FULL_PERIOD_ROWS", 1)
    old_codes = {f"{code:06d}" for code in range(1, 101)}
    new_codes = (old_codes - {"000001"}) | {"000101"}

    try:
        update._validate_period_coverage("2026Q3", new_codes, old_codes)
    except ValueError as exc:
        assert "removed=1" in str(exc)
    else:
        raise AssertionError("any removed code must require explicit override")


def test_explicit_missing_code_preserves_only_named_old_row_with_audit_evidence(tmp_path: Path, monkeypatch):
    out_dir = tmp_path / "by_quarter"
    out_dir.mkdir()
    old = pd.DataFrame([
        {"code": "601059", "report_date": 20260930, "announce_date": 20261019, "总股本": 100.0},
        {"code": "600519", "report_date": 20260930, "announce_date": 20261030, "总股本": 200.0},
    ]).set_index("code")
    old.to_parquet(out_dir / "2026Q3.parquet")
    latest = pd.DataFrame([
        {"code": "600519", "report_date": 20260930, "announce_date": 20261031, "总股本": 210.0},
    ]).set_index("code")
    package = tmp_path / "gpcw20260930.zip"
    package.write_bytes(b"x" * 2048)
    meta = {"stocks": {}, "source_packages": {}}
    monkeypatch.setattr(update, "OUT_DIR", out_dir)
    monkeypatch.setattr(update, "MIN_FULL_PERIOD_ROWS", 1)
    monkeypatch.setattr(update, "load_full_period_frame", lambda _path: latest.copy())

    result = update.refresh_period_from_package(
        meta, package, preserve_missing_codes={"601059"},
    )

    published = pd.read_parquet(out_dir / "2026Q3.parquet")
    assert list(published.index) == ["600519", "601059"]
    assert published.loc["600519", "总股本"] == 210.0
    assert published.loc["601059", "总股本"] == 100.0
    assert result["preserved_missing_codes"] == ["601059"]
    assert meta["source_packages"][package.name]["preserved_missing_codes"] == ["601059"]


def test_period_refresh_rejects_noncanonical_stock_codes(tmp_path: Path, monkeypatch):
    out_dir = tmp_path / "by_quarter"
    out_dir.mkdir()
    package = tmp_path / "gpcw20260930.zip"
    package.write_bytes(b"x" * 2048)
    invalid = pd.DataFrame([{
        "code": "SZ000001X", "report_date": 20260930, "announce_date": 20261030,
    }]).set_index("code")
    monkeypatch.setattr(update, "OUT_DIR", out_dir)
    monkeypatch.setattr(update, "MIN_FULL_PERIOD_ROWS", 1)
    monkeypatch.setattr(update, "load_full_period_frame", lambda _path: invalid.copy())

    try:
        update.refresh_period_from_package({"stocks": {}, "source_packages": {}}, package)
    except ValueError as exc:
        assert "stock codes" in str(exc)
    else:
        raise AssertionError("invalid stock code must be rejected")


def test_rebuild_latest_snapshot_raises_when_publication_fails():
    with mock.patch.object(update, "rebuild_snapshot", return_value=False) as rebuild:
        try:
            update.rebuild_latest_snapshot_or_raise()
        except RuntimeError as exc:
            assert "latest" in str(exc)
        else:
            raise AssertionError("snapshot failure must abort the update")
    rebuild.assert_called_once_with("latest")


def test_mark_refreshes_published_only_after_latest_snapshot_succeeds():
    meta = {"source_packages": {"gpcw20260930.zip": {"sha256": "abc", "published": False}}}
    result = {"source_package": "gpcw20260930.zip"}

    update.mark_refreshes_published(meta, [result])

    assert meta["source_packages"]["gpcw20260930.zip"]["published"] is True
    assert meta["source_packages"]["gpcw20260930.zip"]["published_at"]


def test_finalize_refresh_publication_commits_manifest_before_published_meta(monkeypatch):
    events = []
    meta = {"source_packages": {"gpcw20260930.zip": {"sha256": "abc", "published": False}}}
    results = [{"source_package": "gpcw20260930.zip"}]
    updates = [("002475", "2026Q3", 20260930, 20261030, {})]
    monkeypatch.setattr(update, "write_change_manifest", lambda value: events.append(("manifest", value)))
    monkeypatch.setattr(update, "save_meta", lambda value: events.append(("meta", value["source_packages"]["gpcw20260930.zip"]["published"])))

    update.finalize_refresh_publication(meta, results, updates)

    assert events == [("manifest", updates), ("meta", True)]
