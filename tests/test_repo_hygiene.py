"""数据产物不进版本库：/data/ 下的快照、parquet、归档一律不跟踪。"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def test_no_derived_data_is_tracked():
    tracked = [line for line in git("ls-files", "data").splitlines() if line.strip()]
    assert tracked == [], f"数据产物不应入库（已跟踪 {len(tracked)} 个）：{tracked[:5]}"


def test_data_directory_is_ignored():
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/data/" in rules
    assert "*.parquet" in rules


def test_concept_temperature_snapshot_exists_on_disk_but_is_ignored():
    path = ROOT / "data" / "derived" / "datasets" / "final" / "dataset_concept_temperature_current.json"
    if not path.exists():
        return  # 未构建过的环境跳过
    assert path.stat().st_size > 0, "快照文件被清空了"
    ignored = subprocess.run(["git", "check-ignore", "-q", str(path.relative_to(ROOT))], cwd=ROOT)
    assert ignored.returncode == 0, "快照仍在跟踪范围内，.gitignore 没生效"
