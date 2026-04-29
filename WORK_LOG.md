# PEA Analytics — Work Log
**Account:** M GENTY MATTHIEU | Crédit Mutuel PEA  
**Opened:** 05/02/2025 | **Tax-free from:** 05/02/2030 | **Max deposit:** €150,000  
**Stack:** Python 3.12 · Dash · SQLite · pandas · yfinance · Plotly  
**Last updated:** 2026-04-29

---

## 1. What Was Built (Initial System)

A full local analytics dashboard for a French PEA brokerage account. Built from scratch as a ~2,500-line Python project with 17 files.

### Entry Points

| Command | Effect |
|---------|--------|
| `python main.py` | Ingest + launch dashboard (default) |
| `python main.py --ingest` | Ingest CSV + refresh prices only |
| `python main.py --dashboard` | Launch dashboard only (uses cached DB) |
| `python main.py --report` | Terminal performance/risk/cost report |
| `python main.py --force` | Skip validation gate on ingestion |

Dashboard at **http://localhost:8050**

### Project Structure

```
pea_analytics/
├── main.py                    # CLI entry point
├── config.py                  # All fee constants, PEA metadata, thresholds
├── requirements.txt
├── data/
│   ├── transactions.csv       # User-edited transaction history
│   └── pea_analytics.db       # SQLite (auto-created)
├── db/
│   └── models.py              # SQLAlchemy schema: Transaction, Price, Fundamental
├── ingestion/
│   ├── parser.py              # CSV parse → FIFO cost basis → DB upsert
│   ├── market_data.py         # yfinance price/fundamentals fetcher
│   └── validator.py           # NEW (Phase 1) — pre-ingestion field tagger
├── analytics/
│   ├── performance.py         # TWR, IRR/MWR, PnL, benchmark comparison
│   ├── costs.py               # Broker fees, TTF, spread, slippage, break-even
│   └── risk.py                # Volatility, Sharpe, VaR, drawdown, frontier
├── recommendations/
│   └── engine.py              # BUY/HOLD/REDUCE/EXIT signals
└── dashboard/
    └── app.py                 # 6-page Dash app (~740 lines)
```

### Dashboard Pages

| URL | Content |
|-----|---------|
| `/` | Portfolio value vs benchmark, KPIs, allocation, cost overview |
| `/performance` | TWR, IRR, drawdown chart, invested vs market value |
| `/risk` | Correlation heatmap, Sharpe, beta, VaR, efficient frontier |
| `/costs` | Broker fees, TTF, spread, slippage, break-even per position |
| `/screening` | European PEA universe ranked by composite score |
| `/recommendations` | BUY/HOLD/REDUCE/EXIT signal cards with reasoning |
| `/validate` | NEW (Phase 1) — color-coded CSV validation review table |

---

## 2. Crédit Mutuel Fee Structure (Encoded in config.py)

Source: *Fiche Clarté Tarification Titres et Bourse — Conditions 01/2026*

| Fee | Rate | Rule |
|-----|------|------|
| Euronext stocks (standard) | 0.50% | First 10 qualifying orders in 12M |
| Euronext stocks (Fidélité tier 2) | 0.35% | 11–20 orders >€2,000 in rolling 12M |
| Euronext stocks (Fidélité tier 3) | 0.25% | 21+ orders >€2,000 in rolling 12M |
| ETF / OPC buy | 0.50% | On purchase only |
| ETF / OPC sell | **FREE** | No exit fee |
| Intraday discount | 50% off | 2nd order same stock, same qty, same day |
| TTF | 0.40% | BUY only, French large-caps >€1B market cap |
| Custody (per semester) | 0.125% | Min €6, max €75 — charged Jun 30 / Dec 31 |
| Transfer out | €15/line | Max €150 per PEA |

**TTE.PA (TotalEnergies) example:**
- 5 × €55.67 = €278.35 notional
- Broker fee: €1.39 (0.50%)
- TTF: €1.11 (0.40%)
- Total entry cost: **€280.85**

---

