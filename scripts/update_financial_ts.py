#!/usr/bin/env python3
"""
update_financial_ts.py
======================
增量更新财务时间序列数据。

工作逻辑：
1. 读取 meta.json 获取每只股票已知最新报告期
2. 扫描最新的 gpcw zip，检测哪些股票有更新的财报（compare announce_date）
3. 对检测到新财报的股票：
   a. 从 zip 中提取完整行数据
   b. 按报告期追加到对应 by_quarter/*.parquet（不存在则创建）
   c. 更新 meta.json 中该股票的 periods 条目
4. 重算指定报告期的百分位排名快照（调用仓库版快照引擎）

用法：
    python scripts/update_financial_ts.py [--dry-run]
    python scripts/update_financial_ts.py [--full]   # 全量重建（调用 builder）
    python scripts/update_financial_ts.py [--rebuild-period 2025A]   # 重建指定期次快照
    python scripts/update_financial_ts.py [--rebuild-period latest] # 重建最新期快照

前置依赖：
    meta.json 已由 financial_ts_builder.py 初始化
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

# ── 路径配置 ────────────────────────────────────────────────────────────────
PROJECT = Path(__file__).parent.parent.resolve()
TDX_CW  = Path(os.environ.get("TDX_CW_DIR", "/home/lufanfeng/tdx_data/vipdoc/cw"))
OUT_DIR = PROJECT / "data/derived/financial_ts/by_quarter"
META_FP = PROJECT / "data/derived/financial_ts/meta.json"
CHANGE_MANIFEST_FP = PROJECT / "data/derived/manifests/financial_changes_current.json"
MIN_COMPLETE_PACKAGE_BYTES = 1024
MIN_FULL_PERIOD_ROWS = 1000

sys.path.insert(0, "/home/lufanfeng/.venvs/moontdx-china-stock-data/lib/python3.12/site-packages")

# ── 报告期解析（与 builder 保持一致） ───────────────────────────────────────
def parse_period(report_date: int) -> str:
    s = str(report_date)
    year, month = int(s[:4]), int(s[4:6])
    if month == 3:  return f"{year}Q1"
    if month == 6:  return f"{year}Q2"
    if month == 9:  return f"{year}Q3"
    if month == 12: return f"{year}A"
    q = (month - 1) // 3
    return f"{year}Q{q}" if 1 <= q <= 4 else f"{year}A"


def format_announce_date(raw) -> int:
    """通达信 '财报公告日期' 格式为 YYMMDD 浮点数，如 260422.0 = 2026-04-22。"""
    try:
        v = float(raw)
        if np.isnan(v) or v == 0:
            return 0
        yymmdd = int(v)
        yy = yymmdd // 10000
        mm = (yymmdd % 10000) // 100
        dd = yymmdd % 100
        yy += 2000 if yy < 50 else 1900
        return yy * 10000 + mm * 100 + dd
    except (TypeError, ValueError):
        return 0


def canonical_code(idx_val) -> str:
    s = str(idx_val).strip().lower()
    for p in ("sh:", "sz:", "bj:"):
        s = s.replace(p, "")
    return s


def _period_order(p: str) -> tuple:
    """将 '2023A' / '2023Q1' 转为排序键 (year, q)。年报 q=5 排在 Q3 之后。"""
    p = str(p or "")
    if not p:
        return (0, 0)
    year = int(p[:4])
    if "A" in p:
        q = 5
    else:
        q = int(p[-1])
    return (year, q)


def source_package_fingerprint(path: Path) -> dict[str, object]:
    """Return a content fingerprint; mtime alone is never revision evidence."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    stat = Path(path).stat()
    return {
        "sha256": digest.hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def changed_source_packages(meta: dict, packages: list[Path]) -> list[dict[str, object]]:
    """Detect same-name package revisions previously recorded in meta.

    Unknown packages are handled by the ordinary new-report path and baselined
    after successful publication; they are not revisions by definition.
    """
    known = meta.get("source_packages") or {}
    changed = []
    for path in packages:
        path = Path(path)
        period = parse_period(int(path.stem[-8:]))
        previous = known.get(path.name)
        fingerprint = source_package_fingerprint(path)
        if not isinstance(previous, dict) or not previous.get("sha256"):
            if (OUT_DIR / f"{period}.parquet").exists():
                changed.append({
                    "path": path,
                    "period": period,
                    "fingerprint": fingerprint,
                    "previous_fingerprint": previous,
                    "reason": "untracked_existing_period",
                })
            elif path.stat().st_size >= MIN_COMPLETE_PACKAGE_BYTES:
                changed.append({
                    "path": path,
                    "period": period,
                    "fingerprint": fingerprint,
                    "previous_fingerprint": previous,
                    "reason": "untracked_new_package",
                })
            continue
        if fingerprint["sha256"] == previous.get("sha256") and previous.get("published") is False:
            changed.append({
                "path": path,
                "period": period,
                "fingerprint": fingerprint,
                "previous_fingerprint": previous,
                "reason": "incomplete_publication",
            })
        elif fingerprint["sha256"] != previous.get("sha256"):
            changed.append({
                "path": path,
                "period": period,
                "fingerprint": fingerprint,
                "previous_fingerprint": previous,
                "reason": "sha256_changed",
            })
    return changed


def source_packages_to_scan(meta: dict, packages: list[Path], latest_limit: int = 5) -> list[Path]:
    """Always scan registered packages plus recent unknown packages/new periods."""
    ordered = sorted((Path(path) for path in packages), key=lambda path: path.name, reverse=True)
    known = set((meta.get("source_packages") or {}).keys())
    latest = {path.name for path in ordered[:latest_limit]}
    return [path for path in ordered if path.name in known or path.name in latest]


def load_full_period_frame(path: Path) -> pd.DataFrame:
    """Read the complete corrected package with the warehouse's canonical schema."""
    from scripts.financial_ts_builder import load_cw_zip

    frame = load_cw_zip(Path(path))
    if frame is None:
        raise ValueError(f"failed to read source package: {path}")
    frame.index = frame.index.astype(str).map(canonical_code)
    frame.index.name = "code"
    return frame.sort_index(kind="stable")


def _validate_period_frame(period: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        raise ValueError(f"{period}: source package produced no rows")
    if frame.index.has_duplicates:
        raise ValueError(f"{period}: duplicate stock codes")
    if "report_date" not in frame.columns:
        raise ValueError(f"{period}: missing report_date")
    periods = {
        parse_period(int(value))
        for value in pd.to_numeric(frame["report_date"], errors="coerce").dropna()
    }
    if periods != {period}:
        raise ValueError(f"{period}: report_date periods mismatch: {sorted(periods)}")
    numeric = frame.select_dtypes(include=[np.number])
    if np.isinf(numeric.to_numpy(dtype=float, copy=False)).any():
        raise ValueError(f"{period}: non-finite infinite values")


def _normalize_period_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.index = frame.index.astype(str).map(canonical_code)
    frame.index.name = "code"
    frame["report_date"] = pd.to_numeric(frame["report_date"], errors="raise").astype("int64")
    if "announce_date" in frame.columns:
        source = frame["announce_date"]
    elif "财报公告日期" in frame.columns:
        source = frame["财报公告日期"]
    else:
        source = pd.Series(0, index=frame.index)
    frame["announce_date"] = [
        int(float(value)) if pd.notna(value) and float(value) >= 10_000_000
        else format_announce_date(value)
        for value in source
    ]
    return frame.sort_index(kind="stable")


def _validate_period_coverage(
    period: str,
    new_codes: set[str],
    old_codes: set[str],
    *,
    allow_large_deletion: bool = False,
) -> dict[str, object]:
    invalid_codes = sorted(code for code in new_codes if len(code) != 6 or not code.isdigit())
    if invalid_codes:
        raise ValueError(f"{period}: invalid stock codes: {invalid_codes[:10]}")
    if len(new_codes) < MIN_FULL_PERIOD_ROWS:
        raise ValueError(
            f"{period}: coverage row count {len(new_codes)} below minimum {MIN_FULL_PERIOD_ROWS}"
        )
    removed = old_codes - new_codes
    added = new_codes - old_codes
    if old_codes and removed and not allow_large_deletion:
        raise ValueError(
            f"{period}: coverage deletion gate failed: old={len(old_codes)} "
            f"new={len(new_codes)} removed={len(removed)} added={len(added)}; "
            "explicit --allow-large-deletion is required"
        )
    return {
        "old_rows": len(old_codes),
        "new_rows": len(new_codes),
        "intersection_rows": len(old_codes & new_codes),
        "added_rows": len(added),
        "removed_rows": len(removed),
    }


def _latest_period_from_entries(entries: dict) -> str:
    return max(entries, key=_period_order) if entries else ""


def refresh_period_from_package(
    meta: dict,
    package: Path,
    *,
    allow_large_deletion: bool = False,
    preserve_missing_codes: set[str] | None = None,
) -> dict[str, object]:
    """Atomically replace one complete report period from a revised CW package."""
    package = Path(package)
    period = parse_period(int(package.stem[-8:]))
    frame = _normalize_period_frame(load_full_period_frame(package))
    _validate_period_frame(period, frame)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"{period}.parquet"
    old_codes: set[str] = set()
    old_frame: pd.DataFrame | None = None
    if target.exists():
        old_frame = pd.read_parquet(target)
        old_frame.index = old_frame.index.astype(str).map(canonical_code)
        old_frame.index.name = "code"
        old_codes = set(old_frame.index)

    requested_preserves = {canonical_code(code) for code in (preserve_missing_codes or set())}
    preserved_codes: list[str] = []
    if requested_preserves:
        missing_from_source = old_codes - set(frame.index.astype(str))
        invalid_preserves = requested_preserves - missing_from_source
        if invalid_preserves:
            raise ValueError(
                f"{period}: preserve codes are not old rows missing from source: "
                f"{sorted(invalid_preserves)}"
            )
        assert old_frame is not None
        preserved_codes = sorted(requested_preserves)
        frame = pd.concat([frame, old_frame.loc[preserved_codes]], axis=0, sort=False)
        frame = frame.sort_index(kind="stable")
        _validate_period_frame(period, frame)

    new_codes = set(frame.index.astype(str))
    coverage = _validate_period_coverage(
        period, new_codes, old_codes, allow_large_deletion=allow_large_deletion,
    )

    if target.exists():
        backup_dir = OUT_DIR.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        shutil.copy2(target, backup_dir / f"{period}.{stamp}.parquet")

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=OUT_DIR, prefix=f".{period}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
        frame.to_parquet(temporary, index=True, engine="pyarrow", compression="snappy")
        published = pd.read_parquet(temporary)
        published.index = published.index.astype(str).map(canonical_code)
        pd.testing.assert_frame_equal(published, frame, check_dtype=False, check_exact=True)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    stocks = meta.setdefault("stocks", {})
    for code in old_codes - new_codes:
        info = stocks.get(code)
        if not isinstance(info, dict):
            continue
        periods = info.setdefault("periods", {})
        periods.pop(period, None)
        info["latest_period"] = _latest_period_from_entries(periods)
    for code, row in frame.iterrows():
        info = stocks.setdefault(code, {"name": "", "periods": {}, "latest_period": ""})
        periods = info.setdefault("periods", {})
        report_date = int(float(row.get("report_date", 0)))
        announce_date = int(float(row.get("announce_date", 0) or 0))
        if not announce_date:
            announce_date = format_announce_date(row.get("财报公告日期", 0))
        periods[period] = {
            "report_date": report_date,
            "announce_date": announce_date,
            "file": f"{period}.parquet",
        }
        info["latest_period"] = _latest_period_from_entries(periods)

    fingerprint = source_package_fingerprint(package)
    meta.setdefault("source_packages", {})[package.name] = {
        **fingerprint,
        "period": period,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "published": False,
        "preserved_missing_codes": preserved_codes,
    }
    meta["stock_count"] = len(stocks)
    return {
        "period": period,
        "rows": len(frame),
        "changed_symbols": sorted(old_codes | new_codes),
        "fingerprint": fingerprint,
        "source_package": package.name,
        "target": str(target),
        "coverage": coverage,
        "preserved_missing_codes": preserved_codes,
    }


# ── Meta 读写 ────────────────────────────────────────────────────────────────
def load_meta() -> dict:
    if not META_FP.exists():
        print("ERROR: meta.json 不存在，请先运行 financial_ts_builder.py 全量初始化", file=sys.stderr)
        sys.exit(1)
    with open(META_FP) as f:
        return json.load(f)


def save_meta(meta: dict):
    meta["last_updated"] = pd.Timestamp.now().isoformat()
    META_FP.parent.mkdir(parents=True, exist_ok=True)
    temp = META_FP.with_suffix(".tmp")
    temp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, META_FP)


def _record_package_fingerprints(meta: dict, packages: list[Path]) -> None:
    recorded = meta.setdefault("source_packages", {})
    for path in packages:
        fingerprint = source_package_fingerprint(path)
        previous = recorded.get(path.name) if isinstance(recorded.get(path.name), dict) else {}
        same_content = previous.get("sha256") == fingerprint["sha256"]
        recorded[path.name] = {
            **fingerprint,
            "period": parse_period(int(path.stem[-8:])),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "published": previous.get("published", True) if same_content else True,
        }


def mark_refreshes_published(meta: dict, refresh_results: list[dict[str, object]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    recorded = meta.setdefault("source_packages", {})
    for result in refresh_results:
        package_name = str(result["source_package"])
        entry = recorded.get(package_name)
        if not isinstance(entry, dict):
            raise KeyError(f"missing source package fingerprint: {package_name}")
        entry["published"] = True
        entry["published_at"] = now


def finalize_refresh_publication(
    meta: dict,
    refresh_results: list[dict[str, object]],
    manifest_updates: list[tuple[str, str, int, int, dict]],
) -> None:
    write_change_manifest(manifest_updates)
    mark_refreshes_published(meta, refresh_results)
    save_meta(meta)


def _source_package_for_period(period: str) -> Path:
    matches = [path for path in TDX_CW.glob("gpcw*.zip")
               if parse_period(int(path.stem[-8:])) == period]
    if not matches:
        raise FileNotFoundError(f"no CW package found for {period} under {TDX_CW}")
    return max(matches, key=lambda path: path.stat().st_mtime_ns)


def _manifest_updates_for_refresh(meta: dict, result: dict[str, object]) -> list[tuple[str, str, int, int, dict]]:
    period = str(result["period"])
    updates = []
    for code in result["changed_symbols"]:
        entry = ((meta.get("stocks", {}).get(code, {}).get("periods", {}) or {}).get(period, {}) or {})
        updates.append((code, period, int(entry.get("report_date") or 0),
                        int(entry.get("announce_date") or 0), {}))
    return updates


def write_change_manifest(updates: list[tuple[str, str, int, int, dict]]) -> None:
    """Publish the exact dirty symbols for downstream incremental snapshots."""
    CHANGE_MANIFEST_FP.parent.mkdir(parents=True, exist_ok=True)
    records = [{"symbol": code, "period": period, "report_date": report_date, "announce_date": announce_date}
               for code, period, report_date, announce_date, _record in updates]
    payload = {"generated_at": pd.Timestamp.now().isoformat(), "changed_records": records,
               "changed_symbols": sorted({item["symbol"] for item in records})}
    temp = CHANGE_MANIFEST_FP.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CHANGE_MANIFEST_FP)


# ── 从 gpcw zip 读取目标股票记录 ───────────────────────────────────────────
def read_stock_records_from_zip(zpath: Path, target_codes: set[str]) -> dict[str, dict]:
    """从 zip 中提取目标股票的数据记录。"""
    from mootdx.financial.financial import FinancialReader
    try:
        df = FinancialReader.to_data(str(zpath))
    except Exception:
        return {}

    if df.empty:
        return {}

    df = df.reset_index()
    code_col = df.columns[0]
    df = df.rename(columns={code_col: "code"})
    df["code"] = df["code"].astype(str).apply(canonical_code)

    # 清洗列名
    df.columns = [c.rsplit(".", 1)[0] if "." in c else c for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated(keep="first")]

    # 只保留目标股票
    df = df[df["code"].isin(target_codes)]
    if df.empty:
        return {}

    # 同代码取最新 report_date
    df = df.sort_values("report_date").drop_duplicates(subset="code", keep="last")
    df = df.set_index("code")

    result = {}
    for code, row in df.iterrows():
        rd = int(row.get("report_date", 0))
        ad = format_announce_date(row.get("财报公告日期", 0))
        if rd == 0 or pd.isna(rd):
            continue
        record = row.to_dict()
        record["code"] = code
        record["report_date"] = rd
        record["announce_date"] = ad
        result[code] = record
    return result


# ── Parquet 读写 ─────────────────────────────────────────────────────────────
def read_quarter_parquet(period: str) -> pd.DataFrame:
    fp = OUT_DIR / f"{period}.parquet"
    if not fp.exists():
        return pd.DataFrame()
    return pd.read_parquet(fp)


def append_to_quarter_parquet(period: str, new_records: list[dict]):
    """将新记录追加到已有季度文件（去重：同股票代码保留最新）。"""
    fp = OUT_DIR / f"{period}.parquet"
    if fp.exists():
        existing = pd.read_parquet(fp)
        new_df = pd.DataFrame(new_records).set_index("code")
        combined = pd.concat([existing, new_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.to_parquet(fp, index=True, engine="pyarrow", compression="snappy")
    else:
        df = pd.DataFrame(new_records).set_index("code")
        df.to_parquet(fp, index=True, engine="pyarrow", compression="snappy")
    size_kb = fp.stat().st_size / 1024
    print(f"  → {fp.name}: {len(new_records)} 条新记录, 总 {size_kb:.0f} KB")


# ── 增量检测（修复版）────────────────────────────────────────────────────────
def detect_updates(meta: dict) -> list[tuple[str, str, int, int, dict]]:
    """检测哪些股票有新的财报。

    修复：所有 zip 收集完毕后统一去重，写入 meta 前不更新 meta 状态，
    确保同股票多 period 都能被正确写入各自的 parquet 文件。

    Returns:
        [(code, new_period, report_date, announce_date, full_record), ...]
    """
    # 保存原始 meta 状态用于候选判断（不依赖写入中间态）
    orig_latest: dict[str, str] = {
        code: info["latest_period"]
        for code, info in meta["stocks"].items()
        if info.get("latest_period")
    }

    # 扫描最新 5 个 zip
    zips = sorted(TDX_CW.glob("gpcw*.zip"), reverse=True)[:5]

    all_records: list[tuple[str, str, int, int, dict]] = []

    for zpath in zips:
        zip_period_str = parse_period(int(zpath.stem[-8:]))
        print(f"  扫描 {zpath.name} (zip_period={zip_period_str})", end=" ... ", flush=True)

        # Include equal-period stocks as well: a later announcement date for the
        # same report period is a correction and must refresh derived health data.
        candidates = {
            code: latest
            for code, latest in orig_latest.items()
            if _period_order(latest) <= _period_order(zip_period_str)
        }
        if not candidates:
            print("无候选股票")
            continue

        records = read_stock_records_from_zip(zpath, set(candidates.keys()))
        print(f"获取 {len(records)} 条记录", end="", flush=True)

        found = 0
        for code, record in records.items():
            rd = record["report_date"]
            ad = record["announce_date"]
            new_period = parse_period(int(rd))
            orig_prev = orig_latest.get(code, "")
            # Accept a genuinely newer report or a newer announcement for the
            # same report period (financial corrections/restatements).
            known_period = (meta.get("stocks", {}).get(code, {}).get("periods", {}).get(new_period, {}) or {})
            known_announce = int(known_period.get("announce_date") or 0)
            is_new_period = _period_order(new_period) > _period_order(orig_prev)
            is_revision = new_period == orig_prev and ad > known_announce
            if is_new_period or is_revision:
                all_records.append((code, new_period, rd, ad, record))
                found += 1

        print(f", 其中 {found} 条为新增记录")

    # 去重策略：同 (code, period) 保留 announce_date 最新的一条
    # 允许同一只股票保留多个不同 period 的记录
    def record_key(x):
        code, period, rd, ad, _ = x
        return (code, period, -ad, -rd)

    all_records.sort(key=record_key)
    seen: dict[tuple[str, str], bool] = {}
    updates: list[tuple[str, str, int, int, dict]] = []
    for rec in all_records:
        code, period = rec[0], rec[1]
        if (code, period) not in seen:
            seen[(code, period)] = True
            updates.append(rec)

    return updates


# ── Snapshot rebuild ──────────────────────────────────────────────────────────
SNAPSHOT_SCRIPT = PROJECT / "scripts/build_financial_snapshot_from_warehouse.py"


def rebuild_snapshot(period: str = "latest"):
    """Call the warehouse-based snapshot builder to regenerate a snapshot."""
    import subprocess
    cmd = [
        sys.executable, str(SNAPSHOT_SCRIPT), period,
    ]
    print(f"\n=== 重建快照: {period} ===")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"快照重建失败:\n{result.stderr}", file=sys.stderr)
        return False
    print(result.stdout)
    return True


def rebuild_latest_snapshot_or_raise() -> None:
    if not rebuild_snapshot("latest"):
        raise RuntimeError("financial_snapshot_latest publication failed")


# ── Main流程 ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检测，不写入")
    ap.add_argument("--full", action="store_true", help="全量重建模式（调用 builder）")
    ap.add_argument("--rebuild-period", type=str, default=None,
                    help="重建指定报告期的快照（如 2025A, latest）")
    ap.add_argument("--refresh-period", type=str, default=None,
                    help="从当前CW包整期原子替换Parquet并重建快照（如 2026Q3）")
    ap.add_argument("--allow-large-deletion", action="store_true",
                    help="仅人工确认后允许整期刷新突破旧仓删除阈值；不绕过最低行数和代码格式")
    ap.add_argument("--preserve-missing-code", action="append", default=[],
                    help="显式保留源包漏失的旧仓代码；可重复，仅用于已审计的上游缺失例外")
    args = ap.parse_args()

    # 单独重建快照模式
    if args.rebuild_period:
        ok = rebuild_snapshot(args.rebuild_period)
        sys.exit(0 if ok else 1)

    print("增量更新财务时间序列\n")
    meta = load_meta()
    print(f"Meta: {meta['stock_count']} 只股票, last_updated={meta.get('last_updated', 'N/A')}\n")

    if args.full:
        print("[FULL MODE] 请使用 financial_ts_builder.py 进行全量重建")
        sys.exit(0)

    if args.refresh_period:
        package = _source_package_for_period(args.refresh_period)
        if args.dry_run:
            print(f"[DRY RUN] 将整期刷新 {args.refresh_period}: {package}")
            sys.exit(0)
        result = refresh_period_from_package(
            meta,
            package,
            allow_large_deletion=args.allow_large_deletion,
            preserve_missing_codes=set(args.preserve_missing_code),
        )
        save_meta(meta)
        print(
            f"整期刷新完成: {result['period']} rows={result['rows']} "
            f"changed={len(result['changed_symbols'])} coverage={result['coverage']}"
        )
        rebuild_latest_snapshot_or_raise()
        finalize_refresh_publication(
            meta, [result], _manifest_updates_for_refresh(meta, result),
        )
        sys.exit(0)

    # 增量检测
    print("=== 检测新财报 ===")
    t0 = time.time()
    all_packages = list(TDX_CW.glob("gpcw*.zip"))
    scanned_packages = source_packages_to_scan(meta, all_packages)
    revised_packages = changed_source_packages(meta, scanned_packages)
    if args.dry_run and revised_packages:
        for item in revised_packages:
            print(f"  同名包内容变化: {item['path'].name} -> {item['period']}")
    refresh_results = []
    if not args.dry_run:
        for item in revised_packages:
            print(f"  整期刷新同名修订包: {item['path'].name}")
            refresh_results.append(refresh_period_from_package(meta, item["path"]))
    updates = detect_updates(meta)
    print(f"\n发现 {len(updates)} 只股票有新财报 (检测耗时 {time.time()-t0:.1f}s)\n")

    if not updates and not refresh_results:
        if not args.dry_run:
            _record_package_fingerprints(meta, scanned_packages)
            save_meta(meta)
            write_change_manifest([])
        print("无需更新，退出")
        sys.exit(0)

    if args.dry_run:
        print("=== DRY RUN ===")
        for code, period, rd, ad, _ in sorted(updates, key=lambda x: x[1], reverse=True):
            prev = meta["stocks"].get(code, {}).get("latest_period", "N/A")
            print(f"  {code}: {prev} → {period} (report_date={rd}, announce={ad})")
        sys.exit(0)

    # 增量写入：按 period 从旧到新写（确保新 period 数据不覆盖旧 period）
    # 关键：所有 parquet 写完之前不更新 meta，避免写入中间态影响判断
    print("=== 写入更新 ===")
    by_period: dict[str, list[dict]] = defaultdict(list)
    for code, period, rd, ad, record in updates:
        by_period[period].append(record)

    for period, records in sorted(by_period.items(), key=lambda x: _period_order(x[0])):
        append_to_quarter_parquet(period, records)

    # 所有 parquet 写入完毕后再一次性更新 meta
    for code, period, rd, ad, record in updates:
        if code not in meta["stocks"]:
            meta["stocks"][code] = {"name": "", "periods": {}, "latest_period": ""}
        period_key = period
        if period_key not in meta["stocks"][code]["periods"]:
            meta["stocks"][code]["periods"][period_key] = {
                "report_date": rd,
                "announce_date": ad,
                "file": f"{period_key}.parquet",
            }
        prev = meta["stocks"][code]["latest_period"]
        if _period_order(period_key) >= _period_order(prev):
            meta["stocks"][code]["latest_period"] = period_key

    _record_package_fingerprints(meta, scanned_packages)
    save_meta(meta)
    refresh_updates = [item for result in refresh_results
                       for item in _manifest_updates_for_refresh(meta, result)]
    print(f"\nMeta 已更新: {meta['stock_count']} 只股票")
    print(f"本次新增 {len(updates)} 条股票-报告期记录")

    # 重建最新期快照
    # 找出本次更新涉及的最新年份
    changed_periods = [u[1] for u in updates] + [str(result["period"]) for result in refresh_results]
    if changed_periods:
        rebuild_latest_snapshot_or_raise()
        finalize_refresh_publication(meta, refresh_results, updates + refresh_updates)


if __name__ == "__main__":
    main()
