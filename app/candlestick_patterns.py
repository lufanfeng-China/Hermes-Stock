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


# ── TA-Lib 61- parity: remaining patterns ────────────────────────────────────

def _high_wave(bar):
    """高浪线：上下影线都极长，实体很小"""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0:
        return False
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return body / total < 0.15 and upper > body * 3 and lower > body * 3


def _rickshaw_man(bar):
    """黄包车夫：十字星但上下影线都很长"""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0:
        return False
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return body / total < 0.05 and upper > total * 0.3 and lower > total * 0.3


def _closing_marubozu(bar):
    """收盘光头：无上影线，有下影线，实体大"""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    if c <= o:
        return False
    total = h - l
    if total == 0:
        return True
    upper = _upper_shadow(h, o, c)
    body = _body(o, c)
    return upper < total * 0.05 and body / total > 0.6


def _opening_marubozu(bar):
    """光脚开盘：无下影线，有上影线，实体大"""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    total = h - l
    if total == 0:
        return True
    lower = _lower_shadow(o, c, l)
    body = _body(o, c)
    return lower < total * 0.05 and body / total > 0.6 and c > o


# ── Two-bar additions ───────────────────────────────────────────────────────

def _on_neck(prev, curr):
    """颈上线：阴线后小阳线，收盘接近昨日最低价"""
    po, pc, pl = prev["open"], prev["close"], prev["low"]
    co, cc = curr["open"], curr["close"]
    if not (pc < po and cc > co):
        return False
    return abs(cc - pl) / max(pl, 0.01) < 0.01


def _in_neck(prev, curr):
    """入颈线：阴线后小阳线，收盘略高于昨日最低价但在实体下1/3内"""
    po, pc, pl = prev["open"], prev["close"], prev["low"]
    co, cc = curr["open"], curr["close"]
    if not (pc < po and cc > co):
        return False
    body_range = po - pc
    if body_range == 0:
        return False
    return pl < cc < pc - body_range * 0.66


def _thrusting(prev, curr):
    """插入线：阴线后阳线，收盘进入昨日实体但未过中点"""
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    if not (pc < po and cc > co):
        return False
    mid = (po + pc) / 2
    return co < pc and pc < cc < mid


def _matching_low(prev, curr):
    """相同低价：两根阴线，收盘价几乎相同"""
    if not (prev["close"] < prev["open"] and curr["close"] < curr["open"]):
        return False
    return abs(curr["close"] - prev["close"]) / max(abs(prev["close"]), 0.01) < 0.005


def _homing_pigeon(prev, curr):
    """家鸽：大阴线后小阴线被完全包住"""
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    if not (pc < po and cc < co):
        return False
    return co < po and cc > pc and _body(co, cc) < _body(po, pc) * 0.6


def _stick_sandwich(prev, curr):
    """棍夹：阳线 → 阴线回到起点 → 阳线回到高位(三根中的第一检测点是中间)"""
    # For 2-bar detection we check prev(bear) and curr(bull), 
    # the full 3-bar pattern is: bull → bear(back to open) → bull(back to high)
    if not (prev["close"] < prev["open"] and curr["close"] > curr["open"]):
        return False
    return abs(prev["close"] - curr["open"]) / max(abs(curr["open"]), 0.01) < 0.01


def _separating_lines_bull(prev, curr):
    """看涨分离线：阴线后跳空高开阳线，开盘=昨日开盘"""
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    if not (pc < po and cc > co):
        return False
    return abs(co - po) / max(po, 0.01) < 0.01 and co > pc


def _separating_lines_bear(prev, curr):
    """看跌分离线：阳线后跳空低开阴线，开盘=昨日开盘"""
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    if not (pc > po and cc < co):
        return False
    return abs(co - po) / max(po, 0.01) < 0.01 and co < pc


def _counter_attack_bull(prev, curr):
    """看涨反击线：大阴线后低开阳线，收盘接近昨日收盘"""
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    if not (pc < po and cc > co and co < pc):
        return False
    return abs(cc - pc) / max(abs(pc), 0.01) < 0.01


def _counter_attack_bear(prev, curr):
    """看跌反击线：大阳线后高开阴线，收盘接近昨日收盘"""
    po, pc = prev["open"], prev["close"]
    co, cc = curr["open"], curr["close"]
    if not (pc > po and cc < co and co > pc):
        return False
    return abs(cc - pc) / max(abs(pc), 0.01) < 0.01


# ── Three-bar additions ─────────────────────────────────────────────────────

def _three_inside_up(b1, b2, b3):
    """内部三阳：阴线 → 看涨孕线 → 阳线确认（收盘高于第一根开盘）"""
    if not (b1["close"] < b1["open"]):
        return False
    if not _harami_bullish(b1, b2):
        return False
    if not (b3["close"] > b3["open"]):
        return False
    return b3["close"] > b1["open"]


