import { clamp, resolveViewport, zoomViewport, panViewport, deriveWindowSelection, computeMovingAverageSeries, scaleVolumeMillions } from './viewport.js';
import { test, describe } from 'node:test';
import assert from 'node:assert';

describe('clamp', () => {
  test('inside range', () => assert.strictEqual(clamp(5, 0, 10), 5));
  test('below min', () => assert.strictEqual(clamp(-1, 0, 10), 0));
  test('above max', () => assert.strictEqual(clamp(15, 0, 10), 10));
});

describe('resolveViewport', () => {
  test('middle window', () => {
    const r = resolveViewport({ totalCount: 100, visibleWindow: 20, windowStart: 30 });
    assert.strictEqual(r.windowStart, 30);
    assert.strictEqual(r.windowEnd, 50);
    assert.strictEqual(r.visibleWindow, 20);
  });
  test('clamp start at 0', () => {
    const r = resolveViewport({ totalCount: 100, visibleWindow: 20, windowStart: -10 });
    assert.strictEqual(r.windowStart, 0);
  });
  test('clamp end at totalCount', () => {
    const r = resolveViewport({ totalCount: 100, visibleWindow: 20, windowStart: 90 });
    assert.strictEqual(r.windowStart, 80);
    assert.strictEqual(r.windowEnd, 100);
  });
  test('visibleWindow larger than totalCount', () => {
    const r = resolveViewport({ totalCount: 10, visibleWindow: 20, windowStart: 0 });
    assert.strictEqual(r.visibleWindow, 10);
    assert.strictEqual(r.windowEnd, 10);
  });
});

describe('zoomViewport', () => {
  test('zoom in around center', () => {
    const vp = { windowStart: 50, windowEnd: 70, visibleWindow: 20 };
    const r = zoomViewport({ totalCount: 200, viewport: vp, nextSize: 10, anchorRatio: 0.5 });
    assert.strictEqual(r.visibleWindow, 10);
  });
});

describe('panViewport', () => {
  test('pan right (delta positive)', () => {
    const vp = { windowStart: 50, windowEnd: 70, visibleWindow: 20 };
    const r = panViewport({ totalCount: 200, viewport: vp, deltaPoints: 5 });
    assert.strictEqual(r.windowStart, 55);
  });
  test('pan left (delta negative)', () => {
    const vp = { windowStart: 50, windowEnd: 70, visibleWindow: 20 };
    const r = panViewport({ totalCount: 200, viewport: vp, deltaPoints: -5 });
    assert.strictEqual(r.windowStart, 45);
  });
  test('clamp at left boundary', () => {
    const vp = { windowStart: 5, windowEnd: 25, visibleWindow: 20 };
    const r = panViewport({ totalCount: 200, viewport: vp, deltaPoints: -20 });
    assert.strictEqual(r.windowStart, 0);
  });
});

describe('deriveWindowSelection', () => {
  test('preset smaller than total', () => {
    const r = deriveWindowSelection(200, 20);
    assert.strictEqual(r.visibleWindow, 20);
    assert.strictEqual(r.windowEnd, 200);
  });
  test('ALL (-1) returns full range', () => {
    const r = deriveWindowSelection(200, -1);
    assert.strictEqual(r.visibleWindow, 200);
    assert.strictEqual(r.windowStart, 0);
  });
  test('preset larger than total returns full range', () => {
    const r = deriveWindowSelection(50, 120);
    assert.strictEqual(r.visibleWindow, 50);
  });
});

describe('computeMovingAverageSeries', () => {
  test('5-day MA warmup produces nulls', () => {
    const r = computeMovingAverageSeries([10, 20, 30, 40, 50, 60], 5);
    assert.strictEqual(r[0], null);
    assert.strictEqual(r[3], null);
    assert.strictEqual(r[4], 30);
    assert.strictEqual(r[5], 40);
  });
  test('3-day MA', () => {
    const r = computeMovingAverageSeries([2, 4, 6, 8], 3);
    assert.deepStrictEqual(r, [null, null, 4, 6]);
  });
});

describe('scaleVolumeMillions', () => {
  test('M scale', () => assert.strictEqual(scaleVolumeMillions(1_500_000), '1.5M'));
  test('K scale', () => assert.strictEqual(scaleVolumeMillions(50_000), '50K'));
  test('raw', () => assert.strictEqual(scaleVolumeMillions(500), '500'));
});
