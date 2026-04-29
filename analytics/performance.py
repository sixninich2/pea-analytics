# analytics/performance.py
"""
Portfolio Performance Engine
- Portfolio value over time
- TWR (Time-Weighted Return)
- MWR / IRR (Money-Weighted Return)
- Realized and unrealized gains
- Benchmark comparison vs CAC 40
"""
import pandas as pd
import numpy as np
from datetime import date, timedelta
from scipy.optimize import brentq
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import BENCHMARK_TICKER, RISK_FREE_RATE, PEA_OPEN_DATE
from ingestion.parser import get_transactions_df, compute_positions
from ingestion.market_data import fetch_prices, fetch_latest_prices


# ─── Portfolio Value Timeline ─────────────────────────────────────────────────

def build_portfolio_value_series(session=None,
                                  benchmark_ticker: str = None) -> pd.DataFrame:
    """
    Compute daily portfolio value, invested capital, and benchmark.
    Returns DataFrame: date, portfolio_value, invested_capital, cash,
                       benchmark_indexed, twr_cumulative, drawdown
    """
    txs = get_transactions_df(session)
    if txs.empty:
        return pd.DataFrame()

    txs["date"] = pd.to_datetime(txs["date"]).dt.date
    tickers = [t for t in txs["ticker"].unique()
               if t not in ("DEPOSIT", "CASH")]

    start_date = min(txs["date"])
    end_date = date.today()

    # Use caller-supplied benchmark or fall back to config default
    bm_ticker = benchmark_ticker if benchmark_ticker else BENCHMARK_TICKER

    # Fetch price history
    prices = fetch_prices(
        tickers + [bm_ticker],
        start=start_date - timedelta(days=5),
        end=end_date,
        store=True
    )
    if prices.empty:
        return pd.DataFrame()

    prices.index = pd.to_datetime(prices.index).normalize().map(
        lambda x: x.date() if hasattr(x, 'date') else x
    )
    prices = prices.ffill()

    # Build daily date range (trading days = days where benchmark has data)
    bm_col = bm_ticker if bm_ticker in prices.columns else None
    date_range = sorted(prices.index)
    date_range = [d for d in date_range if d >= start_date]

    records = []
    holdings = {}       # {ticker: quantity}
    cash = 0.0
    total_invested = 0.0
    cumulative_dividends = 0.0

    # Index transactions by date
    tx_by_date = txs.groupby("date")

    for d in date_range:
        # Process transactions on this date
        if d in tx_by_date.groups:
            for _, row in tx_by_date.get_group(d).iterrows():
                tk = row["ticker"]
                if row["type"] == "DEPOSIT":
                    cash += row["exec_price"]
                    total_invested += row["exec_price"]
                elif row["type"] == "BUY":
                    qty = row["quantity"]
                    cost = row["total_cost"]
                    holdings[tk] = holdings.get(tk, 0) + qty
                    cash -= cost
                elif row["type"] == "SELL":
                    qty = abs(row["quantity"])
                    proceeds = abs(row["total_cost"])
                    holdings[tk] = holdings.get(tk, 0) - qty
                    cash += proceeds
                    if holdings[tk] < 0.001:
                        del holdings[tk]
                elif row["type"] == "DIVIDEND":
                    div_income = row["exec_price"]
                    cash += div_income
                    cumulative_dividends += div_income

        # Compute market value of holdings
        market_value = cash
        for tk, qty in holdings.items():
            if qty > 0:
                if tk in prices.columns:
                    px_series = prices[tk]
                    # Get last available price up to today
                    available = px_series[:d].dropna()
                    if not available.empty:
                        market_value += qty * float(available.iloc[-1])

        records.append({
            "date": d,
            "portfolio_value": round(market_value, 2),
            "cash": round(cash, 2),
            "invested_capital": round(total_invested, 2),
            "cumulative_dividends": round(cumulative_dividends, 2),
        })

    df = pd.DataFrame(records).set_index("date")
    if df.empty:
        return df

    # TWR
    df["twr"] = _compute_twr(df, txs)

    # Benchmark (indexed to 100 at start)
    if bm_col and bm_col in prices.columns:
        bm = prices[bm_col].reindex(df.index).ffill()
        bm_start = bm.iloc[0] if not bm.empty else 1
        df["benchmark_indexed"] = (bm / bm_start * 100).values
        df["benchmark_return"] = (bm / bm_start - 1) * 100
    else:
        df["benchmark_indexed"] = 100.0
        df["benchmark_return"] = 0.0

    # Portfolio indexed to 100
    v0 = df["portfolio_value"].iloc[0]
    df["portfolio_indexed"] = (df["portfolio_value"] / v0 * 100) if v0 > 0 else df["portfolio_value"]

    # Drawdown
    df["peak"] = df["portfolio_value"].cummax()
    df["drawdown"] = ((df["portfolio_value"] - df["peak"]) / df["peak"] * 100).fillna(0)

    return df.reset_index()


