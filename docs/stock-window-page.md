# Stock Window Volume Page

This repo includes a small local stock dashboard served by Python stdlib only.

## Run

Start the server from the repo root:

```bash
python3 scripts/serve_stock_dashboard.py
```

Then open:

```text
http://127.0.0.1:8765/
```

The page calls:

```text
/api/stock-window-volume?symbol=601600
```

Notes:

- The frontend includes shared chart window controls: `20D`, `60D`, `120D`, and `ALL`, plus a scrubber to pan the visible range when a fixed window is active.
- The two volume metric cards and the two volume charts display in millions (`M`) by dividing raw API values by `1,000,000`. The close-price chart remains unscaled.
- A shared `Volume MA window` numeric control defaults to `50` and updates a dashed trailing moving-average line on the two volume charts only.
- Mouse wheel zoom works directly on every chart and keeps the shared presets and scrubber synchronized. Dragging inside a chart pans the visible range when a fixed window is active.
- All three SVG charts stay synchronized to the same visible history window, including wheel zoom, drag pan, and hover crosshair state.
- Charts render horizontal and vertical grid lines, clearer axis labels, and a hover tooltip panel with the trading day plus the hovered series value. Volume axis ticks and tooltip values also use `M`.
- Pure viewport math lives in `web/viewport.js`, with a minimal Node built-in test in `tests/viewport.test.js`.
- The backend reads local Tongdaxin data from `/mnt/c/new_tdx64`.
- It invokes `/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python` by subprocess to load `daily()` and `minute()` history.
- The current API handles one symbol per request and returns structured JSON errors when data is unavailable.
