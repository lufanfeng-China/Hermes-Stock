/**
 * Pure viewport math for interactive SVG charts.
 * No DOM, no dependencies — testable with `node --test`.
 */

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

/**
 * Resolve the visible window given total data points and desired visible count.
 * @param {object} opts
 * @param {number} opts.totalCount   - total rows in dataset
 * @param {number} opts.visibleWindow - number of rows to show
 * @param {number} opts.windowStart   - index of first visible row
 * @returns {{windowStart: number, windowEnd: number, visibleWindow: number}}
 */
export function resolveViewport({ totalCount, visibleWindow, windowStart }) {
  const ws = clamp(windowStart, 0, Math.max(0, totalCount - visibleWindow));
  return {
    windowStart: ws,
    windowEnd: Math.min(ws + visibleWindow, totalCount),
    visibleWindow: Math.min(visibleWindow, totalCount),
  };
}

/**
 * Zoom the viewport.
 * @param {object} opts
 * @param {number} opts.totalCount
 * @param {{windowStart:number, windowEnd:number, visibleWindow:number}} opts.viewport
 * @param {number} opts.nextSize  - desired new visibleWindow
 * @param {number} opts.anchorRatio - 0..1, where in the visible window the cursor sits
 */
export function zoomViewport({ totalCount, viewport, nextSize, anchorRatio = 0.5 }) {
  const clampedSize = clamp(nextSize, 10, totalCount);
  const anchorIndex = viewport.windowStart + Math.round(viewport.visibleWindow * anchorRatio);
  const rawStart = anchorIndex - Math.round(clampedSize * anchorRatio);
  return resolveViewport({ totalCount, visibleWindow: clampedSize, windowStart: rawStart });
}

/**
 * Pan the viewport by deltaPoints.
 * @param {object} opts
 * @param {number} opts.totalCount
 * @param {{windowStart:number, windowEnd:number, visibleWindow:number}} opts.viewport
 * @param {number} opts.deltaPoints - positive = pan right (show earlier data), negative = pan left
 */
export function panViewport({ totalCount, viewport, deltaPoints }) {
  return resolveViewport({
    totalCount,
    visibleWindow: viewport.visibleWindow,
    windowStart: viewport.windowStart + deltaPoints,
  });
}

/**
 * Derive window selection state from a preset click.
 * @param {number} totalCount
 * @param {number} preset - preset window size (e.g. 20, 60, 120) or -1 for ALL
 * @returns {{windowStart: number, windowEnd: number, visibleWindow: number}}
 */
export function deriveWindowSelection(totalCount, preset) {
  if (preset === -1 || preset >= totalCount) {
    return { windowStart: 0, windowEnd: totalCount, visibleWindow: totalCount };
  }
  return resolveViewport({ totalCount, visibleWindow: preset, windowStart: Math.max(0, totalCount - preset) });
}

/**
 * Compute a trailing moving-average series.
 * @param {number[]} values - raw values
 * @param {number} windowSize
 * @returns {(number|null)[]}
 */
export function computeMovingAverageSeries(values, windowSize) {
  return values.map((_, i) => {
    if (i < windowSize - 1) return null;
    const slice = values.slice(i - windowSize + 1, i + 1);
    return slice.reduce((a, b) => a + b, 0) / windowSize;
  });
}

/**
 * Convert raw volume to display millions.
 * @param {number} volume
 * @returns {string}
 */
export function scaleVolumeMillions(volume) {
  if (volume >= 1_000_000) return `${(volume / 1_000_000).toFixed(1)}M`;
  if (volume >= 1_000) return `${(volume / 1_000).toFixed(0)}K`;
  return `${volume}`;
}
