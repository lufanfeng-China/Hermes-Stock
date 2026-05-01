/**
 * kline-chart.js
 * Renders an interactive candlestick + volume + RPS-history SVG chart.
 * No external dependencies. Pure DOM + SVG.
 */

const DEFAULTS = {
  priceHeightRatio: 0.55,
  volumeHeightRatio: 0.22,
  rpsHeightRatio: 0.28,
  gapRatio: 0.05,
  marginTop: 16,
  marginBottom: 48,
  marginLeft: 8,
  marginRight: 48,
  candleSpacing: 1.2,
  crosshairColor: '#3a3a4a',
  upColor: '#ef5350',
  downColor: '#26a69a',
  ma5Color: '#f7d06a',
  ma10Color: '#82b1ff',
  rps20Color: '#ce93d8',
  rps50Color: '#80cbc4',
  rps120Color: '#ffcc80',
  rps250Color: '#90caf9',
  rpsGuideColor: '#4a4a6a',
  gridColor: '#22222e',
  textColor: '#8888aa',
  labelColor: '#aaaacc',
};

export class KlineChart {
  /**
   * @param {SVGElement} svg
   * @param {object} opts
   */
  constructor(svg, opts = {}) {
    this.svg = svg;
    this.cfg = { ...DEFAULTS, ...opts };
    this.bars = [];
    this.visible = { windowStart: 0, windowEnd: 0, visibleWindow: 60 };
    this.presets = [20, 60, 120, 250, -1];
    this.maWindows = [5, 10];
    this.maSeries = {};
    this.rpsHistory = [];   // [{trading_day, rps_20, rps_50, rps_120, rps_250}, ...]
    this.hoveredIndex = null;
    this.isDragging = false;
    this.dragStartClientX = 0;
    this.dragStartWindowStart = 0;
    this.onViewportChange = null;
    this._init();
  }

  _init() {
    this._setupStyle();
    this._createDefs();
    this._createGridGroup();
    this._createMaGroup();
    this._createCandleGroup();
    this._createVolumeGroup();
    this._createRpsGroup();
    this._createCrosshairGroup();
    this._createAxes();
    this._createTooltip();
    this._bindEvents();
  }

  _setupStyle() {
    const s = this.svg;
    s.style.display = 'block';
    s.style.userSelect = 'none';
    s.style.cursor = 'crosshair';
    s.style.background = this.cfg.chartBackground || '#0d1117';
  }

  _createDefs() {
    const ns = 'http://www.w3.org/2000/svg';
    const defs = document.createElementNS(ns, 'defs');
    // Clip path for plot area
    this.clipId = 'kc-clip';
    const clip = document.createElementNS(ns, 'clipPath');
    clip.setAttribute('id', this.clipId);
    this.clipRect = document.createElementNS(ns, 'rect');
    clip.appendChild(this.clipRect);
    defs.appendChild(clip);
    this.svg.appendChild(defs);
  }

  _createGridGroup() {
    const ns = 'http://www.w3.org/2000/svg';
    this.gridGroup = document.createElementNS(ns, 'g');
    this.gridGroup.setAttribute('class', 'kc-grids');
    this.svg.appendChild(this.gridGroup);

    this.gridLines = {
      price: document.createElementNS(ns, 'g'),
      volume: document.createElementNS(ns, 'g'),
    };
    for (const g of Object.values(this.gridLines)) {
      g.setAttribute('fill', 'none');
      g.setAttribute('stroke', this.cfg.gridColor);
      g.setAttribute('stroke-width', '0.5');
      g.setAttribute('opacity', '0.6');
      this.gridGroup.appendChild(g);
    }
  }

  _createMaGroup() {
    const ns = 'http://www.w3.org/2000/svg';
    this.maGroup = document.createElementNS(ns, 'g');
    this.maGroup.setAttribute('class', 'kc-ma');
    this.maGroup.setAttribute('clip-path', `url(#${this.clipId})`);
    this.svg.appendChild(this.maGroup);

    const maColors = [this.cfg.ma5Color, this.cfg.ma10Color];
    this.maLines = {};
    for (let i = 0; i < this.maWindows.length; i++) {
      const g = document.createElementNS(ns, 'g');
      g.setAttribute('fill', 'none');
      g.setAttribute('stroke', maColors[i]);
      g.setAttribute('stroke-width', '1.2');
      this.maGroup.appendChild(g);
      this.maLines[this.maWindows[i]] = g;
    }
  }

