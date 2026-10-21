# Good-Stock Undervaluation Diagnosis Implementation Plan

> **For Hermes:** Implement only after the first-wave historical event-study task is fully complete, verified, committed, and a new save tag has been created. Use TDD task-by-task; do not overlap its CPU/data workload with the running first-wave scan.

**Goal:** Add an auditable valuation-diagnosis workflow that first admits only financially sound businesses, then classifies those eligible companies by valuation safety margin and business momentum; companies failing the quality gate remain outside the four quadrants.

**Architecture:** Build a pure, point-in-time-capable valuation classifier on top of existing financial-health, relative-valuation, TTM PE/PS, peer-snapshot, and financial warehouse data. Persist daily current results and date-specific historical results separately. The UI must show evidence and model applicability, never a black-box “undervalued” label.

**Tech stack:** Python 3.12; existing CW Parquet financial warehouse; local TDX QFQ/raw daily data; JSON snapshots; stdlib HTTP handler; vanilla HTML/CSS/JS; unittest.

---

## Locked product structure

### Layer 0 — universe and data validity

Only ordinary沪深 A-shares with a valid current price, identifiable industry/peer context, and complete enough financial evidence may receive a diagnosis. Do not silently convert unavailable evidence into a passing result.

### Layer 1 — “good-stock” quality admission gate

This layer deliberately excludes valuation. A company must pass a future user-confirmed rule card covering:

- multi-year profitability durability;
- cash-flow versus accounting-profit quality;
- balance-sheet and debt-service safety;
- business quality / ROE / margin / turnover stability;
- major financial red flags;
- latest-quarter deterioration monitor, clearly separated from the five complete annual reports.

A failure produces `NOT_QUALITY_ELIGIBLE`, with concrete failed evidence. It must not enter the four quadrants.

### Layer 2 — valuation evidence

Only quality-eligible stocks receive these independent evidence dimensions:

- industry-relative PE-TTM and PS-TTM position;
- own-history PE/PB/PS percentile where valid;
- conservative intrinsic-value range where a sector-appropriate model is applicable;
- raw current-price safety margin versus pessimistic/base intrinsic-value cases;
- explicit reason a metric/model is unavailable (negative TTM earnings, FCF not suitable, insufficient history, etc.).

### Layer 3 — four quadrants

Axes:

- X: valuation safety margin: `HAS_MARGIN` / `NO_MARGIN_OR_UNCERTAIN`;
- Y: business momentum: `IMPROVING` / `STABLE_OR_MILDLY_WEAKENING`.

Resulting classifications:

1. `QUALITY_UNDERVALUED_IMPROVING`
2. `QUALITY_UNDERVALUED_STABLE`
3. `QUALITY_FAIR_IMPROVING`
4. `QUALITY_FAIR_STABLE`
5. `NOT_QUALITY_ELIGIBLE` — outside the four quadrants.

No score threshold, annual-quality gate threshold, valuation-percentile cutoff, safety-margin cutoff, or “improving” rule becomes production logic until reviewed one question at a time with the user.

---

## Task 1: Freeze the rule ledger before implementation

**Objective:** Turn the conceptual framework into an auditable, unambiguous business-rule contract without inspecting outcomes to choose thresholds.

**Files:**
- Create: `docs/strategy_cards/good_stock_undervaluation_v1.md`
- Create: `tests/fixtures/good_stock_undervaluation_rule_card.json`

**Steps:**
1. Ask exactly one unresolved decision at a time, covering the quality gate first, then valuation evidence, then quadrant cutoffs.
2. For each decision, record definition, formula, report-period policy, source field, unavailable-data behavior, and whether it is a hard gate, score, or disclosure only.
3. Freeze separate industry paths:
   - financials: PB–ROE;
   - real estate: discounted NAV / balance-sheet risk review;
   - stable non-financials: PE/PS plus conservative DCF where FCF is usable;
   - cyclicals: normalized/mid-cycle earnings evidence;
   - negative-profit companies: no PE conclusion, disclose unavailable.
4. Explicitly freeze current versus historical/PIT behavior. Historical results may only use prices and reports available at date T.
5. Commit the rule card before coding.

**Verification:** Every rule has a formula, a data source, a timing convention, and a missing-data outcome. No threshold is silently inferred from a sample distribution.

---

