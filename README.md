# PEA Analytics

A local analytics dashboard for a French PEA (Plan d'Épargne en Actions) brokerage account. Tracks transactions, computes performance and risk metrics, and produces a complete cost view that accounts for the actual French broker fee structure: tiered commissions, TTF on French large caps, custody fees, intraday discounts.

Built as a personal project to understand how a portfolio analytics stack is wired end to end, from CSV ingestion to risk metrics to a multi-page web dashboard.

## What it does

The application ingests a transaction history from CSV, validates and persists it to SQLite, fetches prices and fundamentals from yfinance, and exposes the results through a seven-page Dash interface running locally:

| Page | Content |
|------|---------|
| `/` | Portfolio value vs benchmark, KPIs, allocation, cost overview |
| `/performance` | TWR, IRR, drawdown, invested vs market value |
| `/risk` | Volatility, Sharpe, beta, VaR, correlation heatmap, efficient frontier |
| `/costs` | Broker fees, TTF, spread, slippage, break-even per position |
| `/screening` | European PEA-eligible universe ranked by composite score |
| `/recommendations` | BUY / HOLD / REDUCE / EXIT signal cards with reasoning |
| `/validate` | Pre-ingestion CSV review, fields tagged confirmed / inferred / missing |

## Tech stack

* Python 3.12
* Dash and Plotly for the web dashboard
* SQLAlchemy on SQLite for transaction and price persistence
* pandas for return and risk calculations
* yfinance for prices and fundamentals, with a retry plus DB cache fallback chain

## Architecture

```
pea_analytics/
├── main.py                    # CLI entry point
├── config.py                  # Fee constants, PEA metadata, thresholds
├── requirements.txt
├── data/                      # Local only, gitignored
├── db/
│   └── models.py              # Transaction, Price, Fundamental schema
├── ingestion/
│   ├── parser.py              # CSV → FIFO cost basis → DB upsert
│   ├── market_data.py         # yfinance fetcher with retry and DB fallback
│   └── validator.py           # Pre-ingestion field tagger
├── analytics/
│   ├── performance.py         # TWR, MWR / IRR, P&L, benchmark comparison
│   ├── costs.py               # Broker fees, TTF, spread, break-even
│   └── risk.py                # Vol, Sharpe, VaR, drawdown, frontier
├── recommendations/
│   └── engine.py              # Signal generation
├── screening/                 # Composite score ranking module
└── dashboard/
    ├── app.py                 # Seven-page Dash application
    └── pages/
```

## Crédit Mutuel fee model

The cost engine encodes the 2026 Crédit Mutuel PEA fee schedule:

* Tiered Euronext stock commission (0.50% / 0.35% / 0.25%) based on rolling twelve-month order count
* 0.50% buy fee on ETFs and OPCs, free on sale
* 50% intraday discount applied from the second order onward on the same security, same day
* 0.40% TTF on French large caps over €1B market cap, buy side only
* Semestrial custody fee (0.125%, min €6, max €75) generated dynamically through the PEA lock period

Realised P&L, break-even prices and benchmark comparisons all reflect what the account actually pays, not a generic 0.5% assumption.

## Built with Claude Code

The project was developed with Claude Code as a coding collaborator over two phases.

**Initial build.** Claude Code scaffolded the seventeen-file architecture, wrote the SQLAlchemy models, the CSV ingestion pipeline, the FIFO cost basis logic, the seven dashboard pages and the initial fee engine. Roughly 2,500 lines of Python.

**Phase 1 audit and fix.** A full code review surfaced seven bugs ranging from low to high severity:

1. IRR was timed from each transaction date instead of the portfolio start, producing the wrong money-weighted return
2. TWR did not reset sub-periods on BUY and SELL events, only on DEPOSIT
3. Benchmark was hardcoded to CAC 40 despite a portfolio with significant US ETF exposure
4. Intraday 50% discount was defined in config but never applied in the parser
5. TTF was excluded from the FIFO cost basis, overstating realised P&L
6. Custody fee loop was hardcoded to 2026 even though the PEA is locked through 2030
7. Fidélité Bourse tier lookup used a 365-day subtraction instead of twelve calendar months, breaking around leap years

All seven were fixed. The default benchmark moved to the Euro Stoxx 50 with a runtime dropdown on the performance page. A new `validator.py` module was inserted between CSV parsing and DB write so every field is tagged confirmed, inferred or missing before any data is persisted. yfinance fetches now retry with exponential backoff and fall back to the cached SQLite prices when the network fails.

Code was reviewed before each commit. Claude Code produced the implementation; the architecture, the financial logic and the validation criteria were specified and verified manually.

## Getting started

### Install

```bash
git clone https://github.com/sixninich2/pea-analytics.git
cd pea-analytics
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Create your transaction file

The repository does not ship with sample data. Create your own `data/transactions.csv` with the following columns:

| Column | Required | Example |
|--------|----------|---------|
| `date` | Yes | `2026-01-20` |
| `ticker` | Yes | `ESE.PA` |
| `name` | No | `BNPP Easy S&P 500 UCITS ETF` |
| `quantity` | Yes | `12` for BUY, negative on SELL |
| `exec_price` | Yes | `29.5352` |
| `fees` | No | `0` to auto-compute |
| `type` | Yes | `BUY` / `SELL` / `DIVIDEND` / `DEPOSIT` |
| `currency` | No | `EUR` |
| `asset_type` | No | `ETF` or `STOCK` |
| `market` | No | `EURONEXT` |

Optional columns are auto-inferred when blank by the validator module.

### Run

```bash
python main.py              # ingest plus launch dashboard (default)
python main.py --ingest     # ingest CSV and refresh prices only
python main.py --dashboard  # launch dashboard from cached DB
python main.py --report     # terminal performance, risk and cost report
python main.py --force      # skip the validation gate on ingestion
```

The dashboard opens at `http://localhost:8050`.

## Privacy

Real transaction data and the generated SQLite database are gitignored. The `data/` folder is intentionally empty in the repository; users provide their own CSV.

## Known gaps

* No Refinitiv / LSEG API integration; all fundamentals come from yfinance
* The screening universe in `market_data.py` is a static list, not auto-refreshed
* The efficient frontier uses historical covariance and is not re-optimised automatically on portfolio changes

## Disclaimer

Personal learning project. Nothing in this repository constitutes financial or investment advice.

## Author

Matthieu Genty, Master in Finance candidate, ESSCA School of Management.
[LinkedIn](https://www.linkedin.com/in/matthieu-genty/) · [GitHub](https://github.com/sixninich2)
