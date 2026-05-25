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


# ── Additional single-bar ──────────────────────────────────────────────────

def _spinning_top(bar):
    """纺锤线：小实体，上下影线均较长"""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0:
        return False
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return 0.1 < body / total < 0.4 and upper > body and lower > body


def _long_upper_shadow(bar):
    """长上影：上影线 > 实体×2 且 下影线很短"""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0 or body == 0:
        return False
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return upper > body * 2 and lower < body * 0.5


def _long_lower_shadow(bar):
    """长下影：下影线 > 实体×2 且 上影线很短"""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0 or body == 0:
        return False
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return lower > body * 2 and upper < body * 0.5


def _belt_hold_bullish(bar):
    """看涨执带：光头阳线且低开（开盘即最低）"""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    if c <= o:
        return False
    total = h - l
    lower = _lower_shadow(o, c, l)
    upper = _upper_shadow(h, o, c)
    return total > 0 and lower < total * 0.1 and upper > total * 0.05 and (o - l) < total * 0.05


def _belt_hold_bearish(bar):
    """看跌执带：光头阴线且高开（开盘即最高）"""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    if c >= o:
        return False
    total = h - l
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return total > 0 and upper < total * 0.1 and lower > total * 0.05 and (h - o) < total * 0.05


# ── Additional two-bar ─────────────────────────────────────────────────────

def _harami_bullish(prev, curr):
    """看涨孕线：昨日大阴线，今日小阳线被昨日实体完全包住"""
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    prev_body = _body(po, pc)
    curr_body = _body(co, cc)
    if prev_body == 0 or curr_body == 0:
        return False
    if not (pc < po):  # prev bearish
        return False
    if not (cc > co):  # curr bullish
        return False
    return co > pc and cc < po and curr_body < prev_body * 0.6


def _harami_bearish(prev, curr):
    """看跌孕线：昨日大阳线，今日小阴线被昨日实体完全包住"""
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    prev_body = _body(po, pc)
    curr_body = _body(co, cc)
    if prev_body == 0 or curr_body == 0:
        return False
    if not (pc > po):  # prev bullish
        return False
    if not (cc < co):  # curr bearish
        return False
    return co < pc and cc > po and curr_body < prev_body * 0.6


def _harami_cross(prev, curr):
    """十字孕线：昨日大实体，今日十字星被包住"""
    po, pc = prev["open"], prev["close"]
    co, cc, ch, cl = curr["open"], curr["close"], curr["high"], curr["low"]
    prev_body = _body(po, pc)
    curr_body = _body(co, cc)
    if prev_body == 0:
        return False
    total = ch - cl
    if total == 0:
        return False
    is_doji = curr_body / total < 0.1
    if not is_doji:
        return False
    return max(co, cc) < max(po, pc) and min(co, cc) > min(po, pc)


def _tweezers_top(prev, curr):
    """平头顶：两根K线最高价几乎相同"""
    return abs(curr["high"] - prev["high"]) / max(curr["high"], 0.01) < 0.005 and curr["close"] < curr["open"]


def _tweezers_bottom(prev, curr):
    """平头底：两根K线最低价几乎相同"""
    return abs(curr["low"] - prev["low"]) / max(curr["low"], 0.01) < 0.005 and curr["close"] > curr["open"]


def _kicking_bullish(prev, curr):
    """看涨分离：昨日大阴线(marubozu)，今日跳空高开大阳线(marubozu)"""
    po, pc, ph, pl = prev["open"], prev["close"], prev["high"], prev["low"]
    co, cc, ch, cl = curr["open"], curr["close"], curr["high"], curr["low"]
    prev_body = _body(po, pc)
    curr_body = _body(co, cc)
    prev_total = ph - pl
    curr_total = ch - cl
    if prev_total == 0 or curr_total == 0:
        return False
    prev_maru = prev_body / prev_total > 0.8
    curr_maru = curr_body / curr_total > 0.8
    return prev_maru and curr_maru and pc < po and cc > co and co > pc


