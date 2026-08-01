const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const legacyHtml = fs.readFileSync(path.join(root, "web/stock-screener.html"), "utf8");
const script = fs.readFileSync(path.join(root, "web/stock-screener.js"), "utf8");
const v2Html = fs.readFileSync(path.join(root, "web/stock-screener-v2.html"), "utf8");
const globalNav = fs.readFileSync(path.join(root, "web/nav.js"), "utf8");
const v2Css = fs.readFileSync(path.join(root, "web/stock-screener-v2.css"), "utf8");

test("stock screener V2 preserves every DOM id required by the existing behavior", () => {
  const requiredIds = [...script.matchAll(/getElementById\(['"]([^'"]+)['"]\)/g)].map((m) => m[1]);
  const missing = [...new Set(requiredIds)].filter((id) => !v2Html.includes(`id="${id}"`));
  assert.deepEqual(missing, []);
  assert.match(v2Html, /id="stock-screener-filter-form"/);
  assert.match(v2Html, /name="strategy"/);
  assert.match(v2Html, /name="as_of_date"/);
  const requiredNames = [...legacyHtml.matchAll(/\bname="([^"]+)"/g)].map((m) => m[1]);
  for (const name of requiredNames) {
    assert.match(v2Html, new RegExp(`\\bname="${name}"`), `missing form control name: ${name}`);
  }

  assert.match(v2Html, /stock-screener\.js\?v=/);
  assert.match(v2Css, /\.stock-screener-filter-grid\[hidden\]\s*\{\s*display:\s*none/);
});

test("V2 keeps date controls light and improves result-table readability", () => {
  assert.match(v2Css, /\.screener-v2-shell \.screener-date-bar\s*\{[\s\S]*?background:\s*var\(--v2-soft\)/);
  assert.match(v2Css, /\.screener-v2-shell \.stock-screener-table\s*\{[\s\S]*?font-size:\s*13px/);
  assert.match(v2Css, /\.stock-screener-table tbody tr:nth-child\(even\)/);
  assert.match(v2Css, /\.stock-screener-results-wrap\s*\{\s*overflow-x:\s*auto;\s*background:\s*#fff/);
  assert.match(v2Css, /\.screener-name-link\s*\{\s*color:\s*#171717\s*!important/);
});

test("stock screener V2 keeps the legacy page intact as a fallback", () => {
  assert.match(legacyHtml, /<title>股票筛选<\/title>/);
  assert.match(legacyHtml, /stock-screener-filter-form/);
});

test("global navigation directs 股票筛选 to V2", () => {
  assert.match(globalNav, /href: '\/stock-screener-v2\.html', label: '股票筛选'/);
});