  _createCandleGroup() {
    const ns = 'http://www.w3.org/2000/svg';
    this.candleGroup = document.createElementNS(ns, 'g');
    this.candleGroup.setAttribute('class', 'kc-candles');
    this.candleGroup.setAttribute('clip-path', `url(#${this.clipId})`);
    this.svg.appendChild(this.candleGroup);
  }

  _createVolumeGroup() {
    const ns = 'http://www.w3.org/2000/svg';
    this.volumeGroup = document.createElementNS(ns, 'g');
    this.volumeGroup.setAttribute('class', 'kc-volume');
    this.volumeGroup.setAttribute('clip-path', `url(#${this.clipId})`);
    this.svg.appendChild(this.volumeGroup);
  }

  _createRpsGroup() {
    const ns = 'http://www.w3.org/2000/svg';
    this.rpsGroup = document.createElementNS(ns, 'g');
    this.rpsGroup.setAttribute('class', 'kc-rps');
    this.rpsGroup.setAttribute('clip-path', `url(#${this.clipId})`);
    this.svg.appendChild(this.rpsGroup);

    this.rpsGuideLine = document.createElementNS(ns, 'line');
    this.rpsGuideLine.setAttribute('x1', this.cfg.marginLeft);
    this.rpsGuideLine.setAttribute('x2', 10000);
    this.rpsGuideLine.setAttribute('stroke', this.cfg.rpsGuideColor);
    this.rpsGuideLine.setAttribute('stroke-width', '0.8');
    this.rpsGuideLine.setAttribute('stroke-dasharray', '4,4');
    this.rpsGroup.appendChild(this.rpsGuideLine);

    this.rpsLine20 = document.createElementNS(ns, 'path');
    this.rpsLine20.setAttribute('fill', 'none');
    this.rpsLine20.setAttribute('stroke', this.cfg.rps20Color);
    this.rpsLine20.setAttribute('stroke-width', '1.5');
    this.rpsGroup.appendChild(this.rpsLine20);

    this.rpsLine50 = document.createElementNS(ns, 'path');
    this.rpsLine50.setAttribute('fill', 'none');
    this.rpsLine50.setAttribute('stroke', this.cfg.rps50Color);
    this.rpsLine50.setAttribute('stroke-width', '1.3');
    this.rpsGroup.appendChild(this.rpsLine50);

    this.rpsLine120 = document.createElementNS(ns, 'path');
    this.rpsLine120.setAttribute('fill', 'none');
    this.rpsLine120.setAttribute('stroke', this.cfg.rps120Color);
    this.rpsLine120.setAttribute('stroke-width', '1.2');
    this.rpsGroup.appendChild(this.rpsLine120);

    this.rpsLine250 = document.createElementNS(ns, 'path');
    this.rpsLine250.setAttribute('fill', 'none');
    this.rpsLine250.setAttribute('stroke', this.cfg.rps250Color);
    this.rpsLine250.setAttribute('stroke-width', '1.2');
    this.rpsGroup.appendChild(this.rpsLine250);
  }

  _createCrosshairGroup() {
    const ns = 'http://www.w3.org/2000/svg';
    this.crosshairGroup = document.createElementNS(ns, 'g');
    this.crosshairGroup.setAttribute('class', 'kc-crosshair');
    this.crosshairGroup.style.display = 'none';
    this.svg.appendChild(this.crosshairGroup);

    this.crosshairVLine = document.createElementNS(ns, 'line');
    this.crosshairVLine.setAttribute('stroke', this.cfg.crosshairColor);
    this.crosshairVLine.setAttribute('stroke-width', '0.8');
    this.crosshairVLine.setAttribute('stroke-dasharray', '3,3');
    this.crosshairGroup.appendChild(this.crosshairVLine);

    this.crosshairHLine = document.createElementNS(ns, 'line');
    this.crosshairHLine.setAttribute('stroke', this.cfg.crosshairColor);
    this.crosshairHLine.setAttribute('stroke-width', '0.8');
    this.crosshairHLine.setAttribute('stroke-dasharray', '3,3');
    this.crosshairGroup.appendChild(this.crosshairHLine);

    this.crosshairDot = document.createElementNS(ns, 'circle');
    this.crosshairDot.setAttribute('r', '3');
    this.crosshairDot.setAttribute('fill', this.cfg.upColor);
    this.crosshairGroup.appendChild(this.crosshairDot);
  }