## Task 2: Create pure quality-gate calculations with tests

**Objective:** Calculate quality eligibility independently of valuation and preserve all pass/fail evidence.

**Files:**
- Create: `app/undervaluation/quality_gate.py`
- Create: `tests/test_undervaluation_quality_gate.py`
- Reuse: `app/financial/health.py`
- Reuse: `app/financial/composite_health.py`
- Reuse: `app/financial/reports.py`

**TDD steps:**
1. Write failing tests for a durable-profit / cash-flow-consistent company, a profit-cash-flow divergence, a debt/red-flag failure, and unavailable financial history.
2. Implement a pure `evaluate_quality_gate(inputs, as_of_date)` returning:
   ```python
   {
     "status": "QUALITY_ELIGIBLE" | "NOT_QUALITY_ELIGIBLE" | "INSUFFICIENT_EVIDENCE",
     "annual_evidence": {...},
     "quarterly_monitor": {...},
     "failed_rules": [...],
     "data_as_of": "YYYY-MM-DD"
   }
   ```
3. Keep five complete annual reports separate from the latest quarterly monitor.
4. Run the focused tests.
5. Commit.

**Verification:** A stock cannot pass merely because a composite score is high when a hard red flag is present; unavailable evidence is not treated as healthy.

---

## Task 3: Create sector-aware valuation-evidence calculations with tests

**Objective:** Produce valuation evidence without claiming every company has a valid PE or DCF.

**Files:**
- Create: `app/undervaluation/valuation_evidence.py`
- Create: `tests/test_undervaluation_valuation_evidence.py`
- Reuse: `app/relative_valuation/data_loader.py`
- Reuse: `app/relative_valuation/classifier.py`
- Reuse: `app/relative_valuation/history.py`
- Reuse when appropriate: `app/valuation/models.py`

**TDD steps:**
1. Write failing tests for ordinary profitable firms, negative-TTM-EPS firms, a financial company, a real-estate company, an FCF-negative non-financial firm, and missing peer/history data.
2. Implement model selection and return:
   ```python
   {
     "relative_valuation": {"pe_ttm": ..., "ps_ttm": ..., "industry_percentiles": ...},
     "own_history": {"pe_percentile": ..., "pb_percentile": ..., "coverage": ...},
     "intrinsic_value": {"model": ..., "bear": ..., "base": ..., "bull": ..., "applicable": ...},
     "safety_margin": {"bear_pct": ..., "base_pct": ...},
     "unavailable_reasons": [...]
   }
   ```
3. Use original/current market price only for the valuation price; retain the report date and TTM formula as audit fields.
4. Run focused tests.
5. Commit.

**Verification:** No DCF is fabricated when FCF is unsuitable; banks are not evaluated by generic DCF; negative PE is shown as unavailable rather than “cheap.”

---

## Task 4: Classify eligible stocks into the four quadrants

**Objective:** Combine quality and valuation evidence without conflating gates, scores, and labels.

**Files:**
- Create: `app/undervaluation/classifier.py`
- Create: `tests/test_undervaluation_classifier.py`

**TDD steps:**
1. Write failing table-driven tests for all five outcomes, ties/boundaries, unavailable valuation evidence, and multiple warning tags.
2. Implement `classify_undervaluation(quality, valuation, momentum)`.
3. Ensure quality failure always dominates a potential valuation discount.
4. Retain independent tags such as `historical_discount`, `industry_discount`, `quarterly_monitor_warning`, and `intrinsic_model_unavailable`.
5. Run focused tests and commit.

**Verification:** Each output contains an explainable classification path, not only a score.

---

## Task 5: Build PIT-capable current and history snapshot assets

**Objective:** Materialize results offline so APIs/pages never calculate the full universe synchronously.

**Files:**
- Create: `scripts/build_undervaluation_snapshot.py`
- Create: `app/undervaluation/snapshot.py`
- Create: `app/undervaluation/progress.py`
- Create: `tests/test_undervaluation_snapshot.py`
- Modify: `app/pipeline/commands.py`

**Steps:**
1. Define current artifact:
   `data/derived/datasets/final/undervaluation/current.json`.
2. Define history artifact:
   `data/derived/datasets/final/undervaluation/history/<YYYY-MM-DD>.json`.
