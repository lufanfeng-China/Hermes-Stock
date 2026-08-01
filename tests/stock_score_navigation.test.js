const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

test("财务评分顶部导航 includes 极值金叉 but omits 实时选股", () => {
  const html = fs.readFileSync(path.join(__dirname, "../web/stock-score.html"), "utf8");
  const nav = html.match(/<div id="stock-score-topbar-actions"[\s\S]*?<\/div>/)[0];
  assert.match(nav, /href="\/macd-extreme-gc\.html"[^>]*>极值金叉<\/a>/);
  assert.doesNotMatch(nav, /href="\/realtime-screener\.html"[^>]*>实时选股<\/a>/);
});
