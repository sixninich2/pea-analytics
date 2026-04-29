# config.py
# PEA Analytics System - Configuration
# Broker: Crédit Mutuel (Conditions 01/2026)
# Account holder: M GENTY MATTHIEU

from datetime import date

# ─── PEA Account Meta ─────────────────────────────────────────────────────────
PEA_OWNER         = "M GENTY MATTHIEU"
PEA_BROKER        = "Crédit Mutuel"
PEA_OPEN_DATE     = date(2025, 2, 5)          # 05/02/2025 — start of 5-year lock-in
PEA_LOCK_END_DATE = date(2030, 2, 5)          # 05/02/2030 — tax-free withdrawal
PEA_MAX_DEPOSIT   = 150_000.0                  # Legal ceiling (€)
SOCIAL_CHARGES    = 0.172                      # Prélèvements sociaux after 5 years
INCOME_TAX_BEFORE = 0.30                       # PFU if withdrawn before 5 years

# ─── Crédit Mutuel Fee Structure (PDF: Conditions 01/2026) ────────────────────

# Transaction fees — online orders via banque à distance (Gestion libre)
# Source: p.3 — "Ordres Bourse Euronext – Commission proportionnelle"
BROKER_FEE_STANDARD = 0.0050    # 0.50% — first 10 qualifying orders (>2000€ in 12M)
BROKER_FEE_TIER2    = 0.0035    # 0.35% — from 11th order >2000€ on 12M rolling
BROKER_FEE_TIER3    = 0.0025    # 0.25% — from 21st order >2000€ on 12M rolling
BROKER_FEE_HORS_EURONEXT = 0.0050  # 0.50% — non-Euronext markets

# OPC (ETF/Funds) fees — Source: p.4 — "OPC autres: 0.50% à l'achat uniquement"
ETF_BUY_FEE   = 0.0050    # 0.50% on buy
ETF_SELL_FEE  = 0.0000    # FREE on sell (no exit fees on OPC)

# Intraday discount — Source: p.3
INTRADAY_DISCOUNT = 0.50    # 50% off on 2nd order, same stock, same qty, same day

# Custody / Convention fees — Source: p.2
# 0.125% per semester on portfolio value (end of June / end of Dec)
# Min €6, max €75 per semester
CUSTODY_RATE_SEMI  = 0.00125   # 0.125% per semester
CUSTODY_MIN_SEMI   = 6.00      # €6 minimum per semester
CUSTODY_MAX_SEMI   = 75.00     # €75 maximum per semester

# Taxe sur les Transactions Financières (TTF) — Source: p.5
# 0.40% on BUY of French large-caps (market cap >1B€)
# Applies to: large-cap French equities on Euronext Paris
TTF_RATE = 0.0040

# Tickers subject to TTF (French large-caps >1B€ market cap — PEA relevant)
TTF_ELIGIBLE_TICKERS = {
    "AIR.PA",   # Airbus
    "MC.PA",    # LVMH
    "OR.PA",    # L'Oréal
    "SAN.PA",   # Sanofi
    "BNP.PA",   # BNP Paribas
    "TTE.PA",   # TotalEnergies  ← IN YOUR PORTFOLIO
    "SAF.PA",   # Safran
    "ORA.PA",   # Orange
    "SU.PA",    # Schneider Electric
    "CAP.PA",   # Capgemini
    "RI.PA",    # Pernod Ricard
    "DSY.PA",   # Dassault Systèmes
    "KER.PA",   # Kering
    "HO.PA",    # Thales
    "EN.PA",    # Bouygues
    "CS.PA",    # AXA
    "SGO.PA",   # Saint-Gobain
    "VIE.PA",   # Veolia
    "RMS.PA",   # Hermès
    "STM.PA",   # STMicroelectronics
}

# Transfer out fees — Source: p.5
TRANSFER_OUT_LISTED   = 15.0    # €15 per line of listed securities
TRANSFER_OUT_UNLISTED = 50.0    # €50 per line of unlisted
TRANSFER_OUT_MAX      = 150.0   # €150 maximum per PEA

# ─── Market Data ─────────────────────────────────────────────────────────────
# Default benchmark — Euro Stoxx 50 is more representative for a mixed PEA
# (CAC 40 is narrow; S&P 500 makes sense if portfolio is mainly ESE.PA)
BENCHMARK_TICKER   = "^STOXX50E"  # Euro Stoxx 50 (yfinance)
BENCHMARK_LABEL    = "Euro Stoxx 50"
BENCHMARK_OPTIONS  = {
    "Euro Stoxx 50": "^STOXX50E",
    "CAC 40":        "^FCHI",
    "S&P 500":       "SPY",
}
RISK_FREE_RATE     = 0.03       # ECB deposit rate approximation — update manually
PRICE_HISTORY_YEARS = 3         # Years of price history to fetch

# ─── Portfolio Construction Constraints (PEA) ────────────────────────────────
MIN_WEIGHT     = 0.02   # Minimum 2% per position
MAX_WEIGHT     = 0.40   # Maximum 40% per position (ETF can be concentrated)
MIN_POSITION_EUR = 300  # Minimum notional size to recommend

# ─── Risk Parameters ─────────────────────────────────────────────────────────
EWMA_LAMBDA     = 0.94   # RiskMetrics exponential decay
TRADING_DAYS    = 252    # Annual trading days
VAR_CONFIDENCE  = 0.95   # 95% VaR / CVaR

# ─── Refinitiv API (optional — set in .env) ──────────────────────────────────
# If not configured, system falls back to yfinance for all market data
REFINITIV_APP_KEY = ""  # Set in .env: REFINITIV_APP_KEY=your_key

# ─── Dashboard ───────────────────────────────────────────────────────────────
DASH_PORT = 8050
DASH_DEBUG = True

# ─── Database ────────────────────────────────────────────────────────────────
DB_PATH = "data/pea_analytics.db"   # SQLite — simple local setup