3. For historical dates, use announcement-date-truncated financial inputs and the original market price available on T. Never reuse a current relative-valuation snapshot for history.
4. Use `<date>.building` lock and atomic `<date>.progress.json`, following the stock-filter historical contract.
5. Add the current builder to the normal data-update pipeline; historical builds remain on-demand/retryable.
6. Add schema versioning and source-data timestamps.
7. Test historical date T cannot observe report, price, or peer evidence after T.
8. Commit.

**Verification:** Direct snapshot inspection has complete counts, unavailable-data counts, schema version, and no future-data leak.

---

## Task 6: Add an independent API and audit-first page

**Objective:** Present results without presenting a research model as investment advice or hiding uncertainty.

**Files:**
- Modify: `app/handler.py`
- Create: `web/undervaluation.html`
- Create: `web/undervaluation.js`
- Create: `web/undervaluation.css`
- Modify: `web/nav.js`
- Create: `tests/test_undervaluation_contract.py`
- Create: `tests/test_undervaluation_page.py`

**Steps:**
1. Add `GET /api/undervaluation?as_of_date=YYYY-MM-DD`.
2. Return current or historical snapshot only; missing historical data triggers the verified asynchronous builder/progress contract.
3. Page order:
   - data-date and methodology disclosure;
   - four eligible-quality quadrants with counts;
   - separate “not quality eligible / insufficient evidence” section;
   - sortable evidence table;
   - per-stock expansion with annual health, quarter monitor, PE/PS/PB evidence, model applicability, intrinsic-value range, and safety margin.
4. Keep historical mode free of post-T returns.
5. Use cache-busted frontend verification and direct API assertions.
6. Commit.

**Verification:** Browser tests prove all five classifications render, unavailable evidence is visible, and changing to a history date preserves the selected date while polling build progress.

---

## Task 7: Calibrate without outcome overfitting

**Objective:** Audit distribution and coverage before claiming the framework identifies good investments.

**Files:**
- Create: `scripts/research_undervaluation_coverage.py`
- Create: `tests/test_research_undervaluation_coverage.py`
- Create versioned outputs under: `/mnt/c/Users/Sky.Lu/Desktop/output/`

**Steps:**
1. Produce count funnels: universe → sufficient evidence → quality eligible → each quadrant.
2. Break down by industry, size bucket, profitability type, and model applicability.
3. Inspect concentration: no broad conclusion if a quadrant is dominated by one industry or by a small number of issuers.
4. If a future event study is authorized, keep it separate from this classifier and follow a declared split; do not use 2026 data to tune thresholds.
5. Report limitations: survivorship, financial-report timing, negative-earnings treatment, industry mapping gaps, and uncertain model estimates.
6. Commit reports/code separately.

**Verification:** Outputs include exact data date, sample counts, unavailable evidence counts, and no unsupported “effective strategy” claim.

---

## Task 8: Full integration verification and release

**Objective:** Verify the feature through data, API, browser, and data-update workflows.

**Steps:**
1. Run focused unit/contract/page tests plus relevant existing financial/relative-valuation tests.
2. Run `py_compile`, `node --check`, and `git diff --check`.
3. Rebuild a current snapshot and inspect the data manifest.
4. Restart the dashboard with `~/.venvs/moontdx-china-stock-data/bin/python` and verify direct API responses.
5. Browser-test current and historical flows, including a date that needs a background build.
6. Confirm the normal data-update plan lists the current undervaluation builder as independently retryable.
7. Make a final commit, push it, and create a `save-YYYYMMDD-HHMM` tag.

---

## Risks and non-negotiable safeguards

- Do not call a company “undervalued” based solely on PE/PB/PS.
- Never score a missing value as favorable.
- Never use current financial snapshots or current industry valuation history in an old-date diagnosis.
- Preserve raw evidence, period, formula, source and unavailable reason for every displayed metric.
- Do not use a generic DCF for financials, real estate, or FCF-negative businesses.
- Do not allow a quarterly improvement to overwrite the separate five-year annual health assessment.
- Thresholds are intentionally open until user review; implementation must not infer them from observed historical outcomes.

## Deferred start condition

Do not start Task 1 until the active first-wave historical event-scan, raw-outcome completion, chronological reports, review, final verification, commit, and save tag are finished. At that point, begin with a fresh save tag and the one-question-at-a-time rule ledger.