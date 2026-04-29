# ingestion/parser.py
"""
Parses transaction CSV, applies Crédit Mutuel fee rules,
stores to SQLite via SQLAlchemy.
"""
import pandas as pd
import numpy as np
import os, sys
from datetime import date, timedelta
from collections import defaultdict


def _subtract_12_months(d: date) -> date:
    """Subtract exactly 12 calendar months, handling leap-year edge cases."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:          # Feb 29 in a leap year → Feb 28
        return d.replace(year=d.year - 1, day=28)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    BROKER_FEE_STANDARD, BROKER_FEE_TIER2, BROKER_FEE_TIER3,
    ETF_BUY_FEE, ETF_SELL_FEE, TTF_RATE, TTF_ELIGIBLE_TICKERS,
    INTRADAY_DISCOUNT
)
from db.models import Transaction, get_session


# ─── Fee Calculation Engine ────────────────────────────────────────────────────

class CreditMutuelFeeEngine:
    """
    Encodes the exact Crédit Mutuel fee schedule from:
    Fiche Clarté Tarification Titres et Bourse — Conditions 01/2026
    """

    def __init__(self):
        # Track rolling 12-month qualifying orders for Fidélité Bourse
        self._qualifying_orders: list[dict] = []  # {date, notional}
        # Track same-day orders for intraday discount: (date, ticker, qty) → count
        self._daily_orders: dict = {}

    def _count_qualifying_orders(self, as_of: date) -> int:
        """Count orders >2000€ in the rolling 12-calendar-month window ending as_of."""
        cutoff = _subtract_12_months(as_of)
        return sum(
            1 for o in self._qualifying_orders
            if cutoff <= o["date"] < as_of and o["notional"] > 2000
        )

    def _get_broker_rate(self, tx_date: date, notional: float,
                         asset_type: str, order_type: str) -> float:
        """
        Determine the applicable broker commission rate.
        ETF (OPC): 0.50% buy only, free on sell.
        Stocks on Euronext: 0.50% / 0.35% / 0.25% based on Fidélité Bourse tier.
        """
        if asset_type == "ETF":
            return ETF_BUY_FEE if order_type == "BUY" else ETF_SELL_FEE

        if order_type == "SELL":
            # Sells use same tiered rate as buys
            n = self._count_qualifying_orders(tx_date)
            if n >= 20:
                return BROKER_FEE_TIER3
            elif n >= 10:
                return BROKER_FEE_TIER2
            return BROKER_FEE_STANDARD

        # BUY on stock — check Fidélité Bourse tier
        n = self._count_qualifying_orders(tx_date)
        if notional > 2000:
            # This order will count toward future Fidélité Bourse threshold
            self._qualifying_orders.append({"date": tx_date, "notional": notional})
        if n >= 20:
            return BROKER_FEE_TIER3
        elif n >= 10:
            return BROKER_FEE_TIER2
        return BROKER_FEE_STANDARD

    def compute_fees(self, tx_date: date, ticker: str, quantity: float,
                     exec_price: float, asset_type: str, order_type: str,
                     override_fee: float = None) -> dict:
        """
        Returns dict with broker_fee, ttf, total_cost for a transaction.
        If override_fee is provided (from CSV), uses that instead of computing.
        """
        notional = abs(quantity) * exec_price

        if override_fee is not None and override_fee > 0:
            broker_fee = override_fee
        else:
            rate = self._get_broker_rate(tx_date, notional, asset_type, order_type)
            # Intraday discount: 50% off for the 2nd+ order of the same
            # (stock, quantity, day) — Source: Conditions 01/2026 p.3
            if order_type in ("BUY", "SELL") and asset_type != "ETF":
                intraday_key = (tx_date, ticker, round(abs(quantity), 4))
                prior_count = self._daily_orders.get(intraday_key, 0)
                self._daily_orders[intraday_key] = prior_count + 1
                if prior_count >= 1:
                    rate = rate * (1.0 - INTRADAY_DISCOUNT)
            broker_fee = round(notional * rate, 4)

        # TTF: only on BUY of French large-cap stocks
        ttf = 0.0
        if (order_type == "BUY" and asset_type == "STOCK"
                and ticker in TTF_ELIGIBLE_TICKERS):
            ttf = round(notional * TTF_RATE, 4)

        if order_type in ("BUY", "DEPOSIT"):
            total_cost = notional + broker_fee + ttf
        else:  # SELL
            total_cost = -(notional - broker_fee)

        return {
            "broker_fee": broker_fee,
            "ttf": ttf,
            "total_cost": round(total_cost, 4),
        }


# ─── CSV Parser ───────────────────────────────────────────────────────────────

def parse_csv(filepath: str) -> pd.DataFrame:
    """Parse the transaction CSV and normalize columns."""
    df = pd.read_csv(filepath, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.date

    # Handle optional columns
    if "fees" not in df.columns:
        df["fees"] = 0.0
    if "name" not in df.columns:
        df["name"] = df["ticker"]
    if "asset_type" not in df.columns:
        df["asset_type"] = "STOCK"
    if "market" not in df.columns:
        df["market"] = "EURONEXT"
    if "currency" not in df.columns:
        df["currency"] = "EUR"

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)
    df["exec_price"] = pd.to_numeric(df["exec_price"], errors="coerce").fillna(0)
    df["fees"] = pd.to_numeric(df["fees"], errors="coerce").fillna(0)

    return df.sort_values("date").reset_index(drop=True)


def _compute_all_fees(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run the fee engine over every row once and attach the results as new columns:
      computed_broker_fee, computed_ttf, computed_total_cost

    This separates the stateful fee-engine run from the ingestion loop so that:
      • the validator can display real euro amounts (not the CSV 0.0),
      • the ingestion loop reads from these columns (engine runs exactly once).
    """
    engine = CreditMutuelFeeEngine()
    broker_fees, ttfs, total_costs = [], [], []

    for _, row in df.iterrows():
        tx_type = str(row.get("type", "BUY")).upper()

        if tx_type == "DEPOSIT":
            broker_fees.append(0.0)
            ttfs.append(0.0)
            total_costs.append(round(float(row.get("exec_price", 0) or 0), 4))
            continue

        csv_fee = float(row.get("fees", 0) or 0)
        result = engine.compute_fees(
            tx_date=row["date"],
            ticker=str(row["ticker"]).strip(),
            quantity=float(row.get("quantity", 0) or 0),
            exec_price=float(row.get("exec_price", 0) or 0),
            asset_type=str(row.get("asset_type", "STOCK")).upper(),
            order_type=tx_type,
            override_fee=csv_fee if csv_fee > 0 else None,
        )
        broker_fees.append(result["broker_fee"])
        ttfs.append(result["ttf"])
        total_costs.append(result["total_cost"])

    out = df.copy()
    out["computed_broker_fee"]  = broker_fees
    out["computed_ttf"]         = ttfs
    out["computed_total_cost"]  = total_costs
    return out