def _kicking_bearish(prev, curr):
    """看跌分离：昨日大阳线，今日跳空低开大阴线"""
    po, pc, ph, pl = prev["open"], prev["close"], prev["high"], prev["low"]
    co, cc, ch, cl = curr["open"], curr["close"], curr["high"], curr["low"]
    prev_body = _body(po, pc)
    curr_body = _body(co, cc)
    prev_total = ph - pl
    curr_total = ch - cl
    if prev_total == 0 or curr_total == 0:
        return False
    prev_maru = prev_body / prev_total > 0.8
    curr_maru = curr_body / curr_total > 0.8
    return prev_maru and curr_maru and pc > po and cc < co and co < pc


# ── Additional three-bar ────────────────────────────────────────────────────

def _morning_doji_star(b1, b2, b3):
    """十字启明星：阴线 → 十字星(跳空低) → 阳线(跳空高)，类似晨星但中间是十字"""
    if not (b1["close"] < b1["open"]):
        return False
    b2_body = _body(b2["open"], b2["close"])
    b2_total = b2["high"] - b2["low"]
    if b2_total == 0:
        return False
    if b2_body / b2_total > 0.1:  # middle must be doji
        return False
    if not (b3["close"] > b3["open"]):
        return False
    mid1 = (b1["open"] + b1["close"]) / 2
    gap_down = max(b2["open"], b2["close"]) < b1["close"]
    gap_up = min(b3["open"], b3["close"]) > max(b2["open"], b2["close"])
    return b3["close"] > mid1 and (gap_down or gap_up)


def _evening_doji_star(b1, b2, b3):
    """十字暮星：阳线 → 十字星(跳空高) → 阴线(跳空低)"""
    if not (b1["close"] > b1["open"]):
        return False
    b2_body = _body(b2["open"], b2["close"])
    b2_total = b2["high"] - b2["low"]
    if b2_total == 0:
        return False
    if b2_body / b2_total > 0.1:
        return False
    if not (b3["close"] < b3["open"]):
        return False
    mid1 = (b1["open"] + b1["close"]) / 2
    return b3["close"] < mid1


def _abandoned_baby_bullish(b1, b2, b3):
    """弃婴底部：阴线 → 十字星(跳空低，与前后都有缺口) → 阳线(跳空高)"""
    if not (b1["close"] < b1["open"]):
        return False
    b2_body = _body(b2["open"], b2["close"])
    b2_total = b2["high"] - b2["low"]
    if b2_total == 0:
        return False
    if b2_body / b2_total > 0.1:
        return False
    if not (b3["close"] > b3["open"]):
        return False
    # Gap down: b2 high < b1 low, Gap up: b3 low > b2 high
    if b2["high"] >= b1["low"] or b3["low"] <= b2["high"]:
        return False
    return b3["close"] > (b1["open"] + b1["close"]) / 2


def _abandoned_baby_bearish(b1, b2, b3):
    """弃婴顶部：阳线 → 十字星(跳空高，与前后都有缺口) → 阴线(跳空低)"""
    if not (b1["close"] > b1["open"]):
        return False
    b2_body = _body(b2["open"], b2["close"])
    b2_total = b2["high"] - b2["low"]
    if b2_total == 0:
        return False
    if b2_body / b2_total > 0.1:
        return False
    if not (b3["close"] < b3["open"]):
        return False
    if b2["low"] <= b1["high"] or b3["high"] >= b2["low"]:
        return False
    return b3["close"] < (b1["open"] + b1["close"]) / 2


def _three_stars_south(b1, b2, b3):
    """南方三星：连续三日阴线，每日实体缩小、最低价抬高"""
    if not (b3["close"] < b3["open"] and b2["close"] < b2["open"] and b1["close"] < b1["open"]):
        return False
    body3 = _body(b3["open"], b3["close"])
    body2 = _body(b2["open"], b2["close"])
    body1 = _body(b1["open"], b1["close"])
    return body1 < body2 < body3 and b1["low"] > b2["low"] > b3["low"]


