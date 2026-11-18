"""Conservative explanatory labels for v5 swing states; not a probability or trading signal.

No four/five-star assertions: the research never validated those strengths.  A
missing/stale observation is UNKNOWN, never a neutral zero-star state.
"""
from __future__ import annotations

STARS_BY_STATE = {
    '上涨突破': ('bull', 3),
    '高点上移型上行': ('neutral', 0),
    '低点抬升型上行': ('bull', 2),
    '收敛／突破上行': ('bull', 2),
    '上涨回撤': ('neutral', 0),
    '较高波谷已确认（待突破）': ('bull', 1),
    '原正统下行／突破最近峰（反转候选）': ('bull', 1),
    '原高点降低型下行形状／突破最近峰（反转候选）': ('bull', 1),
    '结构转换／混合': ('neutral', 0),
    '区间震荡': ('neutral', 0),
    '收敛／方向待确认': ('neutral', 0),
    '上涨止跌待确认': ('bull', 1),
    '下跌反弹': ('bear', 1),
    '下跌反弹见顶待确认': ('bear', 1),
    '较低波峰已确认（待破位）': ('bear', 1),
    '原正统上行／跌破最近谷（反转候选）': ('bear', 1),
    '原低点抬升型上行形状／跌破最近谷（反转候选）': ('bear', 1),
    '高点降低型下行': ('bear', 2),
    '低点下移型下行': ('bear', 2),
    '收敛／破位下行': ('bear', 2),
    '下跌破位': ('bear', 3),
    '证据不足': ('unknown', 0),
}


def presentation(stock: dict) -> dict:
    if stock.get('status') != 'ok' or stock.get('state') not in STARS_BY_STATE or stock.get('state') == '证据不足':
        return {'tendency': 'unknown', 'star_count': None, 'stars': '未知',
                'disclosure': '前复权日线缺失、过期或结构证据不足；不能沿用旧评级。'}
    tendency, count = STARS_BY_STATE[stock['state']]
    if tendency == 'bull' and stock.get('new_low_risk'):
        return {'tendency': 'caution', 'star_count': None, 'stars': '星级暂缓',
                'underlying_rating': {'tendency': tendency, 'star_count': count},
                'disclosure': '已确认主状态保留，但出现低于最近确认谷的未确认新低；利多星级暂缓，不等于已确认下行。'}
    return {'tendency': tendency, 'star_count': count,
            'stars': ('★' if tendency == 'bull' else '☆') * count or '—',
            'disclosure': '仅表示确认峰谷结构倾向，不是上涨概率或买卖建议；最高展示5颗但目前没有4/5星证据。'}