  _createAxes() {
    const ns = 'http://www.w3.org/2000/svg';
    this.axesGroup = document.createElementNS(ns, 'g');
    this.axesGroup.setAttribute('class', 'kc-axes');
    this.svg.appendChild(this.axesGroup);

    this.priceAxisYLabels = document.createElementNS(ns, 'g');
    this.priceAxisYLabels.setAttribute('class', 'kc-axis-y-price');
    this.axesGroup.appendChild(this.priceAxisYLabels);

    this.volumeAxisYLabels = document.createElementNS(ns, 'g');
    this.volumeAxisYLabels.setAttribute('class', 'kc-axis-y-vol');
    this.axesGroup.appendChild(this.volumeAxisYLabels);

    this.xAxisGroup = document.createElementNS(ns, 'g');
    this.xAxisGroup.setAttribute('class', 'kc-axis-x');
    this.axesGroup.appendChild(this.xAxisGroup);
  }

  _createTooltip() {
    const ns = 'http://www.w3.org/2000/svg';
    this.tooltip = document.createElementNS(ns, 'g');
    this.tooltip.setAttribute('class', 'kc-tooltip');
    this.tooltip.style.display = 'none';
    this.svg.appendChild(this.tooltip);

    const bg = document.createElementNS(ns, 'rect');
    bg.setAttribute('fill', '#1e1e2e');
    bg.setAttribute('rx', '4');
    bg.setAttribute('ry', '4');
    bg.setAttribute('stroke', '#3a3a5a');
    bg.setAttribute('stroke-width', '0.8');
    this.tooltipBg = bg;
    this.tooltip.appendChild(bg);

    this.tooltipText = document.createElementNS(ns, 'text');
    this.tooltipText.setAttribute('fill', '#ccccee');
    this.tooltipText.setAttribute('font-size', '11');
    this.tooltipText.setAttribute('font-family', 'monospace');
    this.tooltip.appendChild(this.tooltipText);
  }

  _bindEvents() {
    this.svg.addEventListener('wheel', (e) => this._onWheel(e), { passive: false });
    this.svg.addEventListener('pointerdown', (e) => this._onPointerDown(e));
    this.svg.addEventListener('pointermove', (e) => this._onPointerMove(e));
    this.svg.addEventListener('pointerup', () => this._onPointerUp());
    this.svg.addEventListener('pointerleave', () => this._onPointerLeave());
  }

  _getPlotDims() {
    const rect = this.svg.getBoundingClientRect();
    const w = rect.width || 800;
    const h = rect.height || 500;
    const mt = this.cfg.marginTop;
    const mb = this.cfg.marginBottom;
    const ml = this.cfg.marginLeft;
    const mr = this.cfg.marginRight;
    const totalChartH = h - mt - mb;
    const priceH = Math.floor(totalChartH * this.cfg.priceHeightRatio);
    const volH = Math.floor(totalChartH * this.cfg.volumeHeightRatio);
    const rpsH = Math.floor(totalChartH * this.cfg.rpsHeightRatio);
    const gap = Math.floor(totalChartH * this.cfg.gapRatio);
    const plotW = w - ml - mr;
    return {
      w, h, mt, mb, ml, mr,
      plotW, totalChartH, priceH, volH, rpsH, gap,
      priceTop: mt,
      volumeTop: mt + priceH + gap,
      rpsTop: mt + priceH + gap + volH + gap,
    };
  }

  _rpsToY(rpsValue) {
    const d = this._getPlotDims();
    // RPS range 0..100 → maps to full rpsH (no padding)
    return d.rpsTop + d.rpsH * (1 - rpsValue / 100);
  }

  _getBarX(i, barW) {
    return this.cfg.marginLeft + i * (barW + this.cfg.candleSpacing);
  }

  load(bars, rpsHistory = [], preset = 60) {
    this.bars = bars || [];
    this.rpsHistory = rpsHistory || [];
    this._computeMA();
    const total = this.bars.length;
    if (preset === -1 || preset >= total) {
      this.visible = { windowStart: 0, windowEnd: total, visibleWindow: total };
    } else {
      const ws = Math.max(0, total - preset);
      this.visible = { windowStart: ws, windowEnd: Math.min(ws + preset, total), visibleWindow: preset };
    }
    this.render();
  }