## 3. Current Holdings (as of audit 2026-03-12)

| Ticker | Name | Shares | Entry Dates |
|--------|------|--------|-------------|
| ESE.PA | BNPP Easy S&P 500 UCITS ETF | 2 | 2025-03-11, 2025-04-09, 2026-01-12 (SELL 20), 2026-01-20 (BUY 12) |
| TTE.PA | TotalEnergies SE | 5 | 2026-01-20 |

**Full transaction history:**

| Date | Type | Security | Qty | Price |
|------|------|----------|-----|-------|
| 2025-02-05 | DEPOSIT | Initial deposit | — | €1,000.00 |
| 2025-03-11 | BUY | ESE.PA | 10 | €25.7102 |
| 2025-04-09 | BUY | ESE.PA | 10 | €22.6234 |
| 2026-01-12 | SELL | ESE.PA | -20 | €30.1632 |
| 2026-01-20 | BUY | TTE.PA | 5 | €55.67 |
| 2026-01-20 | BUY | ESE.PA | 12 | €29.5352 |

---

## 4. Audit — Bugs Found (2026-03-12)

A full audit of the codebase found 7 bugs:

| # | File | Bug | Severity |
|---|------|-----|----------|
| 1 | `analytics/performance.py` | IRR was timing `t` from each transaction date, not from start — wrong MWR | High |
| 2 | `analytics/performance.py` | TWR not sub-period-aware: no reset at BUY/SELL events (only at DEPOSIT) | Medium |
| 3 | `config.py` | Benchmark hardcoded to CAC 40 (`^FCHI`) — bad for an S&P 500 ETF-heavy portfolio | Medium |
| 4 | `ingestion/parser.py` | Intraday 50% discount defined in config but never applied | Medium |
| 5 | `analytics/performance.py` | TTF not included in realized gain FIFO cost basis — P&L overstated | Medium |
| 6 | `analytics/costs.py` | Custody fee loop hardcoded to 2026 — PEA locked until 2030 | Low |
| 7 | `ingestion/parser.py` | Fidélité Bourse tier lookup used 365-day subtraction instead of 12 calendar months — wrong around leap years | Low |

---

## 5. Phase 1 Fixes (2026-03-12)

All 7 bugs fixed. Changes by file:

### config.py
- Changed `BENCHMARK_TICKER` from `"^FCHI"` (CAC 40) to `"^STOXX50E"` (Euro Stoxx 50) — better fit for a mixed European/US portfolio
- Added `BENCHMARK_LABEL = "Euro Stoxx 50"`
- Added `BENCHMARK_OPTIONS` dict with three choices: Euro Stoxx 50, CAC 40, S&P 500

### ingestion/parser.py
- Added `_subtract_12_months(d)` helper — uses `d.replace(year=d.year-1)` with leap-year guard (Feb 29 → Feb 28) instead of `timedelta(days=365)`
- Implemented intraday discount: tracks `(date, ticker, qty)` keys in `_daily_orders`; applies 50% rate reduction from the 2nd order onward
- Added `force=False` parameter to `ingest_transactions()` — allows bypassing the validation gate
- Extracted `_compute_all_fees()` so the fee engine runs once before both validation and ingestion loop

### ingestion/validator.py (NEW FILE)
- Full pre-ingestion data quality layer
- Tags every field in every row as `confirmed` / `inferred` / `missing`
- Required fields: `date`, `ticker`, `quantity`, `exec_price`, `type`
- Optional fields auto-inferred with sensible defaults: `fees`, `name`, `asset_type`, `market`, `currency`
- Fee field shows computed engine amount (not CSV `0.0`) when `fees=0` in CSV
- Semantic warnings: zero price on BUY/SELL, positive qty on SELL, future dates
- CLI: prints `print_validation_report()` on every `--ingest` run
- Dashboard: `validation_to_dataframe()` returns styled table with `[~]` / `[!]` prefixes

