# analytics/costs.py
"""
True Cost Analysis
- Broker fees per transaction
- TTF (Taxe sur les Transactions Financières)
- Custody fees (Frais de Convention — 0.125%/semester)
- Bid-ask spread estimate
- Slippage estimate
- Break-even return required
"""
import pandas as pd
import numpy as np
from datetime import date
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    CUSTODY_RATE_SEMI, CUSTODY_MIN_SEMI, CUSTODY_MAX_SEMI,
    BROKER_FEE_STANDARD, BROKER_FEE_TIER2, BROKER_FEE_TIER3,
    ETF_SELL_FEE, TTF_RATE, TTF_ELIGIBLE_TICKERS,
    PEA_OPEN_DATE, PEA_LOCK_END_DATE
)
from ingestion.parser import get_transactions_df, compute_positions
from ingestion.market_data import fetch_latest_prices


# ─── Spread & Slippage Estimates (by asset class) ─────────────────────────────
# Euronext Paris large-cap typical bid-ask spreads (one-way, % of mid)
SPREAD_ESTIMATES = {
    "STOCK_LARGECAP": 0.0008,   # ~0.08% for CAC 40 names
    "STOCK_MIDCAP":   0.0020,   # ~0.20% for mid-caps
    "ETF":            0.0005,   # ~0.05% for liquid ETFs like ESE
    "DEFAULT":        0.0015,
}

# Slippage: Almgren-Chriss approximation (simplified)
# slippage ≈ 0.1 × (order_notional / ADTV)^0.5
TYPICAL_ADTV = {
    "TTE.PA":  500_000_000,  # ~€500M ADTV (liquid large-cap)
    "ESE.PA":  50_000_000,   # ~€50M ADTV (ETF)
    "AIR.PA":  200_000_000,
    "MC.PA":   300_000_000,
    "DEFAULT": 100_000_000,
}


def compute_per_transaction_costs(txs: pd.DataFrame = None) -> pd.DataFrame:
    """
    Return detailed cost breakdown per transaction.
    Includes: broker_fee, ttf, spread_cost, slippage, total_round_trip,
              break_even_return_pct
    """
    if txs is None:
        txs = get_transactions_df()
    if txs.empty:
        return pd.DataFrame()

    records = []
    for _, row in txs.iterrows():
        if row["type"] not in ("BUY", "SELL"):
            continue

        notional = abs(row["quantity"]) * row["exec_price"]
        tk = row["ticker"]
        asset = row.get("asset_type", "STOCK")

        # Spread cost (one-way)
        if asset == "ETF":
            spread_rate = SPREAD_ESTIMATES["ETF"]
        elif tk in ["TTE.PA", "AIR.PA", "MC.PA", "OR.PA", "BNP.PA", "SAN.PA"]:
            spread_rate = SPREAD_ESTIMATES["STOCK_LARGECAP"]
        else:
            spread_rate = SPREAD_ESTIMATES["DEFAULT"]
        spread_cost = notional * spread_rate

        # Slippage (one-way)
        adtv = TYPICAL_ADTV.get(tk, TYPICAL_ADTV["DEFAULT"])
        slippage = notional * 0.1 * (notional / adtv) ** 0.5 if adtv > 0 else 0

        # Round-trip total (assumes one buy + one sell for each trade)
        round_trip = (row["broker_fee"] + row["ttf"] +
                      2 * spread_cost + 2 * slippage)

        # Break-even: return needed to recover round-trip cost
        be_return = (round_trip / notional * 100) if notional > 0 else 0

        records.append({
            "date": row["date"],
            "ticker": tk,
            "type": row["type"],
            "notional": round(notional, 2),
            "broker_fee": row["broker_fee"],
            "ttf": row["ttf"],
            "spread_cost_est": round(spread_cost, 2),
            "slippage_est": round(slippage, 4),
            "total_one_way": round(row["broker_fee"] + row["ttf"] + spread_cost, 2),
            "round_trip_total": round(round_trip, 2),
            "break_even_pct": round(be_return, 3),
            "fee_drag_pct": round((row["broker_fee"] + row["ttf"]) / notional * 100, 3),
        })

    return pd.DataFrame(records)


def _generate_semester_ends() -> dict:
    """
    Build semester end-date dict from PEA open year through one year past lock-end.
    Covers the full PEA lifetime without hardcoding years.
    """
    start_year = PEA_OPEN_DATE.year
    end_year   = PEA_LOCK_END_DATE.year + 1   # one extra year for safety
    result = {}
    for year in range(start_year, end_year + 1):
        result[f"S1 {year}"] = date(year, 6, 30)
        result[f"S2 {year}"] = date(year, 12, 31)
    return result


def compute_custody_fees(portfolio_values: dict[date, float]) -> pd.DataFrame:
    """
    Estimate custody fees (Frais de Convention) per semester.
    Fee = 0.125% × portfolio_value at end of Jun/Dec, capped €6–€75 per semester.
    Covers the full PEA lifetime dynamically (no hardcoded year cap).
    """
    records = []
    semester_ends = _generate_semester_ends()
    today = date.today()

    for period, end_date in semester_ends.items():
        if end_date > today:
            relevant_dates = [d for d in portfolio_values if d <= today]
            pv = portfolio_values[max(relevant_dates)] if relevant_dates else 0
        else:
            relevant_dates = [d for d in portfolio_values if d <= end_date]
            pv = portfolio_values[max(relevant_dates)] if relevant_dates else 0

        fee = max(CUSTODY_MIN_SEMI, min(CUSTODY_MAX_SEMI, pv * CUSTODY_RATE_SEMI))
        records.append({
            "period":              period,
            "end_date":            end_date,
            "portfolio_value_est": round(pv, 2),
            "custody_fee":         round(fee, 2) if pv > 0 else 0,
            "status":              "charged" if end_date <= today else "estimated",
        })
    return pd.DataFrame(records)