def ingest_transactions(filepath: str, verbose: bool = True,
                        force: bool = False) -> list[Transaction]:
    """
    Parse CSV, validate fields, compute true fees, and upsert into the database.

    force=True  — skip validation gate (proceed even if required fields missing).
                  Use when data has already been reviewed locally.
    Returns list of Transaction objects ingested.
    """
    from ingestion.validator import validate_transactions, print_validation_report

    session = get_session()
    df = parse_csv(filepath)

    # ── Pre-compute fees (engine runs once; validator and loop both use results)
    df = _compute_all_fees(df)

    # ── Validation gate (validator now sees computed euro amounts, not CSV zeros)
    validation = validate_transactions(df)
    if verbose:
        print_validation_report(validation)

    if validation["has_missing"] and not force:
        raise ValueError(
            "Ingestion aborted: missing required fields in CSV. "
            "Fix the data or re-run with --force to override."
        )

    ingested = []
    updated  = 0
    skipped  = 0

    for _, row in df.iterrows():
        tx_type    = str(row.get("type", "BUY")).upper()
        ticker     = str(row["ticker"]).strip()
        quantity   = float(row["quantity"])
        exec_price = float(row["exec_price"])
        asset_type = str(row.get("asset_type", "STOCK")).upper()

        # Use pre-computed fees (4dp precision)
        fees_data = {
            "broker_fee": float(row["computed_broker_fee"]),
            "ttf":        float(row["computed_ttf"]),
            "total_cost": float(row["computed_total_cost"]),
        }

        tx = Transaction(
            date=row["date"],
            ticker=ticker,
            name=str(row.get("name", ticker)),
            quantity=quantity,
            exec_price=exec_price,
            broker_fee=fees_data["broker_fee"],
            ttf=fees_data["ttf"],
            total_cost=fees_data["total_cost"],
            type=tx_type,
            currency=str(row.get("currency", "EUR")),
            asset_type=asset_type,
            market=str(row.get("market", "EURONEXT")),
        )

        existing = session.query(Transaction).filter_by(
            date=tx.date, ticker=tx.ticker,
            quantity=tx.quantity, exec_price=tx.exec_price, type=tx.type
        ).first()

        if existing:
            # Update fee fields if precision changed or fee logic was corrected
            fee_changed = (
                abs(existing.broker_fee - tx.broker_fee) > 1e-6
                or abs(existing.ttf        - tx.ttf)        > 1e-6
                or abs(existing.total_cost - tx.total_cost) > 1e-4
            )
            if fee_changed:
                existing.broker_fee  = tx.broker_fee
                existing.ttf         = tx.ttf
                existing.total_cost  = tx.total_cost
                updated += 1
            else:
                skipped += 1
            continue

        session.add(tx)
        ingested.append(tx)

    session.commit()
    if verbose:
        parts = [f"[OK] Ingested {len(ingested)} new transactions"]
        if updated:
            parts.append(f"updated fees on {updated}")
        parts.append(f"{skipped} unchanged")
        print(", ".join(parts))
    return ingested


