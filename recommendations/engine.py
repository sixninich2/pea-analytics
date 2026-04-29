# recommendations/engine.py
"""
Recommendation Engine
- Compares current portfolio vs optimal allocation
- Generates BUY / HOLD / REDUCE / EXIT signals
- Considers PEA eligibility, transaction costs, diversification
"""
import pandas as pd
import numpy as np
from datetime import date
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    MIN_WEIGHT, MAX_WEIGHT, BROKER_FEE_STANDARD, TTF_RATE,
    TTF_ELIGIBLE_TICKERS, PEA_LOCK_END_DATE, PEA_OPEN_DATE
)
from ingestion.parser import compute_positions
from ingestion.market_data import fetch_latest_prices, fetch_fundamentals_yfinance, SCREENING_UNIVERSE
from analytics.risk import compute_full_risk_report, get_returns
from analytics.costs import position_break_even_table


# ─── Signal Definitions ───────────────────────────────────────────────────────
SIGNALS = {
    "STRONG BUY": {"color": "#00875A", "icon": "⬆⬆"},
    "BUY":        {"color": "#00A86B", "icon": "⬆"},
    "HOLD":       {"color": "#F5A623", "icon": "→"},
    "REDUCE":     {"color": "#E8522A", "icon": "⬇"},
    "EXIT":       {"color": "#D0021B", "icon": "⬇⬇"},
}

# Rebalance threshold: only act when weight deviation > 5%
REBALANCE_THRESHOLD = 0.05


def generate_recommendations(session=None) -> list[dict]:
    """
    Main entry point. Returns list of recommendation dicts, one per holding
    + candidates from screening.
    """
    positions = compute_positions(session=session)
    if positions.empty:
        return _no_positions_message()

    held_tickers = positions["ticker"].tolist()
    latest_prices = fetch_latest_prices(held_tickers)

    # Portfolio market values
    total_value = sum(
        latest_prices.get(t, r["avg_cost"]) * r["quantity"]
        for t, r in zip(positions["ticker"], positions.to_dict("records"))
    )

    # Risk report
    risk = compute_full_risk_report(session=session)

    # Break-even table
    be_table = position_break_even_table(session=session)
    be_lookup = {}
    if not be_table.empty:
        be_lookup = {r["ticker"]: r for _, r in be_table.iterrows()}

    # Fundamentals for held tickers
    fundamentals = fetch_fundamentals_yfinance(held_tickers, store=False)
    fund_lookup = {}
    if not fundamentals.empty:
        fund_lookup = {r["ticker"]: r for _, r in fundamentals.iterrows()}

    # Risk contributions
    rc_lookup = {}
    if "risk_contributions" in risk:
        for rc in risk["risk_contributions"]:
            rc_lookup[rc["ticker"]] = rc

    recommendations = []
    for _, pos in positions.iterrows():
        tk = pos["ticker"]
        current_price = latest_prices.get(tk, pos["avg_cost"])
        market_value  = current_price * pos["quantity"]
        weight        = market_value / total_value if total_value > 0 else 0
        pnl_pct       = (current_price / pos["avg_cost"] - 1) * 100 if pos["avg_cost"] > 0 else 0

        fund  = fund_lookup.get(tk, {})
        be    = be_lookup.get(tk, {})
        rc    = rc_lookup.get(tk, {})
        score = float(fund.get("composite_score", 50)) if fund else 50

        # Transaction cost of reducing
        exit_fee = market_value * BROKER_FEE_STANDARD
        if tk in TTF_ELIGIBLE_TICKERS:
            exit_fee += 0  # TTF only on BUY

        reasons = []
        signal  = "HOLD"

        # ── Signal Logic ──────────────────────────────────────────────────────
        risk_contribution = rc.get("risk_contribution_pct", 0)

        if score >= 70 and weight < MIN_WEIGHT * 2 and pnl_pct > be.get("breakeven_vs_entry_pct", 0):
            signal = "STRONG BUY"
            reasons.append(f"High composite score ({score:.0f}/100)")
            reasons.append(f"Underweight at {weight*100:.1f}%")
        elif score >= 55 and weight < (MIN_WEIGHT + 0.10):
            signal = "BUY"
            reasons.append(f"Above-average score ({score:.0f}/100), room to add")
        elif score >= 35 and weight <= MAX_WEIGHT and risk_contribution < 35:
            signal = "HOLD"
            reasons.append(f"Score {score:.0f}/100 — maintain position")
        elif weight > MAX_WEIGHT:
            signal = "REDUCE"
            reasons.append(f"Overweight: {weight*100:.1f}% (max {MAX_WEIGHT*100:.0f}%)")
        elif risk_contribution > 40:
            signal = "REDUCE"
            reasons.append(f"Excess risk concentration: {risk_contribution:.1f}% of portfolio risk")
        elif score < 30:
            signal = "EXIT"
            reasons.append(f"Low composite score ({score:.0f}/100)")

        # Cost context
        if be:
            if not be.get("above_breakeven", True):
                reasons.append(
                    f"⚠ Below break-even price "
                    f"({be.get('current_price', 0):.2f} < {be.get('breakeven_price', 0):.2f})"
                )
            else:
                reasons.append(
                    f"Break-even cleared: {be.get('current_gain_pct', 0):.2f}% gain "
                    f"vs {be.get('breakeven_vs_entry_pct', 0):.2f}% needed"
                )

        # PEA lock-in context
        days_to_unlock = (PEA_LOCK_END_DATE - date.today()).days
        if days_to_unlock > 0 and signal in ("REDUCE", "EXIT"):
            reasons.append(
                f"⚠ PEA lock-in: {days_to_unlock} days to tax-free withdrawal "
                f"(05/02/2030). Consider holding to avoid PFU."
            )

        recommendations.append({
            "ticker":             tk,
            "name":               str(fund.get("name", tk)) if fund else tk,
            "signal":             signal,
            "signal_color":       SIGNALS[signal]["color"],
            "signal_icon":        SIGNALS[signal]["icon"],
            "current_price":      round(current_price, 4),
            "quantity":           pos["quantity"],
            "market_value":       round(market_value, 2),
            "weight_pct":         round(weight * 100, 2),
            "avg_cost":           round(pos["avg_cost"], 4),
            "pnl_pct":            round(pnl_pct, 2),
            "pnl_eur":            round((current_price - pos["avg_cost"]) * pos["quantity"], 2),
            "composite_score":    round(score, 1),
            "risk_contribution":  round(risk_contribution, 1),
            "breakeven_pct":      round(be.get("breakeven_vs_entry_pct", 0), 3),
            "exit_fee_est":       round(exit_fee, 2),
            "reasons":            reasons,
            "sector":             str(fund.get("sector", "N/A")) if fund else "N/A",
            "analyst_upside":     fund.get("analyst_upside") if fund else None,
        })

    # Add new candidate ideas from screening (not already held)
    candidates = _screen_new_candidates(held_tickers, total_value)
    recommendations.extend(candidates)

    return sorted(recommendations, key=lambda x: (
        ["STRONG BUY","BUY","HOLD","REDUCE","EXIT"].index(x["signal"]),
        -x.get("composite_score", 0)
    ))


