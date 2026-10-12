# AGENTS.md — instructions for coding agents working in this repository

This repository contains four self-hosted price-monitoring dashboards for the
AI hardware supply chain (DRAM / NAND / eMMC / MLCC / glass-fabric boards).
Each board under `boards/<name>/` is self-contained: its own scraper package
(`tracker/`), its own dashboard (`dashboard/`), its own SQLite database.

## Cold start (deterministic, no API keys required)

```bash
python -m pip install -r requirements.txt
# optional, only needed if you want the browser-based scrapers:
#   python -m playwright install chromium

python -m boards.storage.tracker.update   # first run: 3-5 min, fills SQLite
python -m boards.storage.tracker.audit    # expect: PASS (some WARN ok)
python -m boards.storage.serve            # http://127.0.0.1:8790
```

Repeat per board (signal/mlcc/fabric use the same pattern; ports 8794/8792/8793).
`python -m scripts.make_demo_data` seeds synthetic series for storage/mlcc.
The fabric board is anchor-based: `python -m boards.fabric.tracker.update
--seed-anchors-only` seeds all news anchors offline.

## Hard rules (do not violate)

1. **Never fabricate data.** Boards deliberately show anchors/gaps instead of
   interpolated curves. If a source has no price today, record no row.
2. **Never mix calibers.** Different price calibers (spot / contract / retail /
   channel) are separate series. Never join them into one line.
3. **Scrape at most once per day per source.** These are public pages; hammering
   them gets your IP blocked (this is by design — see `ali.py` / `wxscan.py`
   circuit-breaker notes). Failed fetch = skip today, the scheduler retries
   tomorrow.
4. **All source timestamps are Asia/Shanghai (GMT+8).** Staleness checks use
   `tracker/tz.py`, not the machine's local timezone.
5. **Boards present phenomena; humans draw conclusions.** The signal board's
   red lamp means "cross-layer resonance detected" — it is a data statement,
   not trading advice.

## Known first-run behavior

- `audit` may report FAIL on coverage checks right after cold start (only one
  day of data). This is expected during the accumulation period; coverage
  checks turn PASS as daily runs accumulate.
- Some scrapers require JS rendering (Playwright). Without it those series
  stay empty — the rest of the board still works.
- TrendForce free pages stopped updating several module sections after
  2026-09-29; those series are fed by the CFM channel instead (see
  README "Source shrinkage log").

## Repository map

- `boards/signal/`   — AI capex & exit-signal board (port 8794)
- `boards/storage/`  — DRAM/NAND/SSD spot & contract prices (8790)
- `boards/mlcc/`     — MLCC distributor prices (8792)
- `boards/fabric/`   — glass-fabric board prices (8793)
- `hub/`             — landing page linking all boards (8800)
- `shared/`          — design system doc
- `scripts/`         — start-all script, demo data generator