def _advance_block(b1, b2, b3):
    """前进受阻：连续三日阳线，但每日实体缩小、上影渐长"""
    if not (b3["close"] > b3["open"] and b2["close"] > b2["open"] and b1["close"] > b1["open"]):
        return False
    body3 = _body(b3["open"], b3["close"])
    body2 = _body(b2["open"], b2["close"])
    body1 = _body(b1["open"], b1["close"])
    upper3 = _upper_shadow(b3["high"], b3["open"], b3["close"])
    upper2 = _upper_shadow(b2["high"], b2["open"], b2["close"])
    upper1 = _upper_shadow(b1["high"], b1["open"], b1["close"])
    return body1 < body2 < body3 and upper1 > upper2 > upper3


def _stalled_pattern(b1, b2, b3):
    """停顿形态：前两根强阳线，第三根小阳线(实体在第二根上影线内)"""
    if not (b3["close"] > b3["open"] and b2["close"] > b2["open"]):
        return False
    body2 = _body(b2["open"], b2["close"])
    body1 = _body(b1["open"], b1["close"])
    if body1 == 0:
        return False
    # b1 is much smaller than b2, and b1's body is within b2's upper shadow
    return body1 < body2 * 0.5 and b1["open"] > b2["close"] and b1["close"] < b2["high"]


# ── Public API ──────────────────────────────────────────────────────────────

PATTERNS = [
    # ── Single-bar ──
    ("十字星", _doji, 1, "neutral"),
    ("纺锤线", _spinning_top, 1, "neutral"),
    ("锤子线", _hammer, 1, "bullish"),
    ("倒锤子", _inverted_hammer, 1, "bearish"),
    ("长上影", _long_upper_shadow, 1, "bearish"),
    ("长下影", _long_lower_shadow, 1, "bullish"),
    ("光头阳线", _marubozu_bullish, 1, "bullish"),
    ("光头阴线", _marubozu_bearish, 1, "bearish"),
    ("蜻蜓十字", _dragonfly_doji, 1, "bullish"),
    ("墓碑十字", _gravestone_doji, 1, "bearish"),
    ("看涨执带", _belt_hold_bullish, 1, "bullish"),
    ("看跌执带", _belt_hold_bearish, 1, "bearish"),
    # ── Two-bar ──
    ("看涨吞没", _bullish_engulfing, 2, "bullish"),
    ("看跌吞没", _bearish_engulfing, 2, "bearish"),
    ("刺透形态", _piercing_line, 2, "bullish"),
    ("乌云盖顶", _dark_cloud_cover, 2, "bearish"),
    ("看涨孕线", _harami_bullish, 2, "bullish"),
    ("看跌孕线", _harami_bearish, 2, "bearish"),
    ("十字孕线", _harami_cross, 2, "bearish"),
    ("平头顶", _tweezers_top, 2, "bearish"),
    ("平头底", _tweezers_bottom, 2, "bullish"),
    ("看涨分离", _kicking_bullish, 2, "bullish"),
    ("看跌分离", _kicking_bearish, 2, "bearish"),
    # ── Three-bar ──
    ("晨星", _morning_star, 3, "bullish"),
    ("暮星", _evening_star, 3, "bearish"),
    ("十字启明星", _morning_doji_star, 3, "bullish"),
    ("十字暮星", _evening_doji_star, 3, "bearish"),
    ("弃婴底部", _abandoned_baby_bullish, 3, "bullish"),
    ("弃婴顶部", _abandoned_baby_bearish, 3, "bearish"),
    ("红三兵", _three_white_soldiers, 3, "bullish"),
    ("三只乌鸦", _three_black_crows, 3, "bearish"),
    ("南方三星", _three_stars_south, 3, "bullish"),
    ("前进受阻", _advance_block, 3, "bearish"),
    ("停顿形态", _stalled_pattern, 3, "bearish"),
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