def get_transactions_df(session=None) -> pd.DataFrame:
    """Return all transactions as a tidy DataFrame."""
    if session is None:
        session = get_session()
    txs = session.query(Transaction).order_by(Transaction.date).all()
    if not txs:
        return pd.DataFrame()
    return pd.DataFrame([{
        "date": t.date, "ticker": t.ticker, "name": t.name,
        "quantity": t.quantity, "exec_price": t.exec_price,
        "broker_fee": t.broker_fee, "ttf": t.ttf, "total_cost": t.total_cost,
        "type": t.type, "currency": t.currency,
        "asset_type": t.asset_type, "market": t.market,
    } for t in txs])


def compute_positions(as_of: date = None, session=None) -> pd.DataFrame:
    """
    Compute current open positions using FIFO cost basis.
    Returns DataFrame with columns: ticker, quantity, avg_cost, cost_basis_total
    """
    if session is None:
        session = get_session()
    df = get_transactions_df(session)
    if df.empty:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"]).dt.date
    if as_of:
        df = df[df["date"] <= as_of]

    positions = defaultdict(lambda: {"quantity": 0.0, "fifo_lots": []})

    for _, row in df.iterrows():
        tk = row["ticker"]
        if row["type"] == "DEPOSIT":
            continue
        elif row["type"] == "BUY":
            positions[tk]["quantity"] += row["quantity"]
            positions[tk]["fifo_lots"].append({
                "qty": row["quantity"],
                "price": row["exec_price"],
                "fee": row["broker_fee"] + row["ttf"],
            })
        elif row["type"] == "SELL":
            sold_qty = abs(row["quantity"])
            positions[tk]["quantity"] -= sold_qty
            # FIFO: consume oldest lots first
            remaining = sold_qty
            new_lots = []
            for lot in positions[tk]["fifo_lots"]:
                if remaining <= 0:
                    new_lots.append(lot)
                elif lot["qty"] <= remaining:
                    remaining -= lot["qty"]
                else:
                    lot["qty"] -= remaining
                    remaining = 0
                    new_lots.append(lot)
            positions[tk]["fifo_lots"] = new_lots
        elif row["type"] == "DIVIDEND":
            pass  # dividends don't affect cost basis

    records = []
    for tk, pos in positions.items():
        qty = pos["quantity"]
        if abs(qty) < 0.001:
            continue
        lots = pos["fifo_lots"]
        total_cost = sum(l["qty"] * l["price"] + l["fee"] for l in lots)
        avg_cost = total_cost / qty if qty > 0 else 0
        records.append({
            "ticker": tk,
            "quantity": qty,
            "avg_cost": avg_cost,
            "cost_basis_total": total_cost,
        })

    return pd.DataFrame(records) if records else pd.DataFrame()
