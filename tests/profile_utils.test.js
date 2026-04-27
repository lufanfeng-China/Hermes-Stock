const test = require("node:test");
const assert = require("node:assert/strict");
const { formatAuxiliaryBucketLabel, sortAuxiliaryBuckets } = require("../web/profile-utils.js");

test("formatAuxiliaryBucketLabel maps auxiliary buckets to Chinese labels", () => {
  assert.equal(formatAuxiliaryBucketLabel("membership"), "风格/成分");
  assert.equal(formatAuxiliaryBucketLabel("technical"), "技术标签");
  assert.equal(formatAuxiliaryBucketLabel("financial"), "财务标签");
  assert.equal(formatAuxiliaryBucketLabel("shareholder"), "股东/持股");
  assert.equal(formatAuxiliaryBucketLabel("timestamped"), "时点标签");
  assert.equal(formatAuxiliaryBucketLabel("description"), "业务描述");
  assert.equal(formatAuxiliaryBucketLabel("alias"), "历史简称");
  assert.equal(formatAuxiliaryBucketLabel("unknown_bucket"), "其他标签");
});

test("sortAuxiliaryBuckets enforces stable bucket order", () => {
  const input = [
    ["description", [{}]],
    ["membership", [{}]],
    ["timestamped", [{}]],
    ["technical", [{}]],
    ["shareholder", [{}]],
    ["financial", [{}]],
    ["alias", [{}]],
  ];
  assert.deepEqual(
    sortAuxiliaryBuckets(input).map(([bucket]) => bucket),
    ["financial", "shareholder", "technical", "timestamped", "membership", "description", "alias"]
  );
});