  _computeMA() {
    this.maSeries = {};
    const closes = this.bars.map((b) => b.close);
    for (const w of this.maWindows) {
      this.maSeries[w] = closes.map((_, i) => {
        if (i < w - 1) return null;
        const slice = closes.slice(i - w + 1, i + 1);
        return slice.reduce((a, b) => a + b, 0) / w;
      });
    }
  }

  render() {
    if (!this.bars.length) return;
    this._updateClipRect();
    this._renderGrid();
    this._renderVolume();
    this._renderRps();
    this._renderCandles();
    this._renderMA();
    this._renderAxes();
  }

  _updateClipRect() {
    const d = this._getPlotDims();
    this.clipRect.setAttribute('x', d.ml);
    this.clipRect.setAttribute('y', d.mt);
    this.clipRect.setAttribute('width', d.plotW);
    // Extend clip to the bottom of the SVG so RPS area (which exceeds
    // totalChartH due to stacked sections with gaps) is not clipped.
    this.clipRect.setAttribute('height', d.h - d.mt + 1);
  }

  _renderGrid() {
    const d = this._getPlotDims();
    const { priceTop, priceH, volumeTop, volH } = d;

    // Price grid — 5 lines
    const priceG = this.gridLines.price;
    priceG.innerHTML = '';
    const priceMin = this._priceMin();
    const priceMax = this._priceMax();
    for (let i = 0; i <= 4; i++) {
      const y = priceTop + (priceH * i) / 4;
      const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l.setAttribute('x1', d.ml);
      l.setAttribute('x2', d.ml + d.plotW);
      l.setAttribute('y1', y);
      l.setAttribute('y2', y);
      priceG.appendChild(l);
    }

    // Volume grid — 2 lines
    const volG = this.gridLines.volume;
    volG.innerHTML = '';
    for (let i = 0; i <= 2; i++) {
      const y = volumeTop + (volH * i) / 2;
      const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l.setAttribute('x1', d.ml);
      l.setAttribute('x2', d.ml + d.plotW);
      l.setAttribute('y1', y);
      l.setAttribute('y2', y);
      volG.appendChild(l);
    }

    // RPS area horizontal guides at 50 and 80
    if (this.rpsHistory && this.rpsHistory.length) {
      for (const rpsVal of [50, 80]) {
        const y = this._rpsToY(rpsVal);
        const gl = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        gl.setAttribute('x1', d.ml);
        gl.setAttribute('x2', d.ml + d.plotW);
        gl.setAttribute('y1', y);
        gl.setAttribute('y2', y);
        gl.setAttribute('stroke', this.cfg.rpsGuideColor);
        gl.setAttribute('stroke-width', '0.5');
        gl.setAttribute('stroke-dasharray', '3,3');
        gl.setAttribute('opacity', '0.5');
        this.rpsGroup.insertBefore(gl, this.rpsGroup.firstChild);
      }
    }
  }

  _renderRps() {
    if (!this.rpsHistory || !this.rpsHistory.length) return;
    const d = this._getPlotDims();
    const barW = this._barWidth();
    const spacing = this.cfg.candleSpacing;
    const rpsByDate = new Map(this.rpsHistory.map(r => [r.trading_day, r]));

    const buildPoints = (key) => {
      // First pass: collect all valid (localI, x, y) points
      const valid = [];
      for (let localI = 0; localI < this.visible.visibleWindow; localI++) {
        const globalI = this.visible.windowStart + localI;
        const bar = this.bars[globalI];
        if (!bar) continue;
        const rpsRow = rpsByDate.get(bar.trading_day);
        if (!rpsRow) continue;
        const rpsVal = rpsRow[key];
        if (rpsVal === null || rpsVal === undefined) continue;
        const x = d.ml + localI * (barW + spacing) + barW / 2;
        const y = this._rpsToY(rpsVal);
        valid.push({ localI, x, y });
      }
      if (valid.length === 0) return [];

      // Second pass: output one entry per localI, using linear interpolation for gaps
      const out = [];
      for (let localI = 0; localI < this.visible.visibleWindow; localI++) {
        const x = d.ml + localI * (barW + spacing) + barW / 2;
        // Find bracket valid points
        let p = null, n = null;
        for (let j = 0; j < valid.length; j++) {
          if (valid[j].localI <= localI) p = valid[j];
          if (valid[j].localI >= localI && n === null) n = valid[j];
        }
        if (p && n && p.localI === n.localI) {
          // Same point is both prev and next (only one valid point)
          out.push({ x, y: p.y });
        } else if (p && n) {
          // Interpolate
          const t = (localI - p.localI) / (n.localI - p.localI);
          out.push({ x, y: p.y + (n.y - p.y) * t });
        } else if (p) {
          out.push({ x, y: p.y });
        } else if (n) {
          out.push({ x, y: n.y });
        } else {
          out.push(null);
        }
      }
      return out;
    };

    const pts20 = buildPoints('rps_20');
    const pts50 = buildPoints('rps_50');
    const pts120 = buildPoints('rps_120');
    const pts250 = buildPoints('rps_250');

    const toPath = (pts) => {
      const valid = pts.filter(p => p !== null);
      if (valid.length === 0) return '';
      const segs = [];
      for (let i = 0; i < pts.length; i++) {
        const p = pts[i];
        if (p === null) continue;
        segs.push(i === 0 || pts[i - 1] === null
          ? `M${p.x.toFixed(1)},${p.y.toFixed(1)}`
          : `L${p.x.toFixed(1)},${p.y.toFixed(1)}`);
      }
      return segs.join(' ');
    };

    this.rpsLine20.setAttribute('d', toPath(pts20));
    this.rpsLine50.setAttribute('d', toPath(pts50));
    this.rpsLine120.setAttribute('d', toPath(pts120));
    this.rpsLine250.setAttribute('d', toPath(pts250));
  }