def _compute_twr(portfolio_df: pd.DataFrame, txs: pd.DataFrame) -> pd.Series:
    """
    Modified Dietz TWR approximation.
    Sub-periods are bounded by cash flow events (deposits/withdrawals).
    """
    df = portfolio_df.copy()
    txs = txs.copy()
    txs["date"] = pd.to_datetime(txs["date"]).dt.date

    cf_dates = txs[txs["type"].isin(["DEPOSIT", "WITHDRAW"])]["date"].unique()
    cf_dates = sorted(set(cf_dates) | {df.index[0], df.index[-1]})

    twr_series = pd.Series(index=df.index, dtype=float)
    cumulative = 1.0

    sub_start = df.index[0]
    for i, d in enumerate(df.index):
        if d in cf_dates and d != df.index[0]:
            # End of sub-period
            v_start = df.loc[sub_start, "portfolio_value"]
            v_end = df.loc[d, "portfolio_value"]
            # Net cash flows during sub-period
            cfs = txs[(txs["date"] > sub_start) & (txs["date"] <= d)]
            cf_sum = cfs[cfs["type"] == "DEPOSIT"]["exec_price"].sum()
            cf_sum -= cfs[cfs["type"] == "WITHDRAW"]["exec_price"].sum()
            adj_start = v_start + cf_sum * 0.5  # Modified Dietz
            sub_return = (v_end / adj_start - 1) if adj_start > 0 else 0
            cumulative *= (1 + sub_return)
            sub_start = d

        # Daily TWR = cumulative × sub-period progress
        v_start_p = df.loc[sub_start, "portfolio_value"]
        v_curr = df.loc[d, "portfolio_value"]
        sub_progress = (v_curr / v_start_p - 1) if v_start_p > 0 else 0
        twr_series[d] = (cumulative * (1 + sub_progress) - 1) * 100

    return twr_series


# ─── Performance Summary ──────────────────────────────────────────────────────

def compute_performance_summary(session=None) -> dict:
    """Return key performance metrics as a dict."""
    df = build_portfolio_value_series(session)
    if df.empty:
        return {}

    txs = get_transactions_df(session)
    current_value = df["portfolio_value"].iloc[-1]
    invested      = df["invested_capital"].iloc[-1]
    dividends     = df["cumulative_dividends"].iloc[-1]

    # Realized gains
    realized = _compute_realized_gains(txs)

    # Unrealized gains
    positions = compute_positions()
    latest_prices = {}
    if not positions.empty:
        latest_prices = fetch_latest_prices(positions["ticker"].tolist())
    unrealized = sum(
        (latest_prices.get(row["ticker"], row["avg_cost"]) - row["avg_cost"])
        * row["quantity"]
        for _, row in positions.iterrows()
    )

    # Total fees paid
    total_fees = txs[txs["type"].isin(["BUY", "SELL"])]["broker_fee"].sum()
    total_ttf  = txs["ttf"].sum()

    # MWR / IRR
    mwr = compute_irr(txs, current_value)

    # Benchmark
    bm_return = df["benchmark_return"].iloc[-1] if "benchmark_return" in df else 0

    # TWR
    twr = df["twr"].iloc[-1] if "twr" in df else 0

    # Max drawdown
    max_dd = df["drawdown"].min()

    # Days since opening
    days_held = (date.today() - PEA_OPEN_DATE).days
    years_remaining = max(0, (date(2030, 2, 5) - date.today()).days / 365.25)

    return {
        "current_value":     round(current_value, 2),
        "invested_capital":  round(invested, 2),
        "total_return_eur":  round(current_value - invested + dividends, 2),
        "total_return_pct":  round((current_value / invested - 1) * 100, 2) if invested else 0,
        "twr":               round(float(twr), 2),
        "mwr_irr":           round(mwr * 100, 2),
        "benchmark_return":  round(float(bm_return), 2),
        "alpha":             round(float(twr) - float(bm_return), 2),
        "realized_gains":    round(realized, 2),
        "unrealized_gains":  round(unrealized, 2),
        "dividends_received": round(dividends, 2),
        "total_broker_fees": round(total_fees, 2),
        "total_ttf":         round(total_ttf, 2),
        "total_costs":       round(total_fees + total_ttf, 2),
        "max_drawdown_pct":  round(float(max_dd), 2),
        "days_in_pea":       days_held,
        "years_to_tax_free": round(years_remaining, 1),
    }


