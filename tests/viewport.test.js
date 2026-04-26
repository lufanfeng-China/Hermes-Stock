const test = require("node:test");
const assert = require("node:assert/strict");

const {
  scaleVolumeMillions,
  computeMovingAverageSeries,
  resolveViewport,
  zoomViewport,
  panViewport,
  deriveWindowSelection,
} = require("../web/viewport.js");

test("resolveViewport returns full range for all mode", () => {
  assert.deepEqual(resolveViewport(100, "all", 0), {
    start: 0,
    end: 100,
    size: 100,
    isAll: true,
    maxStart: 0,
  });
});

test("resolveViewport clamps fixed window start", () => {
  assert.deepEqual(resolveViewport(100, 20, 90), {
    start: 80,
    end: 100,
    size: 20,
    isAll: false,
    maxStart: 80,
  });
});

test("zoomViewport zooms around the hovered anchor", () => {
  const next = zoomViewport({
    totalCount: 120,
    viewport: { start: 40, size: 40 },
    nextSize: 20,
    anchorRatio: 0.75,
  });

  assert.deepEqual(next, { start: 55, size: 20 });
});

test("panViewport clamps to history bounds", () => {
  assert.deepEqual(
    panViewport({
      totalCount: 120,
      viewport: { start: 90, size: 20 },
      deltaPoints: 30,
    }),
    { start: 100, size: 20 }
  );
});

test("deriveWindowSelection marks non-preset windows as custom", () => {
  assert.equal(deriveWindowSelection({ size: 33, isAll: false }, [20, 60, 120]), null);
  assert.equal(deriveWindowSelection({ size: 60, isAll: false }, [20, 60, 120]), 60);
  assert.equal(deriveWindowSelection({ size: 120, isAll: true }, [20, 60, 120]), "all");
});

test("scaleVolumeMillions converts raw volume to millions", () => {
  assert.equal(scaleVolumeMillions(12500000), 12.5);
  assert.equal(scaleVolumeMillions(0), 0);
});

test("computeMovingAverageSeries returns trailing averages with null warmup", () => {
  assert.deepEqual(computeMovingAverageSeries([10, 20, 30, 40], 3), [null, null, 20, 30]);
  assert.deepEqual(computeMovingAverageSeries([5, 15], 1), [5, 15]);
});