def _get_exit_broker_rate(txs: pd.DataFrame, asset_type: str) -> float:
    """
    Estimate the broker commission rate that would apply to an exit trade today.
    Applies Fidélité Bourse tiering from the actual transaction history.
    ETF sells are free at Crédit Mutuel.
    """
    from ingestion.parser import CreditMutuelFeeEngine

    # ETF sells are explicitly free (OPC: 0% exit)
    if asset_type == "ETF":
        return ETF_SELL_FEE  # 0.0

    # Replay qualifying BUY orders to determine current tier
    engine = CreditMutuelFeeEngine()
    buy_txs = txs[txs["type"] == "BUY"].sort_values("date")
    for _, row in buy_txs.iterrows():
        notional = abs(float(row["quantity"])) * float(row["exec_price"])
        if notional > 2000:
            engine._qualifying_orders.append({
                "date":     row["date"],
                "notional": notional,
            })

    n = engine._count_qualifying_orders(date.today())
    if n >= 20:
        return BROKER_FEE_TIER3
    elif n >= 10:
        return BROKER_FEE_TIER2
    return BROKER_FEE_STANDARD


def compute_cost_summary(txs: pd.DataFrame = None) -> dict:
    """High-level cost summary."""
    if txs is None:
        txs = get_transactions_df()
    if txs.empty:
        return {}

    buy_txs   = txs[txs["type"] == "BUY"]
    sell_txs  = txs[txs["type"] == "SELL"]
    total_buy_notional = (buy_txs["quantity"] * buy_txs["exec_price"]).sum()

    per_tx = compute_per_transaction_costs(txs)

    return {
        "total_broker_fees":    round(txs["broker_fee"].sum(), 2),
        "total_ttf":            round(txs["ttf"].sum(), 2),
        "total_spread_est":     round(per_tx["spread_cost_est"].sum(), 2) if not per_tx.empty else 0,
        "total_slippage_est":   round(per_tx["slippage_est"].sum(), 4) if not per_tx.empty else 0,
        "total_explicit_costs": round(txs["broker_fee"].sum() + txs["ttf"].sum(), 2),
        "total_all_in_costs":   round(per_tx["round_trip_total"].sum(), 2) if not per_tx.empty else 0,
        "n_trades":             len(buy_txs) + len(sell_txs),
        "avg_fee_rate":         round(txs["broker_fee"].sum() / total_buy_notional * 100, 3) if total_buy_notional else 0,
        "ttf_tickers":          list(txs[txs["ttf"] > 0]["ticker"].unique()),
    }


def position_break_even_table(session=None) -> pd.DataFrame:
    """
    For each open position, compute the break-even price:
    price at which the position recovers its entry costs.
    """
    positions = compute_positions(session=session)
    if positions.empty:
        return pd.DataFrame()

    txs = get_transactions_df(session)
    latest_prices = fetch_latest_prices(positions["ticker"].tolist())

    records = []
    for _, pos in positions.iterrows():
        tk = pos["ticker"]
        current_price = latest_prices.get(tk, pos["avg_cost"])

        # Entry costs per share
        buys = txs[(txs["ticker"] == tk) & (txs["type"] == "BUY")]
        total_fees = (buys["broker_fee"] + buys["ttf"]).sum()
        total_qty = buys["quantity"].sum()
        fee_per_share = total_fees / total_qty if total_qty > 0 else 0

        # Estimated exit cost using the actual tiered rate (or free for ETFs)
        asset_type    = "ETF" if txs[txs["ticker"] == tk]["asset_type"].iloc[0] == "ETF" else "STOCK"
        exit_rate     = _get_exit_broker_rate(txs, asset_type)
        exit_notional = pos["quantity"] * current_price
        exit_fee      = exit_notional * exit_rate

        # Break-even price (entry cost basis + exit fee)
        breakeven_price = pos["avg_cost"] + fee_per_share + (exit_fee / pos["quantity"])
        breakeven_pct = (breakeven_price / pos["avg_cost"] - 1) * 100 if pos["avg_cost"] > 0 else 0

        # Current profit/loss vs break-even
        current_gain_pct = (current_price / pos["avg_cost"] - 1) * 100 if pos["avg_cost"] > 0 else 0
        above_breakeven = current_price > breakeven_price

        records.append({
            "ticker": tk,
            "quantity": pos["quantity"],
            "avg_cost": round(pos["avg_cost"], 4),
            "current_price": round(current_price, 4),
            "breakeven_price": round(breakeven_price, 4),
            "breakeven_vs_entry_pct": round(breakeven_pct, 3),
            "current_gain_pct": round(current_gain_pct, 2),
            "above_breakeven": above_breakeven,
            "total_pnl_eur": round((current_price - pos["avg_cost"]) * pos["quantity"], 2),
        })

    return pd.DataFrame(records)