def _three_inside_down(b1, b2, b3):
    """内部三阴：阳线 → 看跌孕线 → 阴线确认"""
    if not (b1["close"] > b1["open"]):
        return False
    if not _harami_bearish(b1, b2):
        return False
    if not (b3["close"] < b3["open"]):
        return False
    return b3["close"] < b1["open"]


def _three_outside_up(b1, b2, b3):
    """外部三阳：阴线 → 看涨吞没 → 阳线确认（收盘继续走高）"""
    if not (b1["close"] < b1["open"]):
        return False
    if not _bullish_engulfing(b1, b2):
        return False
    if not (b3["close"] > b3["open"]):
        return False
    return b3["close"] > b2["close"]


def _three_outside_down(b1, b2, b3):
    """外部三阴：阳线 → 看跌吞没 → 阴线确认"""
    if not (b1["close"] > b1["open"]):
        return False
    if not _bearish_engulfing(b1, b2):
        return False
    if not (b3["close"] < b3["open"]):
        return False
    return b3["close"] < b2["close"]


def _upside_gap_two_crows(b1, b2, b3):
    """向上跳空双鸦：阳线 → 跳空高开阴线 → 阴线吞没第二根(开盘更高收盘更低)"""
    if not (b1["close"] > b1["open"]):
        return False
    if not (b2["close"] < b2["open"] and b2["open"] > b1["close"]):
        return False
    if not (b3["close"] < b3["open"]):
        return False
    return b3["open"] > b2["open"] and b3["close"] < b2["close"]


def _side_by_side_white_bull(b1, b2, b3):
    """并列阳线看涨：阳线 → 跳空高开 → 两根并列小阳线"""
    if not (b1["close"] > b1["open"]):
        return False
    if not (b2["close"] > b2["open"] and b2["open"] > b1["close"]):
        return False
    if not (b3["close"] > b3["open"]):
        return False
    return abs(b3["open"] - b2["open"]) / max(b2["open"], 0.01) < 0.01


def _side_by_side_white_bear(b1, b2, b3):
    """并列阳线看跌：阴线 → 跳空低开 → 两根并列小阳线"""
    if not (b1["close"] < b1["open"]):
        return False
    if not (b2["close"] > b2["open"] and b2["open"] < b1["close"]):
        return False
    if not (b3["close"] > b3["open"]):
        return False
    return abs(b3["open"] - b2["open"]) / max(b2["open"], 0.01) < 0.01


def _downside_gap_three(b1, b2, b3):
    """向下跳空三法：阴线 → 跳空低开 → 三根小阳线不补缺口 → 阴线新低(简化:检查前3根)"""
    if not (b1["close"] < b1["open"]):
        return False
    if not (b2["open"] < b1["low"]):  # gap down
        return False
    if not (b3["close"] > b3["open"]):
        return False
    return b3["high"] < b1["low"]  # gap not filled


def _breakaway_bull(b1, b2, b3):
    """脱离看涨：长阴线 → 跳空低开小阴 → 跳空低开最后大阳线"""
    body1 = _body(b1["open"], b1["close"])
    if not (b1["close"] < b1["open"] and body1 > 0):
        return False
    if not (b2["close"] < b2["open"] and b2["high"] < b1["low"]):
        return False
    return b3["close"] > b3["open"]


def _breakaway_bear(b1, b2, b3):
    """脱离看跌：长阳线 → 跳空高开小阳 → 跳空高开最后大阴线"""
    body1 = _body(b1["open"], b1["close"])
    if not (b1["close"] > b1["open"] and body1 > 0):
        return False
    if not (b2["close"] > b2["open"] and b2["low"] > b1["high"]):
        return False
    return b3["close"] < b3["open"]


def _unique_three_river(b1, b2, b3):
    """独特三河底：阴线 → 锤子线(新低) → 小阳线(未过锤子实体)"""
    if not (b1["close"] < b1["open"]):
        return False
    if not _hammer(b2):
        return False
    if b2["low"] >= b1["low"]:  # must make new low
        return False
    if not (b3["close"] > b3["open"]):
        return False
    b2_body_high = max(b2["open"], b2["close"])
    return b3["close"] < b2_body_high  # hasn't broken above hammer body yet


def _three_stars(b1, b2, b3):
    """三星：三根十字星，中间十字跳空"""
    for b in [b1, b2, b3]:
        body = _body(b["open"], b["close"])
        total = b["high"] - b["low"]
        if total == 0 or body / total > 0.1:
            return False
    return b2["high"] < b1["low"] or b2["low"] > b1["high"]


def _tasuki_gap_bull(b1, b2, b3):
    """向上跳空并列：阳线 → 跳空高开阳线 → 阴线回补但未补缺口"""
    if not (b1["close"] > b1["open"]):
        return False
    if not (b2["close"] > b2["open"] and b2["low"] > b1["high"]):  # gap up
        return False
    if not (b3["close"] < b3["open"]):  # 3rd bearish
        return False
    return b3["close"] > b1["high"]  # didn't fill gap


