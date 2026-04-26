(function initViewportModule(globalScope) {
  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function resolveViewport(totalCount, visibleWindow, windowStart) {
    if (!totalCount) {
      return { start: 0, end: 0, size: 0, isAll: true, maxStart: 0 };
    }

    if (visibleWindow === "all" || totalCount <= visibleWindow) {
      return { start: 0, end: totalCount, size: totalCount, isAll: true, maxStart: 0 };
    }

    const size = clamp(Math.round(visibleWindow), 1, totalCount);
    const maxStart = Math.max(0, totalCount - size);
    const start = clamp(Math.round(windowStart || 0), 0, maxStart);
    return { start, end: start + size, size, isAll: false, maxStart };
  }

  function zoomViewport({ totalCount, viewport, nextSize, anchorRatio = 0.5 }) {
    const clampedSize = clamp(Math.round(nextSize), 1, totalCount || 1);
    if (clampedSize >= totalCount) {
      return { start: 0, size: totalCount };
    }

    const boundedAnchor = clamp(anchorRatio, 0, 1);
    const anchorIndex = viewport.start + viewport.size * boundedAnchor;
    const rawStart = anchorIndex - clampedSize * boundedAnchor;
    const maxStart = Math.max(0, totalCount - clampedSize);
    return {
      start: clamp(Math.round(rawStart), 0, maxStart),
      size: clampedSize,
    };
  }

  function panViewport({ totalCount, viewport, deltaPoints }) {
    const size = clamp(Math.round(viewport.size), 1, totalCount || 1);
    const maxStart = Math.max(0, totalCount - size);
    return {
      start: clamp(Math.round(viewport.start + deltaPoints), 0, maxStart),
      size,
    };
  }

  function deriveWindowSelection(viewport, presets) {
    if (viewport.isAll) {
      return "all";
    }

    const match = presets.find((preset) => preset === viewport.size);
    return match ?? null;
  }

  function scaleVolumeMillions(value) {
    return Number(value) / 1000000;
  }

  function computeMovingAverageSeries(values, windowSize) {
    const size = Math.max(1, Math.round(windowSize || 1));
    const averages = [];
    let rollingSum = 0;

    values.forEach((value, index) => {
      rollingSum += value;
      if (index >= size) {
        rollingSum -= values[index - size];
      }

      if (index < size - 1) {
        averages.push(null);
        return;
      }

      averages.push(rollingSum / size);
    });

    return averages;
  }

  const api = {
    clamp,
    resolveViewport,
    zoomViewport,
    panViewport,
    deriveWindowSelection,
    scaleVolumeMillions,
    computeMovingAverageSeries,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  globalScope.StockViewport = api;
})(typeof window !== "undefined" ? window : globalThis);
