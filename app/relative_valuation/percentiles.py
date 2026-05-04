from __future__ import annotations

from bisect import bisect_left


def compute_empirical_percentile(value: float | None, sample: list[float] | tuple[float, ...]) -> float | None:
    if value is None:
        return None
    values = sorted(float(item) for item in sample)
    count = len(values)
    if count == 0:
        return None
    if count == 1:
        return 100.0

    first_idx = bisect_left(values, float(value))
    if first_idx < count and values[first_idx] == float(value):
        last_idx = first_idx
        while last_idx + 1 < count and values[last_idx + 1] == float(value):
            last_idx += 1
        average_rank = ((first_idx + 1) + (last_idx + 1)) / 2.0
        return average_rank / count * 100.0

    insertion_rank = first_idx + 1
    if insertion_rank > count:
        insertion_rank = count
    return insertion_rank / count * 100.0


def should_warn_non_linear_high_percentile_risk(percentile: float | None) -> bool:
    return percentile is not None and percentile > 80.0