  _priceMin() {
    const vis = this._visibleBars();
    let min = Infinity;
    for (const b of vis) {
      if (b.low < min) min = b.low;
    }
    return min;
  }

  _priceMax() {
    const vis = this._visibleBars();
    let max = -Infinity;
    for (const b of vis) {
      if (b.high > max) max = b.high;
    }
    return max;
  }

  _volumeMax() {
    const vis = this._visibleBars();
    let max = 0;
    for (const b of vis) {
      if (b.volume > max) max = b.volume;
    }
    return max;
  }

  _visibleBars() {
    return this.bars.slice(this.visible.windowStart, this.visible.windowEnd);
  }

  _barWidth() {
    const d = this._getPlotDims();
    const totalSlots = this.visible.visibleWindow;
    return Math.max(1, Math.floor(d.plotW / totalSlots) - this.cfg.candleSpacing);
  }

  _priceToY(price) {
    const d = this._getPlotDims();
    const pMin = this._priceMin();
    const pMax = this._priceMax();
    const range = pMax - pMin || 1;
    return d.priceTop + d.priceH * (1 - (price - pMin) / range);
  }

  _volToY(vol) {
    const d = this._getPlotDims();
    const vMax = this._volumeMax() || 1;
    return d.volumeTop + d.volH * (1 - vol / vMax);
  }

  _renderCandles() {
    const cg = this.candleGroup;
    cg.innerHTML = '';
    const bars = this._visibleBars();
    const barW = this._barWidth();
    const d = this._getPlotDims();

    for (let localI = 0; localI < bars.length; localI++) {
      const globalI = this.visible.windowStart + localI;
      const bar = bars[localI];
      const x = d.ml + localI * (barW + this.cfg.candleSpacing);
      const isUp = bar.close >= bar.open;
      const color = isUp ? this.cfg.upColor : this.cfg.downColor;

      // Wick
      const wick = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      wick.setAttribute('x1', x + barW / 2);
      wick.setAttribute('x2', x + barW / 2);
      wick.setAttribute('y1', this._priceToY(bar.high));
      wick.setAttribute('y2', this._priceToY(bar.low));
      wick.setAttribute('stroke', color);
      wick.setAttribute('stroke-width', '1');
      cg.appendChild(wick);

      // Body
      const bodyY = this._priceToY(Math.max(bar.open, bar.close));
      const bodyH = Math.max(1, Math.abs(this._priceToY(bar.open) - this._priceToY(bar.close)));
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', x);
      rect.setAttribute('y', bodyY);
      rect.setAttribute('width', barW);
      rect.setAttribute('height', bodyH);
      rect.setAttribute('fill', color);
      rect.setAttribute('rx', '0.5');
      cg.appendChild(rect);
    }
  }