def _screen_new_candidates(held_tickers: list[str],
                            portfolio_value: float) -> list[dict]:
    """Screen the European universe for potential new BUY candidates."""
    universe = [t for t in SCREENING_UNIVERSE if t not in held_tickers]
    if not universe:
        return []

    print("  Screening European universe for new candidates...")
    try:
        df = fetch_fundamentals_yfinance(universe[:20], store=False)
    except Exception:
        return []

    if df.empty:
        return []

    candidates = []
    for _, row in df.nlargest(5, "composite_score").iterrows():
        tk = row["ticker"]
        score = float(row.get("composite_score", 0))
        if score < 60:
            continue
        upside = row.get("analyst_upside")
        entry_cost = portfolio_value * MIN_WEIGHT  # Suggested entry notional
        broker_fee = entry_cost * BROKER_FEE_STANDARD
        ttf = entry_cost * TTF_RATE if tk in TTF_ELIGIBLE_TICKERS else 0
        breakeven = (broker_fee + ttf) / entry_cost * 100

        reasons = [
            f"Screening score: {score:.0f}/100 — top PEA universe candidate",
            f"Not currently held — adds diversification",
        ]
        if upside and not np.isnan(upside):
            reasons.append(f"Analyst consensus upside: {upside:.1f}%")
        if tk in TTF_ELIGIBLE_TICKERS:
            reasons.append(f"TTF applies on entry: {ttf:.2f}€ "
                           f"({TTF_RATE*100:.2f}% — French large-cap)")
        reasons.append(f"Break-even return needed: {breakeven:.2f}%")

        signal = "STRONG BUY" if score >= 75 else "BUY"
        candidates.append({
            "ticker":             tk,
            "name":               str(row.get("name", tk)),
            "signal":             signal,
            "signal_color":       SIGNALS[signal]["color"],
            "signal_icon":        SIGNALS[signal]["icon"],
            "current_price":      round(float(row.get("current_price", 0)), 2),
            "quantity":           0,
            "market_value":       0,
            "weight_pct":         0.0,
            "avg_cost":           0.0,
            "pnl_pct":            0.0,
            "pnl_eur":            0.0,
            "composite_score":    round(score, 1),
            "risk_contribution":  0.0,
            "breakeven_pct":      round(breakeven, 3),
            "exit_fee_est":       0.0,
            "reasons":            reasons,
            "sector":             str(row.get("sector", "N/A")),
            "analyst_upside":     upside if upside and not np.isnan(float(upside)) else None,
            "is_candidate":       True,
        })

    return candidates


def _no_positions_message() -> list[dict]:
    return [{
        "ticker": "—",
        "name": "No open positions found",
        "signal": "HOLD",
        "signal_color": SIGNALS["HOLD"]["color"],
        "signal_icon": SIGNALS["HOLD"]["icon"],
        "reasons": ["Import transactions first via data ingestion."],
        "composite_score": 0,
        "weight_pct": 0, "market_value": 0, "pnl_pct": 0,
        "pnl_eur": 0, "current_price": 0, "quantity": 0,
        "avg_cost": 0, "risk_contribution": 0, "breakeven_pct": 0,
        "exit_fee_est": 0, "sector": "—", "analyst_upside": None,
    }]