def _compute_realized_gains(txs: pd.DataFrame) -> float:
    """Compute total realized PnL from completed trades."""
    if txs.empty:
        return 0.0
    sells = txs[txs["type"] == "SELL"]
    total_realized = 0.0
    for tk in sells["ticker"].unique():
        buys  = txs[(txs["ticker"] == tk) & (txs["type"] == "BUY")].copy()
        tsells = sells[sells["ticker"] == tk].copy()
        # FIFO match
        # Include both broker_fee AND ttf in the per-share cost basis
        fifo = list(zip(
            buys["quantity"],
            buys["exec_price"]
            + (buys["broker_fee"] + buys["ttf"]) / buys["quantity"].clip(lower=1)
        ))
        for _, sell_row in tsells.iterrows():
            remaining = abs(sell_row["quantity"])
            sell_net = abs(sell_row["total_cost"])
            sold_cost = 0.0
            i = 0
            while remaining > 0 and i < len(fifo):
                lot_qty, lot_price = fifo[i]
                take = min(remaining, lot_qty)
                sold_cost += take * lot_price
                fifo[i] = (lot_qty - take, lot_price)
                remaining -= take
                i += 1
            total_realized += sell_net - sold_cost
    return total_realized


def compute_irr(txs: pd.DataFrame, final_value: float) -> float:
    """
    Money-Weighted Return (IRR) for a PEA account.

    For a PEA, only deposits and withdrawals are external cash flows —
    BUY/SELL are internal movements within the account. IRR measures how
    well the deposits performed as a whole.

    Convention: t is measured in years from the first deposit (t=0).
    NPV = sum(cf / (1+r)^t) = 0  solves for r.
    """
    if txs.empty:
        return 0.0

    today = date.today()
    ext_txs = txs[txs["type"].isin(["DEPOSIT", "WITHDRAW"])].copy()
    if ext_txs.empty:
        return 0.0

    # Ensure dates are Python date objects for arithmetic
    ext_txs = ext_txs.copy()
    ext_txs["date"] = pd.to_datetime(ext_txs["date"]).dt.date
    start_date = ext_txs["date"].min()

    cfs: list[tuple[float, float]] = []
    for _, row in ext_txs.iterrows():
        t = (row["date"] - start_date).days / 365.25
        if row["type"] == "DEPOSIT":
            cfs.append((-row["exec_price"], t))   # investor puts money in
        else:
            cfs.append((+row["exec_price"], t))   # investor takes money out

    # Terminal value: current portfolio worth (includes fee drag via lower value)
    t_end = (today - start_date).days / 365.25
    if final_value > 0:
        cfs.append((final_value, t_end))

    if len(cfs) < 2:
        return 0.0

    def npv(r: float) -> float:
        return sum(cf / (1.0 + r) ** t for cf, t in cfs)

    try:
        return brentq(npv, -0.99, 50.0, maxiter=1000)
    except Exception:
        return 0.0