  _renderVolume() {
    const vg = this.volumeGroup;
    vg.innerHTML = '';
    const bars = this._visibleBars();
    const barW = this._barWidth();
    const d = this._getPlotDims();

    for (let localI = 0; localI < bars.length; localI++) {
      const bar = bars[localI];
      const x = d.ml + localI * (barW + this.cfg.candleSpacing);
      const isUp = bar.close >= bar.open;
      const color = isUp ? this.cfg.upColor : this.cfg.downColor;

      const y = this._volToY(bar.volume);
      const h = Math.max(1, d.volumeTop + d.volH - y);
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', x);
      rect.setAttribute('y', y);
      rect.setAttribute('width', barW);
      rect.setAttribute('height', h);
      rect.setAttribute('fill', color);
      rect.setAttribute('opacity', '0.6');
      rect.setAttribute('rx', '0.5');
      vg.appendChild(rect);
    }
  }

  _renderMA() {
    const d = this._getPlotDims();
    const barW = this._barWidth();
    const colors = [this.cfg.ma5Color, this.cfg.ma10Color];

    for (let mi = 0; mi < this.maWindows.length; mi++) {
      const w = this.maWindows[mi];
      const g = this.maLines[w];
      g.innerHTML = '';

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const segs = [];
      let started = false;

      for (let localI = 0; localI < this.visible.visibleWindow; localI++) {
        const globalI = this.visible.windowStart + localI;
        const maVal = this.maSeries[w]?.[globalI];
        if (maVal === null || maVal === undefined) continue;
        const x = d.ml + localI * (barW + this.cfg.candleSpacing) + barW / 2;
        const y = this._priceToY(maVal);
        segs.push(started ? `L${x.toFixed(1)},${y.toFixed(1)}` : `M${x.toFixed(1)},${y.toFixed(1)}`);
        started = true;
      }
      path.setAttribute('d', segs.join(' '));
      path.setAttribute('stroke', colors[mi]);
      path.setAttribute('stroke-width', '1.3');
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke-linejoin', 'round');
      g.appendChild(path);
    }
  }

  _renderAxes() {
    const d = this._getPlotDims();
    const bars = this._visibleBars();
    const barW = this._barWidth();
    const axisLabelX = d.w - 4;

    // Price Y axis labels
    const pG = this.priceAxisYLabels;
    pG.innerHTML = '';
    const pMin = this._priceMin();
    const pMax = this._priceMax();
    for (let i = 0; i <= 4; i++) {
      const price = pMin + (pMax - pMin) * (4 - i) / 4;
      const y = d.priceTop + (d.priceH * i) / 4;
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', d.w - 4);
      t.setAttribute('y', y + 4);
      t.setAttribute('fill', this.cfg.textColor);
      t.setAttribute('font-size', '10');
      t.setAttribute('font-family', 'monospace');
      t.setAttribute('text-anchor', 'end');
      t.textContent = price.toFixed(2);
      pG.appendChild(t);
    }

    // Volume Y axis
    const vG = this.volumeAxisYLabels;
    vG.innerHTML = '';
    const vMax = this._volumeMax();
    for (let i = 0; i <= 2; i++) {
      const vol = vMax * (2 - i) / 2;
      const y = d.volumeTop + (d.volH * i) / 2;
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', axisLabelX);
      t.setAttribute('y', y + 4);
      t.setAttribute('fill', this.cfg.textColor);
      t.setAttribute('font-size', '10');
      t.setAttribute('font-family', 'monospace');
      t.setAttribute('text-anchor', 'end');
      t.textContent = vol >= 1_000_000 ? `${(vol / 1_000_000).toFixed(1)}M` : vol >= 1_000 ? `${(vol / 1_000).toFixed(0)}K` : `${vol}`;
      vG.appendChild(t);
    }

    // X axis date labels
    const xG = this.xAxisGroup;
    xG.innerHTML = '';
    const step = Math.max(1, Math.floor(bars.length / 6));
    for (let localI = 0; localI < bars.length; localI += step) {
      const globalI = this.visible.windowStart + localI;
      const bar = bars[localI];
      if (!bar) continue;
      const x = d.ml + localI * (barW + this.cfg.candleSpacing) + barW / 2;
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', x);
      t.setAttribute('y', d.h - 6);
      t.setAttribute('fill', this.cfg.labelColor);
      t.setAttribute('font-size', '10');
      t.setAttribute('font-family', 'monospace');
      t.setAttribute('text-anchor', 'middle');
      t.textContent = bar.trading_day.slice(5); // MM-DD
      xG.appendChild(t);
    }

    // RPS axis labels
    if (this.rpsHistory && this.rpsHistory.length) {
      this._renderRpsAxisLabels(d);
    }
  }

