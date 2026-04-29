# PEA Analytics System
**M GENTY MATTHIEU — Crédit Mutuel PEA**
Opened: 05/02/2025 | Tax-free withdrawal: 05/02/2030

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run everything (ingest data + open dashboard)
python main.py

# 3. Open browser
open http://localhost:8050
```

---

## Project Structure

```
pea_analytics/
├── main.py                      # Entry point
├── config.py                    # Crédit Mutuel fee rules + account settings
├── requirements.txt
├── data/
│   └── transactions.csv         # YOUR REAL TRANSACTION HISTORY ← edit this
├── db/
│   └── models.py                # SQLite schema (auto-created)
├── ingestion/
│   ├── parser.py                # CSV ingestion + FIFO cost basis
│   └── market_data.py           # yfinance price fetcher + screening
├── analytics/
│   ├── performance.py           # TWR, IRR, PnL, benchmark
│   ├── costs.py                 # Hidden cost analysis + break-even
│   └── risk.py                  # Volatility, Sharpe, drawdown, frontier
├── recommendations/
│   └── engine.py                # BUY/HOLD/REDUCE signal generator
└── dashboard/
    └── app.py                   # Interactive Dash dashboard
```

---

## Adding Your Transactions

Edit `data/transactions.csv`. Required columns:

| Column | Description | Example |
|--------|-------------|---------|
| date | Trade date (YYYY-MM-DD) | 2025-03-11 |
| ticker | Euronext ticker (Yahoo Finance format) | ESE.PA |
| name | Full security name | BNPP Easy S&P 500 UCITS ETF |
| quantity | Shares bought (+) or sold (-) | 10 |
| exec_price | Execution price per share | 25.7102 |
| fees | Broker fee paid (leave 0 to auto-compute) | 12.86 |
| type | BUY / SELL / DIVIDEND / DEPOSIT | BUY |
| currency | EUR | EUR |
| asset_type | STOCK or ETF | ETF |
| market | EURONEXT | EURONEXT |

### Your Current Transactions (from SMS)

| Date | Action | Security | Qty | Price |
|------|--------|----------|-----|-------|
| 2025-02-05 | DEPOSIT | Initial deposit | — | 1000.00 |
| 2025-03-11 | BUY | BNPP Easy S&P 500 ETF (ESE.PA) | 10 | 25.7102 |
| 2025-04-09 | BUY | BNPP Easy S&P 500 ETF (ESE.PA) | 10 | 22.6234 |
| 2026-01-12 | SELL | BNPP Easy S&P 500 ETF (ESE.PA) | -20 | 30.1632 |
| 2026-01-20 | BUY | TotalEnergies SE (TTE.PA) | 5 | 55.67 |
| 2026-01-20 | BUY | BNPP Easy S&P 500 ETF (ESE.PA) | 12 | 29.5352 |

> Add any transactions you see in the SMS screenshots that are cut off.

---

## Crédit Mutuel Fee Structure (Encoded in config.py)

| Fee Type | Rate | Condition |
|----------|------|-----------|
| Euronext stocks (online) | **0.50%** | Standard (≤10 qualifying orders/12M) |
| Euronext stocks (online) | **0.35%** | Fidélité Bourse tier 2 (11–20 orders >2000€) |
| Euronext stocks (online) | **0.25%** | Fidélité Bourse tier 3 (21+ orders >2000€) |
| ETF / OPC (buy) | **0.50%** | On purchase only |
| ETF / OPC (sell) | **FREE** | No exit fee |
| TTF | **0.40%** | BUY only, French large-caps >1B€ market cap |
| Custody (Frais de Convention) | **0.125%/semester** | Min €6, max €75, calculated on Jun 30 / Dec 31 |
| Transfer out | **€15/line** | Max €150 per PEA |

**Your TotalEnergies (TTE.PA) buy incurs both broker fee + TTF:**
- 5 shares × 55.67€ = 278.35€ notional
- Broker fee: 278.35 × 0.50% = €1.39
- TTF: 278.35 × 0.40% = €1.11
- Total entry cost: €280.85

---

## PEA Tax Rules

| Event | Tax Treatment |
|-------|--------------|
| Gains before 5 years (before 05/02/2030) | PFU 30% (12.8% IR + 17.2% PS) |
| Gains after 5 years (after 05/02/2030) | Social charges only: 17.2% |
| Dividends inside PEA | Tax-free (no withholding) |
| Max lifetime contribution | €150,000 |
| Withdrawal before 5 years | Closes the PEA + full taxation |

---

## Dashboard Pages

| URL | Content |
|-----|---------|
| `/` | Portfolio value vs CAC 40, KPIs, allocation, costs |
| `/performance` | TWR, IRR, drawdown, invested vs market value |
| `/risk` | Correlation heatmap, Sharpe, beta, VaR, efficient frontier |
| `/costs` | Broker fees, TTF, spread, slippage, break-even per position |
| `/screening` | European PEA universe ranked by composite score |
| `/recommendations` | BUY/HOLD/REDUCE signal cards with reasoning |

---

## Commands

```bash
# Full run (default)
python main.py

# Only ingest / refresh prices
python main.py --ingest

# Only launch dashboard (uses cached DB data)
python main.py --dashboard

# Terminal report (no dashboard)
python main.py --report
```

---

## Optional: Refinitiv API

If you have LSEG Workspace or Refinitiv API credentials, set:

```env
# .env
REFINITIV_APP_KEY=your_key_here
```

The system will automatically use Refinitiv for fundamentals and screening.
Without it, yfinance is used — fully functional for all calculations.

---

*Built for M GENTY MATTHIEU · Crédit Mutuel PEA · Conditions 01/2026*
