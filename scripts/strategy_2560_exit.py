"""Exit-state rules shared by the 2560 strategy backtests."""


def exit_reason(*, armed: bool, pnl_pct: float, macd_dead_cross: bool) -> str | None:
    """Return the 2560 exit-state transition for the current closing bar.

    A position is armed only after its closing profit has reached +20%.  Before
    that point neither a MACD dead cross nor a +15% profit level exits it.
    Once armed, a MACD dead cross exits immediately; otherwise a retracement to
    +15% (inclusive) locks in the profit floor.
    """
    if not armed:
        return "armed" if pnl_pct >= 20.0 else None
    if macd_dead_cross:
        return "macd_dead_cross"
    if pnl_pct <= 15.0:
        return "profit_floor"
    return None