def _tasuki_gap_bear(b1, b2, b3):
    """向下跳空并列：阴线 → 跳空低开阴线 → 阳线反弹但未补缺口"""
    if not (b1["close"] < b1["open"]):
        return False
    if not (b2["close"] < b2["open"] and b2["high"] < b1["low"]):
        return False
    if not (b3["close"] > b3["open"]):
        return False
    return b3["close"] < b1["low"]


# ── Fallback: bar classification (always matches) ─────────────────────────

def _bar_type(bar):
    """Classify every bar into a type. Returns (name, direction)."""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    total = h - l
    if total == 0:
        return ("一字平盘", "neutral")
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    body_ratio = body / total
    bullish = c > o

    if body_ratio > 0.7:
        if upper < total * 0.05 and lower < total * 0.05:
            return ("大阳线", "bullish") if bullish else ("大阴线", "bearish")
    if body_ratio > 0.4:
        if upper > body and lower < body * 0.3:
            return ("光脚阳线", "bullish") if bullish else ("光脚阴线", "bearish")
        if lower > body and upper < body * 0.3:
            return ("光头阳线", "bullish") if bullish else ("光头阴线", "bearish")
    if upper > body * 2.5 and lower < body * 0.3:
        return ("长上影阳", "bearish") if bullish else ("长上影阴", "bearish")
    if lower > body * 2.5 and upper < body * 0.3:
        return ("长下影阳", "bullish") if bullish else ("长下影阴", "bullish")
    if body_ratio < 0.2 and upper > total * 0.3 and lower > total * 0.3:
        return ("十字星", "neutral")
    if body_ratio < 0.3:
        return ("小阳线", "bullish") if bullish else ("小阴线", "bearish")
    if upper > lower * 1.5:
        return ("上影阳线", "bearish") if bullish else ("上影阴线", "bearish")
    if lower > upper * 1.5:
        return ("下影阳线", "bullish") if bullish else ("下影阴线", "bullish")
    return ("阳线", "bullish") if bullish else ("阴线", "bearish")


# ── Public API ──────────────────────────────────────────────────────────────

PATTERNS = [
    # ── Single-bar ──
    ("十字星", _doji, 1, "neutral"),
    ("纺锤线", _spinning_top, 1, "neutral"),
    ("高浪线", _high_wave, 1, "neutral"),
    ("黄包车夫", _rickshaw_man, 1, "neutral"),
    ("锤子线", _hammer, 1, "bullish"),
    ("倒锤子", _inverted_hammer, 1, "bearish"),
    ("长上影", _long_upper_shadow, 1, "bearish"),
    ("长下影", _long_lower_shadow, 1, "bullish"),
    ("光头阳线", _marubozu_bullish, 1, "bullish"),
    ("光头阴线", _marubozu_bearish, 1, "bearish"),
    ("收盘光头", _closing_marubozu, 1, "bullish"),
    ("光脚开盘", _opening_marubozu, 1, "bullish"),
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
    ("颈上线", _on_neck, 2, "bearish"),
    ("入颈线", _in_neck, 2, "bearish"),
    ("插入线", _thrusting, 2, "bearish"),
    ("相同低价", _matching_low, 2, "bullish"),
    ("家鸽", _homing_pigeon, 2, "bullish"),
    ("棍夹", _stick_sandwich, 2, "bullish"),
    ("看涨分离线", _separating_lines_bull, 2, "bullish"),
    ("看跌分离线", _separating_lines_bear, 2, "bearish"),
    ("看涨反击", _counter_attack_bull, 2, "bullish"),
    ("看跌反击", _counter_attack_bear, 2, "bearish"),
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
    ("内部三阳", _three_inside_up, 3, "bullish"),
    ("内部三阴", _three_inside_down, 3, "bearish"),
    ("外部三阳", _three_outside_up, 3, "bullish"),
    ("外部三阴", _three_outside_down, 3, "bearish"),
    ("跳空双鸦", _upside_gap_two_crows, 3, "bearish"),
    ("并列阳线涨", _side_by_side_white_bull, 3, "bullish"),
    ("并列阳线跌", _side_by_side_white_bear, 3, "bearish"),
    ("向下跳空", _downside_gap_three, 3, "bearish"),
    ("脱离看涨", _breakaway_bull, 3, "bullish"),
    ("脱离看跌", _breakaway_bear, 3, "bearish"),
    ("独特三河", _unique_three_river, 3, "bullish"),
    ("三星", _three_stars, 3, "neutral"),
    ("向上跳空并列", _tasuki_gap_bull, 3, "bullish"),
    ("向下跳空并列", _tasuki_gap_bear, 3, "bearish"),
]


def detect_latest_pattern(bars: list[dict]) -> dict | None:
    """Return the most recent candlestick pattern at the last bar.
    Always returns a result — falls back to bar type classification."""
    n = len(bars)
    if n == 0:
        return None
    # Try specific patterns first
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
    # Fallback: classify the bar by its shape
    try:
        name, direction = _bar_type(bars[-1])
        return {"name": name, "direction": direction}
    except Exception:
        return None
