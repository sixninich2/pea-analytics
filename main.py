#!/usr/bin/env python3
# main.py
"""
PEA Analytics System — Main Entry Point
Usage:
    python main.py              # Ingest data + launch dashboard
    python main.py --ingest     # Only ingest / refresh data
    python main.py --dashboard  # Only launch dashboard (no refresh)
    python main.py --report     # Print performance report to terminal
"""
import sys
import os
import argparse
from datetime import date

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(__file__))


def run_ingestion(verbose=True, force=False):
    """Step 1: Ingest transactions and fetch market data.

    force=True  — skip validation gate (useful when running non-interactively
                  or when data has already been reviewed).
    """
    print("\n" + "=" * 60)
    print("  PEA Analytics - Data Ingestion")
    print("=" * 60)

    # Init DB
    from db.models import init_db
    init_db()

    # Ingest transactions
    print("\n[1/4] Parsing transactions...")
    from ingestion.parser import ingest_transactions, get_transactions_df
    txs_path = os.path.join("data", "transactions.csv")
    if not os.path.exists(txs_path):
        print(f"  [ERROR] File not found: {txs_path}")
        print("  -> Add your transactions to data/transactions.csv")
        return
    ingest_transactions(txs_path, verbose=verbose, force=force)

    # Fetch prices for held tickers + benchmark
    print("\n[2/4] Fetching market prices...")
    from ingestion.parser import get_transactions_df
    from ingestion.market_data import fetch_prices, SCREENING_UNIVERSE
    from config import BENCHMARK_TICKER

    txs = get_transactions_df()
    tickers = list(txs["ticker"].unique()) if not txs.empty else []
    tickers = [t for t in tickers if t not in ("DEPOSIT", "CASH")]
    all_tickers = list(set(tickers + [BENCHMARK_TICKER]))
    fetch_prices(all_tickers, store=True)

    # Compute and display performance
    print("\n[3/4] Computing performance metrics...")
    try:
        from analytics.performance import compute_performance_summary
        summary = compute_performance_summary()
        if summary:
            print(f"  Portfolio value:     €{summary['current_value']:,.2f}")
            print(f"  Total return:        {summary['total_return_pct']:+.2f}%")
            print(f"  TWR:                 {summary['twr']:+.2f}%")
            print(f"  CAC 40 return:       {summary['benchmark_return']:+.2f}%")
            print(f"  Alpha:               {summary['alpha']:+.2f}%")
            print(f"  IRR (MWR):           {summary['mwr_irr']:+.2f}%")
            print(f"  Max drawdown:        {summary['max_drawdown_pct']:.2f}%")
            print(f"  Total broker fees:   €{summary['total_broker_fees']:.2f}")
            print(f"  TTF paid:            €{summary['total_ttf']:.2f}")
            days_left = (date(2030, 2, 5) - date.today()).days
            print(f"  PEA lock-in:         {days_left} days remaining (-> 05/02/2030)")
    except Exception as e:
        print(f"  [ERROR] Performance error: {e}")

    # Quick risk report
    print("\n[4/4] Computing risk metrics...")
    try:
        from analytics.risk import compute_full_risk_report
        risk = compute_full_risk_report()
        if "portfolio_vol_pct" in risk:
            print(f"  Portfolio volatility: {risk['portfolio_vol_pct']:.2f}% p.a.")
            print(f"  Sharpe ratio:         {risk['portfolio_sharpe']:.3f}")
            var = risk.get("var", {})
            print(f"  VaR (95%, 1D):        {var.get('var_1d_pct', 0):.3f}%")
    except Exception as e:
        print(f"  [ERROR] Risk error: {e}")

    print("\n[OK] Ingestion complete")


def run_dashboard():
    """Step 2: Launch interactive Dash dashboard."""
    print("\n" + "=" * 60)
    print("  PEA Analytics - Dashboard")
    print("=" * 60)
    print(f"\n  [OK] Starting server...")
    print(f"  [OK] Open your browser: http://localhost:8050")
    print(f"  [OK] Press Ctrl+C to stop\n")

    from dashboard.app import app
    from config import DASH_PORT, DASH_DEBUG
    app.run(debug=DASH_DEBUG, port=DASH_PORT, host="127.0.0.1")


def run_report():
    """Print full analytics report to terminal."""
    print("\n" + "=" * 60)
    print("  PEA Analytics - Terminal Report")
    print("=" * 60)

    from analytics.performance import compute_performance_summary
    from analytics.costs import compute_cost_summary, position_break_even_table
    from analytics.risk import compute_full_risk_report
    from ingestion.parser import get_transactions_df
    from config import PEA_OWNER, PEA_BROKER, PEA_OPEN_DATE, PEA_LOCK_END_DATE

    print(f"\n  Account: {PEA_OWNER} | {PEA_BROKER}")
    print(f"  Opened:  {PEA_OPEN_DATE} | Tax-free: {PEA_LOCK_END_DATE}")

    summary = compute_performance_summary()
    if summary:
        print("\n  -- PERFORMANCE ─────────────────────────")
        for k, v in summary.items():
            print(f"    {k:<25} {v}")

    txs = get_transactions_df()
    costs = compute_cost_summary(txs)
    if costs:
        print("\n  -- COSTS ───────────────────────────────")
        for k, v in costs.items():
            print(f"    {k:<25} {v}")

    be = position_break_even_table()
    if not be.empty:
        print("\n  -- BREAK-EVEN ANALYSIS ─────────────────")
        print(be.to_string(index=False))

    risk = compute_full_risk_report()
    if "portfolio_vol_pct" in risk:
        print("\n  -- RISK ────────────────────────────────")
        print(f"    Volatility:   {risk['portfolio_vol_pct']:.2f}% p.a.")
        print(f"    Sharpe:       {risk['portfolio_sharpe']:.3f}")
        print(f"    Max Drawdown: {risk['max_drawdown']['max_drawdown_pct']:.2f}%")

    from recommendations.engine import generate_recommendations
    recs = generate_recommendations()
    if recs:
        print("\n  -- RECOMMENDATIONS ─────────────────────")
        for r in recs:
            print(f"    [{r['signal']:12}] {r['ticker']:10} "
                  f"Score:{r['composite_score']:5.1f}  "
                  f"Weight:{r['weight_pct']:5.1f}%  "
                  f"P&L:{r['pnl_pct']:+6.2f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PEA Analytics System")
    parser.add_argument("--ingest",    action="store_true", help="Ingest data only")
    parser.add_argument("--dashboard", action="store_true", help="Launch dashboard only")
    parser.add_argument("--report",    action="store_true", help="Print terminal report")
    parser.add_argument("--force",     action="store_true",
                        help="Skip validation gate (use when data is already reviewed)")
    args = parser.parse_args()

    if args.ingest:
        run_ingestion(force=args.force)
    elif args.dashboard:
        run_dashboard()
    elif args.report:
        run_report()
    else:
        # Default: ingest + launch (non-interactive; validation prints but does not block)
        run_ingestion(force=True)
        run_dashboard()