  _renderRpsAxisLabels(d) {
    // Clear old RPS axis labels and legend (they accumulate otherwise)
    this._rpsAxisLabels = this._rpsAxisLabels || [];
    for (const t of this._rpsAxisLabels) t.remove();
    this._rpsAxisLabels = [];

    const rpsVals = [0, 50, 80, 100];
    const colors = [this.cfg.textColor, this.cfg.rpsGuideColor, this.cfg.rpsGuideColor, this.cfg.textColor];
    const yTexts = [d.rpsTop + d.rpsH, this._rpsToY(50), this._rpsToY(80), d.rpsTop];
    const axisLabelX = d.w - 4;
    for (let i = 0; i < rpsVals.length; i++) {
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', axisLabelX);
      t.setAttribute('y', yTexts[i] + 4);
      t.setAttribute('fill', colors[i]);
      t.setAttribute('font-size', '10');
      t.setAttribute('font-family', 'monospace');
      t.setAttribute('text-anchor', 'end');
      t.textContent = rpsVals[i];
      this.axesGroup.appendChild(t);
      this._rpsAxisLabels.push(t);
    }
    // Legend
    const legendItems = [
      { label: 'RPS20', color: this.cfg.rps20Color },
      { label: 'RPS50', color: this.cfg.rps50Color },
      { label: 'RPS120', color: this.cfg.rps120Color },
      { label: 'RPS250', color: this.cfg.rps250Color },
    ];
    legendItems.forEach((item, idx) => {
      const ly = d.rpsTop + 12 + idx * 14;
      const lt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      lt.setAttribute('x', d.ml + 4);
      lt.setAttribute('y', ly);
      lt.setAttribute('fill', item.color);
      lt.setAttribute('font-size', '10');
      lt.setAttribute('font-family', 'monospace');
      lt.textContent = item.label;
      this.axesGroup.appendChild(lt);
      this._rpsAxisLabels.push(lt);
    });
  }

  _setCrosshair(visibleIndex, clientX, clientY) {
    if (visibleIndex === null) {
      this.crosshairGroup.style.display = 'none';
      this.tooltip.style.display = 'none';
      return;
    }
    const ns = 'http://www.w3.org/2000/svg';
    const d = this._getPlotDims();
    const barW = this._barWidth();
    const x = d.ml + visibleIndex * (barW + this.cfg.candleSpacing) + barW / 2;
    const bars = this._visibleBars();
    const bar = bars[visibleIndex];
    if (!bar) return;
    const y = this._priceToY(bar.close);

    this.crosshairGroup.style.display = 'block';
    this.crosshairVLine.setAttribute('x1', x);
    this.crosshairVLine.setAttribute('x2', x);
    this.crosshairVLine.setAttribute('y1', d.priceTop);
    this.crosshairVLine.setAttribute('y2', d.volumeTop + d.volH);

    this.crosshairHLine.setAttribute('x1', d.ml);
    this.crosshairHLine.setAttribute('x2', d.ml + d.plotW);
    this.crosshairHLine.setAttribute('y1', y);
    this.crosshairHLine.setAttribute('y2', y);

    this.crosshairDot.setAttribute('cx', x);
    this.crosshairDot.setAttribute('cy', y);
    this.crosshairDot.setAttribute('fill', bar.close >= bar.open ? this.cfg.upColor : this.cfg.downColor);

    // Tooltip
    const lines = [
      `日期: ${bar.trading_day}`,
      `最高价: ${bar.high}`,
      `最低价: ${bar.low}`,
      `收盘价: ${bar.close}`,
    ];
    const padding = 6;
    const lineH = 13;
    const tw = 144;
    const th = lines.length * lineH + padding * 2;

    // Position tooltip to avoid edges
    let tx = x + 8;
    if (tx + tw > d.ml + d.plotW) tx = x - tw - 8;
    let ty = Math.max(d.mt, y - th / 2);
    if (ty + th > d.h - d.mb) ty = d.h - d.mb - th;

    this.tooltipBg.setAttribute('x', tx);
    this.tooltipBg.setAttribute('y', ty);
    this.tooltipBg.setAttribute('width', tw);
    this.tooltipBg.setAttribute('height', th);

    this.tooltipText.setAttribute('x', tx + padding);
    this.tooltipText.setAttribute('y', ty + padding + 10);
    this.tooltipText.textContent = '';
    lines.forEach((line, index) => {
      const tspan = document.createElementNS(ns, 'tspan');
      tspan.setAttribute('x', tx + padding);
      if (index === 0) {
        tspan.setAttribute('dy', '0');
      } else {
        tspan.setAttribute('dy', String(lineH));
      }
      tspan.textContent = line;
      this.tooltipText.appendChild(tspan);
    });
    this.tooltip.style.display = 'block';
  }

