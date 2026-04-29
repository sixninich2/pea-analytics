# db/models.py
from sqlalchemy import (
    create_engine, Column, Integer, Float, String, Date, DateTime,
    Boolean, Text, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DB_PATH

Base = declarative_base()

# ─── Transactions ─────────────────────────────────────────────────────────────
class Transaction(Base):
    __tablename__ = "transactions"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    date          = Column(Date, nullable=False)
    ticker        = Column(String(20), nullable=False)
    name          = Column(String(100))
    quantity      = Column(Float, nullable=False)        # negative = sell
    exec_price    = Column(Float, nullable=False)
    broker_fee    = Column(Float, default=0.0)
    ttf           = Column(Float, default=0.0)           # Taxe sur Transactions Financières
    total_cost    = Column(Float)                        # notional + fees + ttf
    type          = Column(String(10), nullable=False)   # BUY / SELL / DIVIDEND / DEPOSIT
    currency      = Column(String(3), default="EUR")
    asset_type    = Column(String(10), default="STOCK")  # STOCK / ETF / CASH
    market        = Column(String(20), default="EURONEXT")
    created_at    = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("date", "ticker", "quantity", "exec_price", "type",
                         name="uq_transaction"),
    )

# ─── Daily Prices ─────────────────────────────────────────────────────────────
class Price(Base):
    __tablename__ = "prices"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    date       = Column(Date, nullable=False)
    ticker     = Column(String(20), nullable=False)
    open       = Column(Float)
    high       = Column(Float)
    low        = Column(Float)
    close      = Column(Float)
    adj_close  = Column(Float)
    volume     = Column(Float)
    source     = Column(String(20), default="yfinance")
    __table_args__ = (
        UniqueConstraint("date", "ticker", name="uq_price"),
        Index("ix_prices_ticker_date", "ticker", "date"),
    )

# ─── Portfolio Snapshots ──────────────────────────────────────────────────────
class Position(Base):
    __tablename__ = "positions"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date  = Column(Date, nullable=False)
    ticker         = Column(String(20), nullable=False)
    quantity       = Column(Float, default=0.0)
    avg_cost       = Column(Float, default=0.0)          # FIFO cost basis per share
    market_value   = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    weight         = Column(Float, default=0.0)          # % of portfolio
    __table_args__ = (
        UniqueConstraint("snapshot_date", "ticker", name="uq_position"),
    )

# ─── Dividends ────────────────────────────────────────────────────────────────
class Dividend(Base):
    __tablename__ = "dividends"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    ex_date          = Column(Date, nullable=False)
    ticker           = Column(String(20), nullable=False)
    amount_per_share = Column(Float, nullable=False)
    total_received   = Column(Float)
    currency         = Column(String(3), default="EUR")
    __table_args__ = (
        UniqueConstraint("ex_date", "ticker", name="uq_dividend"),
    )

# ─── Fundamentals ─────────────────────────────────────────────────────────────
class Fundamental(Base):
    __tablename__ = "fundamentals"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    ticker           = Column(String(20), nullable=False)
    as_of_date       = Column(Date, nullable=False)
    roce             = Column(Float)
    op_margin        = Column(Float)
    rev_growth       = Column(Float)
    price_to_cf      = Column(Float)
    net_debt_ebitda  = Column(Float)
    momentum_12m     = Column(Float)
    analyst_upside   = Column(Float)
    sector           = Column(String(50))
    composite_score  = Column(Float)
    source           = Column(String(20), default="yfinance")
    __table_args__ = (
        UniqueConstraint("ticker", "as_of_date", name="uq_fundamental"),
    )

# ─── Performance History ──────────────────────────────────────────────────────
class PerformanceRecord(Base):
    __tablename__ = "performance"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    date             = Column(Date, nullable=False, unique=True)
    portfolio_value  = Column(Float)
    cash_balance     = Column(Float)
    total_invested   = Column(Float)
    daily_return     = Column(Float)
    twr_cumulative   = Column(Float)
    benchmark_value  = Column(Float)
    benchmark_return = Column(Float)
    drawdown         = Column(Float)


def get_engine():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return create_engine(f"sqlite:///{DB_PATH}", echo=False)


def get_session():
    engine = get_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    print(f"[OK] Database initialized at {DB_PATH}")
