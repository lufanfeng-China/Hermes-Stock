const SEARCH_DEBOUNCE_MS = 200;
const MAX_RECENT_STOCK_SEARCHES = 6;
const RECENT_STOCK_SEARCHES_STORAGE_KEY = "valuation-recent-searches";

const inputEl = document.getElementById("valuation-input");
const buttonEl = document.getElementById("valuation-search-btn");
const statusEl = document.getElementById("valuation-status");
const dropdownEl = document.getElementById("valuation-dropdown");

const searchState = {
  timer: null,
  requestId: 0,
  selectedStock: null,
  suggestions: [],
  recentSearches: [],
  dropdownMode: "suggestions",
};

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("muted", !isError);
}

function formatNumber(value, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function formatPercent(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatOutputLevel(value) {
  const map = {
    standard: "标准",
    cautious_reference: "谨慎参考",
    highly_cautious: "高度谨慎",
    not_estimable: "不宜估值",
  };
  return map[value] || value || "—";
}

function renderTagList(el, items, emptyText) {
  if (!Array.isArray(items) || !items.length) {
    el.textContent = emptyText;
    return;
  }
  el.innerHTML = items.map((item) => `<div class="stock-score-analysis-item">${escapeHtml(item)}</div>`).join("");
}

function renderViewPanel(el, view) {
  const titleMap = {
    earnings: "盈利视角",
    asset: "资产视角",
    revenue: "收入视角",
  };
  if (!view) {
    el.innerHTML = '<div class="stock-score-analysis-card"><h3>待加载</h3></div>';
    return;
  }
  const notes = Array.isArray(view.notes) && view.notes.length ? view.notes.join("；") : "无";
  const drivers = Array.isArray(view.drivers) && view.drivers.length ? view.drivers.join(" / ") : "无";
  el.innerHTML = `
    <div class="stock-score-dim-panel-head">
      <p class="eyebrow">${escapeHtml(view.view_name.toUpperCase())}</p>
      <h3>${escapeHtml(titleMap[view.view_name] || view.view_name)}</h3>
    </div>
    <div class="dim-cards">
      <article class="dim-card">
        <p class="dim-label">状态</p>
        <p class="dim-score">${view.is_valid ? "有效" : "无效"}</p>
        <p class="dim-meta">可靠度: ${formatNumber(view.reliability)}</p>
      </article>
      <article class="dim-card">
        <p class="dim-label">Low / Mid / High</p>
        <p class="dim-score">${formatNumber(view.mid)}</p>
        <p class="dim-meta">${formatNumber(view.low)} / ${formatNumber(view.high)}</p>
      </article>
      <article class="dim-card">
        <p class="dim-label">Drivers</p>
        <p class="dim-score dim-score-sm">${escapeHtml(drivers)}</p>
        <p class="dim-meta">${escapeHtml(notes)}</p>
      </article>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function normalizeMarket(code) {
  if (!code) return null;
  const s = String(code).trim().toLowerCase();
  if (["sh", "sz", "bj"].includes(s)) return s;
  if (s.startsWith("6") || s.startsWith("5") || s.startsWith("9")) return "sh";
  if (s.startsWith("0") || s.startsWith("3")) return "sz";
  if (s.startsWith("4") || s.startsWith("8")) return "bj";
  return null;
}

function normalizeQuery(raw) {
  const text = String(raw || "").trim();
  if (!text) return { market: "", symbol: "" };
  if (text.includes(":")) {
    const [market, symbol] = text.split(":", 2);
    return { market: normalizeMarket(market.trim()) || "", symbol: symbol.trim() };
  }
  const symbol = text.replace(/[^\d]/g, "");
  return { market: normalizeMarket(symbol) || "", symbol };
}

async function fetchStockSuggestions(query) {
  const url = `/api/search/stocks?q=${encodeURIComponent(query)}&limit=10`;
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload?.error?.message || `HTTP ${response.status}`);
  }
  return payload.results || [];
}

function toStockIdentity(row) {
  if (!row?.market || !row?.symbol) return "";
  return `${String(row.market).toLowerCase()}:${String(row.symbol).trim()}`;
}

function loadRecentStockSearches() {
  try {
    const raw = localStorage.getItem(RECENT_STOCK_SEARCHES_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((row) => row && row.market && row.symbol)
      .map((row) => ({
        market: String(row.market).toLowerCase(),
        symbol: String(row.symbol).trim(),
        stock_name: String(row.stock_name || row.name || row.symbol).trim(),
      }))
      .slice(0, MAX_RECENT_STOCK_SEARCHES);
  } catch {
    return [];
  }
}

function saveRecentStockSearch(stock) {
  if (!stock?.market || !stock?.symbol) return;
  const normalized = {
    market: String(stock.market).toLowerCase(),
    symbol: String(stock.symbol).trim(),
    stock_name: String(stock.stock_name || stock.name || stock.symbol).trim(),
  };
  const identity = toStockIdentity(normalized);
  const nextItems = [
    normalized,
    ...loadRecentStockSearches().filter((row) => toStockIdentity(row) !== identity),
  ].slice(0, MAX_RECENT_STOCK_SEARCHES);
  searchState.recentSearches = nextItems;
  try {
    localStorage.setItem(RECENT_STOCK_SEARCHES_STORAGE_KEY, JSON.stringify(nextItems));
  } catch {
    // Ignore quota/privacy failures and keep in-memory state usable.
  }
}

function renderRecentStockSearches() {
  const items = loadRecentStockSearches().slice(0, MAX_RECENT_STOCK_SEARCHES);
  searchState.recentSearches = items;
  searchState.dropdownMode = "recent-search";
  searchState.suggestions = [];
  if (!items.length) {
    dropdownEl.innerHTML = '<div class="search-option empty recent-search">暂无最近搜索</div>';
    dropdownEl.classList.add("visible");
    return;
  }

  dropdownEl.innerHTML = items.map((row, index) => (
    `<button type="button" class="search-option recent-search" data-index="${index}" data-source="recent-search">
      <span class="search-option-main">${escapeHtml(row.stock_name)}</span>
      <span class="search-option-meta">recent-search · ${escapeHtml(row.market.toUpperCase())} · ${escapeHtml(row.symbol)}</span>
    </button>`
  )).join("");
  dropdownEl.classList.add("visible");
}

function renderSuggestions(results) {
  searchState.dropdownMode = "suggestions";
  searchState.suggestions = results;
  if (!results.length) {
    dropdownEl.innerHTML = '<div class="search-option empty">未找到匹配股票</div>';
    dropdownEl.classList.add("visible");
    return;
  }

  dropdownEl.innerHTML = results.map((row, index) => (
    `<button type="button" class="search-option" data-index="${index}">
      <span class="search-option-main">${escapeHtml(row.stock_name)}</span>
      <span class="search-option-meta">${escapeHtml(String(row.market || "").toUpperCase())} · ${escapeHtml(row.symbol || "")}</span>
    </button>`
  )).join("");
  dropdownEl.classList.add("visible");
}

function hideSuggestions() {
  dropdownEl.classList.remove("visible");
}

function applySuggestion(row) {
  if (!row) return;
  searchState.selectedStock = {
    market: String(row.market || "").toLowerCase(),
    symbol: String(row.symbol || "").trim(),
    stock_name: String(row.stock_name || row.name || row.symbol || "").trim(),
  };
  inputEl.value = `${searchState.selectedStock.stock_name} (${searchState.selectedStock.symbol})`;
  hideSuggestions();
}

async function loadSuggestions(query) {
  const trimmed = query.trim();
  const requestId = ++searchState.requestId;
  if (!trimmed) {
    renderRecentStockSearches();
    return;
  }
  try {
    const results = await fetchStockSuggestions(trimmed);
    if (requestId !== searchState.requestId) return;
    renderSuggestions(results.slice(0, 10));
  } catch {
    if (requestId !== searchState.requestId) return;
    dropdownEl.innerHTML = '<div class="search-option empty">搜索失败</div>';
    dropdownEl.classList.add("visible");
  }
}

async function runValuationSearch(selectedRow = null) {
  const input = inputEl.value.trim();
  let market = "";
  let symbol = "";
  let stockName = "";

  if (selectedRow) {
    market = String(selectedRow.market || "").toLowerCase();
    symbol = String(selectedRow.symbol || "").trim();
    stockName = String(selectedRow.stock_name || selectedRow.name || selectedRow.symbol || "").trim();
    searchState.selectedStock = { market, symbol, stock_name: stockName };
  } else if (searchState.selectedStock) {
    market = searchState.selectedStock.market;
    symbol = searchState.selectedStock.symbol;
    stockName = searchState.selectedStock.stock_name;
  } else {
    const normalized = normalizeQuery(input);
    market = normalized.market;
    symbol = normalized.symbol;
  }

  if ((!market || !symbol) && searchState.suggestions.length) {
    const fallback = searchState.suggestions[0];
    applySuggestion(fallback);
    market = searchState.selectedStock?.market || "";
    symbol = searchState.selectedStock?.symbol || "";
    stockName = searchState.selectedStock?.stock_name || "";
  }

  if ((!market || !symbol) && input) {
    try {
      const directMatches = await fetchStockSuggestions(input);
      if (directMatches.length === 1) {
        applySuggestion(directMatches[0]);
        market = searchState.selectedStock?.market || "";
        symbol = searchState.selectedStock?.symbol || "";
        stockName = searchState.selectedStock?.stock_name || "";
      }
    } catch {
      // Keep the normal validation error below if direct lookup also fails.
    }
  }

  if (!market || !symbol) {
    setStatus("请输入有效股票代码，例如 000333 或 sz:000333", true);
    return;
  }

  hideSuggestions();
  setStatus("估值计算中...");
  try {
    const response = await fetch(`/api/valuation?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`);
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result?.error?.message || result?.error || "valuation api failed");
    }
    renderValuationResult(result);
    saveRecentStockSearch({
      market,
      symbol,
      stock_name: stockName || result.stock_name || symbol,
    });
    searchState.selectedStock = {
      market,
      symbol,
      stock_name: stockName || result.stock_name || symbol,
    };
    setStatus(`${result.stock_name} 估值结果已更新`);
  } catch (error) {
    console.error(error);
    setStatus(`估值查询失败: ${error.message || error}`, true);
  }
}

function renderValuationResult(result) {
  document.getElementById("valuation-stock-name").textContent = result.stock_name || "—";
  document.getElementById("valuation-stock-symbol").textContent = `${(result.market || "").toUpperCase()}:${result.symbol || ""}`;
  document.getElementById("valuation-date").textContent = result.valuation_date || "—";
  document.getElementById("valuation-latest-report-date").textContent = result.latest_report_date || "最新报告期未提供";
  document.getElementById("valuation-current-price").textContent = formatNumber(result.current_price);
  document.getElementById("valuation-final-low").textContent = `Low: ${formatNumber(result.final_low)}`;
  document.getElementById("valuation-final-mid").textContent = formatNumber(result.final_mid);
  document.getElementById("valuation-final-high").textContent = `High: ${formatNumber(result.final_high)}`;
  document.getElementById("valuation-output-level").textContent = formatOutputLevel(result.output_level);
  document.getElementById("valuation-dominant-view").textContent = `主导视角: ${result.dominant_view || "—"}`;
  document.getElementById("valuation-template-id").textContent = result.valuation_template_id || "—";
  document.getElementById("valuation-upside-mid").textContent = `中枢偏离: ${formatPercent(result.upside_mid_pct)}`;
  document.getElementById("valuation-margin-of-safety").textContent = `安全边际: ${formatPercent(result.margin_of_safety_pct)}`;
  document.getElementById("valuation-methodology-note").textContent = result.methodology_note || "暂无方法说明";

  const views = Array.isArray(result.views) ? result.views : [];
  renderViewPanel(document.getElementById("valuation-view-earnings"), views.find((v) => v.view_name === "earnings"));
  renderViewPanel(document.getElementById("valuation-view-asset"), views.find((v) => v.view_name === "asset"));
  renderViewPanel(document.getElementById("valuation-view-revenue"), views.find((v) => v.view_name === "revenue"));

  renderTagList(document.getElementById("valuation-risk-tags"), result.risk_tags, "暂无风险标签");
  renderTagList(document.getElementById("valuation-failure-conditions"), result.failure_conditions, "暂无失效条件");
}

document.addEventListener("DOMContentLoaded", () => {
  buttonEl.addEventListener("click", () => runValuationSearch());
  inputEl.addEventListener("input", (event) => {
    const value = event.target.value;
    if (searchState.selectedStock) {
      const selectedLabel = `${searchState.selectedStock.stock_name} (${searchState.selectedStock.symbol})`;
      if (value !== selectedLabel) searchState.selectedStock = null;
    }
    window.clearTimeout(searchState.timer);
    searchState.timer = window.setTimeout(() => {
      loadSuggestions(value);
    }, SEARCH_DEBOUNCE_MS);
  });
  inputEl.addEventListener("focus", () => {
    renderRecentStockSearches();
  });
  inputEl.addEventListener("click", () => {
    renderRecentStockSearches();
  });
  inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      if (searchState.selectedStock) {
        runValuationSearch(searchState.selectedStock);
      } else if (searchState.suggestions.length === 1) {
        applySuggestion(searchState.suggestions[0]);
        runValuationSearch(searchState.selectedStock);
      } else {
        runValuationSearch();
      }
      hideSuggestions();
    }
  });
  dropdownEl.addEventListener("click", (event) => {
    const option = event.target.closest(".search-option[data-index]");
    if (!option) return;
    const index = Number(option.dataset.index);
    const list = option.dataset.source === "recent-search"
      ? searchState.recentSearches
      : searchState.suggestions;
    const row = list[index];
    applySuggestion(row);
    runValuationSearch(row);
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-input-wrap")) {
      hideSuggestions();
    }
  });
});