  _onWheel(e) {
    e.preventDefault();
    const d = this._getPlotDims();
    const rect = this.svg.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const plotLeft = d.ml;
    const plotRight = d.ml + d.plotW;
    if (mouseX < plotLeft || mouseX > plotRight) return;

    const anchorRatio = (mouseX - plotLeft) / d.plotW;
    const total = this.bars.length;
    const factor = e.deltaY < 0 ? 0.85 : 1.15;
    const nextSize = Math.round(this.visible.visibleWindow * factor);
    const { clamp } = { clamp: (v, lo, hi) => Math.max(lo, Math.min(hi, v)) };
    const clampedSize = clamp(nextSize, 10, total);
    const anchorIndex = this.visible.windowStart + Math.round(this.visible.visibleWindow * anchorRatio);
    const rawStart = anchorIndex - Math.round(clampedSize * anchorRatio);
    const ws = clamp(rawStart, 0, Math.max(0, total - clampedSize));

    this.visible = {
      windowStart: ws,
      windowEnd: Math.min(ws + clampedSize, total),
      visibleWindow: clampedSize,
    };
    this.render();
    if (this.onViewportChange) this.onViewportChange(this.visible);
  }

  _onPointerDown(e) {
    this.isDragging = true;
    this.dragStartClientX = e.clientX;
    this.dragStartWindowStart = this.visible.windowStart;
    this.svg.style.cursor = 'grabbing';
  }

  _onPointerMove(e) {
    const rect = this.svg.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const d = this._getPlotDims();

    if (this.isDragging) {
      const dx = e.clientX - this.dragStartClientX;
      const barW = this._barWidth() + this.cfg.candleSpacing;
      const deltaBars = Math.round(dx / barW);
      const total = this.bars.length;
      const { clamp } = { clamp: (v, lo, hi) => Math.max(lo, Math.min(hi, v)) };
      const newWs = clamp(this.dragStartWindowStart - deltaBars, 0, Math.max(0, total - this.visible.visibleWindow));
      this.visible = {
        windowStart: newWs,
        windowEnd: Math.min(newWs + this.visible.visibleWindow, total),
        visibleWindow: this.visible.visibleWindow,
      };
      this.render();
      if (this.onViewportChange) this.onViewportChange(this.visible);
      return;
    }

    // Hover detection
    const plotLeft = d.ml;
    const plotRight = d.ml + d.plotW;
    if (mouseX < plotLeft || mouseX > plotRight) {
      this._setCrosshair(null);
      return;
    }
    const barW = this._barWidth() + this.cfg.candleSpacing;
    const visIndex = Math.floor((mouseX - plotLeft) / barW);
    if (visIndex < 0 || visIndex >= this.visible.visibleWindow) {
      this._setCrosshair(null);
      return;
    }
    this._setCrosshair(visIndex, e.clientX, e.clientY);
  }

  _onPointerUp() {
    this.isDragging = false;
    this.svg.style.cursor = 'crosshair';
  }

  _onPointerLeave() {
    this._setCrosshair(null);
    if (this.isDragging) this._onPointerUp();
  }

  setPreset(preset) {
    const total = this.bars.length;
    if (preset === -1 || preset >= total) {
      this.visible = { windowStart: 0, windowEnd: total, visibleWindow: total };
    } else {
      const ws = Math.max(0, total - preset);
      this.visible = { windowStart: ws, windowEnd: Math.min(ws + preset, total), visibleWindow: preset };
    }
    this.render();
    if (this.onViewportChange) this.onViewportChange(this.visible);
  }

  getVisibleRange() {
    if (!this.bars.length) return { start: '', end: '' };
    const bars = this._visibleBars();
    return { start: bars[0]?.trading_day || '', end: bars[bars.length - 1]?.trading_day || '' };
  }
}