### analytics/performance.py
- **IRR fix:** `t` now computed as `(row.date - start_date).days / 365.25` for all external cash flows; `final_value` terminal CF uses `(today - start_date).days / 365.25`
- **TWR fix:** sub-period boundaries now include BUY and SELL dates (not only DEPOSIT) via Modified Dietz; cumulative return chains correctly across sub-periods
- **TTF in FIFO:** realized gain calculation includes TTF per share in cost basis: `buys["exec_price"] + (buys["broker_fee"] + buys["ttf"]) / buys["quantity"].clip(lower=1)`
- Added `benchmark_ticker=` parameter to `build_portfolio_value_series()` — lets dashboard pass user selection at runtime

### analytics/costs.py
- `compute_custody_fees()` now dynamic: generates semester end-dates from `PEA_OPEN_DATE.year` through `PEA_LOCK_END_DATE.year + 1` via `_generate_semester_ends()` — covers full PEA life without hardcoded year cap
- `_get_exit_broker_rate()` returns `ETF_SELL_FEE = 0.0` for ETF assets (Crédit Mutuel: OPC sells are free) — break-even table now reflects zero exit cost for ESE.PA

### ingestion/market_data.py
- Added `_yfinance_download_with_retry()` — 3 attempts with exponential backoff (1s, 2s, 4s)
- Added `_fetch_prices_from_db()` — reads cached SQLite prices when yfinance fails
- `fetch_prices()` now: try yfinance with retry → fall back to DB cache → report result

### dashboard/app.py
- Added `/validate` page: renders color-coded `validation_to_dataframe()` output, confirms/inferred/missing rows
- Added benchmark dropdown on Performance page — passes selected ticker to `build_portfolio_value_series(benchmark_ticker=...)`

### main.py
- Added `--force` CLI flag — passed through to `ingest_transactions(force=True)`
- Default combined mode (`python main.py`) uses `force=True` so it never blocks unattended
- `--ingest` mode prints validation report before ingestion

---

## 6. Architecture Decisions

- **No DB rebuild on re-run:** transactions are upserted; fees are updated if precision changed (tolerance: >1e-6 on fees, >1e-4 on total_cost)
- **Fee engine runs once per ingest:** `_compute_all_fees()` pre-computes all fees so both the validator and the ingestion loop read from the same `computed_*` columns — engine state not replayed twice
- **yfinance fallback chain:** live → retry → cached SQLite — dashboard never crashes on network failure
- **Backward compatibility preserved:** `python main.py` behaves identically to pre-Phase-1 from the user's perspective

---

## 7. PEA Tax Context

| Event | Tax |
|-------|-----|
| Withdrawal before 05/02/2030 | PFU 30% (12.8% IR + 17.2% PS) + closes the PEA |
| Withdrawal after 05/02/2030 | Social charges only: 17.2% |
| Dividends inside PEA | Tax-free |
| Max lifetime contribution | €150,000 |

---

## 8. Known Remaining Gaps (Not Yet Fixed)

- Refinitiv/LSEG API not wired — all fundamentals come from yfinance (functional but shallower)
- Screening universe (`SCREENING_UNIVERSE` in `market_data.py`) is static — no auto-update
- No SELL fee in TTF list (TTF is BUY-only by law, so this is correct, but the eligible ticker list is manually maintained)
- Risk page efficient frontier uses historical covariance — does not re-optimize on portfolio changes automatically

---

## 9. How to Add a New Transaction

Edit `data/transactions.csv`. Columns:

| Column | Required | Example |
|--------|----------|---------|
| date | Yes | 2026-04-29 |
| ticker | Yes | ESE.PA |
| name | No | BNPP Easy S&P 500 UCITS ETF |
| quantity | Yes | 5 (BUY) or -5 (SELL) |
| exec_price | Yes | 28.40 |
| fees | No | 0 (auto-computed) |
| type | Yes | BUY / SELL / DIVIDEND / DEPOSIT |
| currency | No | EUR |
| asset_type | No | ETF or STOCK |
| market | No | EURONEXT |

Then run: `python main.py --ingest`

---

*Log maintained by Claude Code · Anthropic*
