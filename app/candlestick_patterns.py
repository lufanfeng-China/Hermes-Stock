"""Pure-Python candlestick pattern recognition (no TA-Lib dependency).

Each pattern function receives the raw bar dicts: latest first, oldest last.
"""


def _body(o, c):
    return abs(c - o)


def _upper_shadow(h, o, c):
    return h - max(o, c)


def _lower_shadow(o, c, l):
    return min(o, c) - l


# ── Single-bar patterns ────────────────────────────────────────────────────

def _doji(bar):
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0:
        return False
    return body / total < 0.1


def _hammer(bar):
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0 or body == 0:
        return False
    lower = _lower_shadow(o, c, l)
    upper = _upper_shadow(h, o, c)
    return lower >= body * 2 and upper < total * 0.3


def _inverted_hammer(bar):
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0 or body == 0:
        return False
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return upper >= body * 2 and lower < total * 0.3


def _marubozu_bullish(bar):
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    if c <= o:
        return False
    body = _body(o, c)
    total = h - l
    return total == 0 or body / total > 0.9


def _marubozu_bearish(bar):
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    if c >= o:
        return False
    body = _body(o, c)
    total = h - l
    return total == 0 or body / total > 0.9


def _dragonfly_doji(bar):
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0:
        return False
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return body / total < 0.05 and upper < total * 0.05 and lower > total * 0.6


def _gravestone_doji(bar):
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0:
        return False
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return body / total < 0.05 and lower < total * 0.05 and upper > total * 0.6


# ── Two-bar patterns ────────────────────────────────────────────────────────

def _bullish_engulfing(prev, curr):
    po, pc, ph, pl = prev["open"], prev["close"], prev["high"], prev["low"]
    co, cc, ch, cl = curr["open"], curr["close"], curr["high"], curr["low"]
    if not (pc < po):  # prev bearish
        return False
    if not (cc > co):  # curr bullish
        return False
    return co < pc and cc > po


def _bearish_engulfing(prev, curr):
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    if not (pc > po):  # prev bullish
        return False
    if not (cc < co):  # curr bearish
        return False
    return co > pc and cc < po


def _piercing_line(prev, curr):
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    if not (pc < po):  # prev bearish
        return False
    if not (cc > co):  # curr bullish
        return False
    if co > pc:  # must open at or below prev close
        return False
    mid = (po + pc) / 2
    return cc > mid


def _dark_cloud_cover(prev, curr):
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    if not (pc > po):  # prev bullish
        return False
    if not (cc < co):  # curr bearish
        return False
    if co < pc:  # must open at or above prev close
        return False
    mid = (po + pc) / 2
    return cc < mid


# ── Three-bar patterns ──────────────────────────────────────────────────────

def _morning_star(b1, b2, b3):
    """b1=oldest, b2=middle, b3=latest"""
    if not (b1["close"] < b1["open"]):  # day1 bearish
        return False
    mid1 = (b1["open"] + b1["close"]) / 2
    if _body(b2["open"], b2["close"]) / max(_body(b1["open"], b1["close"]), 0.001) > 0.5:
        return False
    if not (b3["close"] > b3["open"]):  # day3 bullish
        return False
    return b3["close"] > mid1


def _evening_star(b1, b2, b3):
    if not (b1["close"] > b1["open"]):  # day1 bullish
        return False
    mid1 = (b1["open"] + b1["close"]) / 2
    if _body(b2["open"], b2["close"]) / max(_body(b1["open"], b1["close"]), 0.001) > 0.5:
        return False
    if not (b3["close"] < b3["open"]):  # day3 bearish
        return False
    return b3["close"] < mid1


def _three_white_soldiers(b1, b2, b3):
    if not (b3["close"] > b3["open"] and b2["close"] > b2["open"] and b1["close"] > b1["open"]):
        return False
    return b1["close"] > b2["close"] > b3["close"]


def _three_black_crows(b1, b2, b3):
    if not (b3["close"] < b3["open"] and b2["close"] < b2["open"] and b1["close"] < b1["open"]):
        return False
    return b1["close"] < b2["close"] < b3["close"]


# ── Public API ──────────────────────────────────────────────────────────────

PATTERNS = [
    # Single-bar
    ("十字星", _doji, 1, "neutral"),
    ("锤子线", _hammer, 1, "bullish"),
    ("倒锤子", _inverted_hammer, 1, "bearish"),
    ("光头阳线", _marubozu_bullish, 1, "bullish"),
    ("光头阴线", _marubozu_bearish, 1, "bearish"),
    ("蜻蜓十字", _dragonfly_doji, 1, "bullish"),
    ("墓碑十字", _gravestone_doji, 1, "bearish"),
    # Two-bar
    ("看涨吞没", _bullish_engulfing, 2, "bullish"),
    ("看跌吞没", _bearish_engulfing, 2, "bearish"),
    ("刺透形态", _piercing_line, 2, "bullish"),
    ("乌云盖顶", _dark_cloud_cover, 2, "bearish"),
    # Three-bar
    ("晨星", _morning_star, 3, "bullish"),
    ("暮星", _evening_star, 3, "bearish"),
    ("红三兵", _three_white_soldiers, 3, "bullish"),
    ("三只乌鸦", _three_black_crows, 3, "bearish"),
]


def detect_latest_pattern(bars: list[dict]) -> dict | None:
    """Return the most recent candlestick pattern at the last bar, or None."""
    n = len(bars)
    for name, fn, lookback, direction in PATTERNS:
        if n < lookback:
            continue
        try:
            if lookback == 1:
                if fn(bars[-1]):
                    return {"name": name, "direction": direction}
            elif lookback == 2:
                if fn(bars[-2], bars[-1]):
                    return {"name": name, "direction": direction}
            elif lookback == 3:
                if fn(bars[-3], bars[-2], bars[-1]):
                    return {"name": name, "direction": direction}
        except Exception:
            continue
    return None
