const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

test("财务评分顶部导航不再暴露已退役的 RPS、股票筛选和极值金叉功能", () => {
  const html = fs.readFileSync(path.join(__dirname, "../web/stock-score.html"), "utf8");
  const nav = html.match(/<div id="stock-score-topbar-actions"[\s\S]*?<\/div>/)[0];
  assert.doesNotMatch(nav, /rps-pool|stock-screener|macd-extreme-gc/);
  assert.doesNotMatch(nav, /href="\/realtime-screener\.html"[^>]*>实时选股<\/a>/);
});
