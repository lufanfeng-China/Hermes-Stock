# MA25-RPS Three-Position Short-Swing Baseline Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build and run a reproducible CSI300 baseline backtest for a maximum-three-position MA25 pullback + RPS short-swing strategy.

**Architecture:** A standalone versioned Python backtest will use Tongdaxin QFQ daily OHLCV only for technical signals and local raw daily bars for T+1 execution and MTM. It will read the RPS Parquet history and the current CSI300 constituent capture, simulate day-by-day with cash debits, slot limits, industry de-duplication, and next-open orders, then write versioned JSON/TXT reports to the desktop output directory.

**Tech Stack:** Python 3.12; pandas/numpy; mootdx; existing `app.tdx.qfq_kline`; local TDX data; Parquet.

---

### Task 1: Define and test deterministic candidate selection

**Objective:** Prove the ranking and industry de-duplication selects at most three distinct-industry candidates without inspecting future bars.

**Files:**
- Create: `tests/test_backtest_ma25_rps_three_position_v1.py`
- Create: `scripts/backtest_ma25_rps_three_position_csi300_v1.py`

**Step 1:** Write failing tests for: maximum-three selection, industry uniqueness, rank-score ordering, and a no-candidate case.

**Step 2:** Run the specific pytest command and confirm it fails because the module is absent.

**Step 3:** Implement minimal pure selection helpers.

**Step 4:** Re-run the test and require it to pass.

### Task 2: Define and test chronological order handling

**Objective:** Prove a close-time signal only creates a T+1 order, never executes at the signal close, and portfolio equity is always cash plus MTM market value.

**Files:**
- Modify: `tests/test_backtest_ma25_rps_three_position_v1.py`
- Modify: `scripts/backtest_ma25_rps_three_position_csi300_v1.py`

**Step 1:** Add a failing miniature-bar test for T+1 entry, three-slot cap, and cash-plus-market-value accounting.

**Step 2:** Run it and confirm failure.

**Step 3:** Implement the minimal event-loop helpers.

**Step 4:** Re-run focused tests and require they pass.

### Task 3: Implement data adapters and full strategy simulation

**Objective:** Connect current CSI300, QFQ technical signals, raw execution/MTM, RPS history, and the industry map under the declared strategy contract.

**Files:**
- Modify: `scripts/backtest_ma25_rps_three_position_csi300_v1.py`

**Contract:**
- Current CSI300 constituents only; disclose survivorship bias.
- QFQ signals: MA25 10-day slope >=0.5%; low within +/-3% of MA25; close >=MA25 and <=5% above; VMA5/VMA60 in [1.15,2.5]; bullish body >=50% of range; RPS20/50/120/250 each >=70.
- Signal at close, one candidate per stock; rank by RPS total, MA25 proximity, volume quality, and close strength; at most one per second-level industry and at most three holdings.
- T+1 raw open entry and raw close MTM; do not fall back from QFQ to raw for signals.
- Exit on a -6% close loss, two consecutive close<MA25, day-3 nonpositive close<MA10, 1/3 sells at +8% and +12%, final portion on close<MA10 or MACD death cross, day-7 return<+3%, or day-10 time exit. Each close trigger exits at next available raw open.
- Strict nonnegative cash and daily `equity == cash + market_value` assertions.

### Task 4: Run and audit the baseline

**Objective:** Execute the script with the documented venv and produce date/versioned desktop TXT and JSON artifacts.

**Files:**
- Output: `/mnt/c/Users/Sky.Lu/Desktop/output/MA25_RPS_CSI300_三仓短线_严格MTM_v1_*.txt`
- Output: `/mnt/c/Users/Sky.Lu/Desktop/output/MA25_RPS_CSI300_三仓短线_严格MTM_v1_*.json`

**Verification:**
1. `python -m py_compile` passes.
2. Focused tests pass, then `pytest tests/ -q` passes.
3. Backtest records source coverage, QFQ and raw coverage, loaded universe, signal funnel, closed-trade mean and median holding days, annual MTM, terminal MTM invariant, candidate rejection counts, and all exit reasons.
4. Report results and limitations without treating historical performance as investment advice.
