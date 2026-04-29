# ingestion/market_data.py
"""
Market data fetcher.
Primary source: yfinance (free, works immediately)
Optional upgrade: Refinitiv Data Library (enterprise)
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
import time
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    BENCHMARK_TICKER, PRICE_HISTORY_YEARS, REFINITIV_APP_KEY
)
from db.models import Price, Fundamental, get_session


# ─── Ticker Mapping: Crédit Mutuel SMS name toyfinance symbol ────────────────
TICKER_MAP = {
    "ESE.PA":  "ESE.PA",    # BNPP Easy S&P 500 UCITS ETF EUR (Euronext Paris)
    "TTE.PA":  "TTE.PA",    # TotalEnergies SE
    "AIR.PA":  "AIR.PA",    # Airbus
    "MC.PA":   "MC.PA",     # LVMH
    "OR.PA":   "OR.PA",     # L'Oréal
    "SAN.PA":  "SAN.PA",    # Sanofi
    "BNP.PA":  "BNP.PA",    # BNP Paribas
    "SAF.PA":  "SAF.PA",    # Safran
    "^FCHI":   "^FCHI",     # CAC 40
}

# PEA-eligible European screening universe (yfinance tickers)
SCREENING_UNIVERSE = [
    "AIR.PA", "MC.PA", "OR.PA", "TTE.PA", "SAN.PA", "BNP.PA", "SAF.PA",
    "SU.PA", "CAP.PA", "RI.PA", "DSY.PA", "KER.PA", "HO.PA", "CS.PA",
    "SGO.PA", "VIE.PA", "RMS.PA", "STM.PA", "ORA.PA", "EN.PA",
    "ACA.PA", "GLE.PA", "LR.PA", "SW.PA", "EDF.PA",
    "ALO.PA", "FP.PA",  "URW.PA", "SEV.PA", "VK.PA",
    # Belgian (Euronext Brussels — PEA eligible)
    "UCB.BR", "ABI.BR", "SOLB.BR",
    # Dutch (Euronext Amsterdam — PEA eligible)
    "ASML.AS", "INGA.AS", "PHIA.AS", "REN.AS",
]


# ─── Internal helpers: retry + DB fallback ───────────────────────────────────

def _yfinance_download_with_retry(tickers: list[str], start: date,
                                   end: date, max_retries: int = 3) -> pd.DataFrame:
    """Download from yfinance with exponential-backoff retry."""
    for attempt in range(max_retries):
        try:
            raw = yf.download(
                tickers, start=start, end=end,
                auto_adjust=True, progress=False, threads=True
            )
            if not raw.empty:
                return raw
        except Exception as e:
            wait = 2 ** attempt  # 1s, 2s, 4s
            if attempt < max_retries - 1:
                print(f"  [ERROR] yfinance attempt {attempt + 1} failed: {e}. "
                      f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [ERROR] yfinance failed after {max_retries} attempts: {e}")
    return pd.DataFrame()


def _fetch_prices_from_db(tickers: list[str], start: date,
                           end: date) -> pd.DataFrame:
    """Return cached prices from SQLite as a wide DataFrame (index=date, cols=ticker)."""
    session = get_session()
    from db.models import Price as PriceModel
    try:
        records = (
            session.query(PriceModel)
            .filter(PriceModel.ticker.in_(tickers))
            .filter(PriceModel.date >= start)
            .filter(PriceModel.date <= end)
            .all()
        )
        if not records:
            return pd.DataFrame()
        rows = [{"date": r.date, "ticker": r.ticker, "close": r.close}
                for r in records]
        df = pd.DataFrame(rows)
        return df.pivot(index="date", columns="ticker", values="close")
    except Exception as e:
        print(f"  [ERROR] DB price fallback error: {e}")
        return pd.DataFrame()


def fetch_prices(tickers: list[str], start: date = None,
                 end: date = None, store: bool = True) -> pd.DataFrame:
    """
    Download adjusted daily close prices for given tickers.
    Returns wide DataFrame: index=date, columns=ticker.
    """
    if start is None:
        start = date.today() - timedelta(days=365 * PRICE_HISTORY_YEARS)
    if end is None:
        end = date.today()

    print(f"  Fetching prices for {len(tickers)} tickers ({start} to{end})...")
    raw = _yfinance_download_with_retry(tickers, start, end)

    if raw.empty:
        # yfinance failed — fall back to cached DB prices
        print("  -> Falling back to cached prices from database.")
        cached = _fetch_prices_from_db(tickers, start, end)
        if not cached.empty:
            print(f"  [OK] Served {len(cached)} cached price rows from DB.")
        return cached

    # Handle single vs multi-ticker response
    if len(tickers) == 1:
        raw.columns = pd.MultiIndex.from_product([raw.columns, tickers])

    prices = pd.DataFrame()
    if "Close" in raw.columns.get_level_values(0):
        prices = raw["Close"].copy()
    elif "Adj Close" in raw.columns.get_level_values(0):
        prices = raw["Adj Close"].copy()

    prices.index = pd.to_datetime(prices.index).date
    prices = prices.dropna(how="all")

    if store:
        _store_prices(raw, tickers)

    return prices


def _store_prices(raw: pd.DataFrame, tickers: list[str]):
    """Persist prices to SQLite."""
    session = get_session()
    stored = 0
    for ticker in tickers:
        try:
            if len(tickers) == 1:
                df_t = raw.copy()
                df_t.columns = df_t.columns.droplevel(1) if isinstance(
                    df_t.columns, pd.MultiIndex) else df_t.columns
            else:
                if isinstance(raw.columns, pd.MultiIndex):
                    df_t = raw.xs(ticker, level=1, axis=1) if ticker in \
                           raw.columns.get_level_values(1) else pd.DataFrame()
                else:
                    df_t = raw[[ticker]].rename(columns={ticker: "Close"})
            if df_t.empty:
                continue

            for idx, row in df_t.iterrows():
                px_date = idx.date() if hasattr(idx, "date") else idx
                close_col = "Close" if "Close" in row.index else (
                    "Adj Close" if "Adj Close" in row.index else None)
                if close_col is None:
                    continue
                close_val = row.get(close_col)
                if pd.isna(close_val):
                    continue

                existing = session.query(Price).filter_by(
                    date=px_date, ticker=ticker).first()
                if existing:
                    continue

                p = Price(
                    date=px_date, ticker=ticker,
                    open=float(row.get("Open", np.nan) or np.nan),
                    high=float(row.get("High", np.nan) or np.nan),
                    low=float(row.get("Low", np.nan) or np.nan),
                    close=float(close_val),
                    adj_close=float(close_val),
                    volume=float(row.get("Volume", 0) or 0),
                )
                session.add(p)
                stored += 1
        except Exception as e:
            pass

    session.commit()
    if stored > 0:
        print(f"  [OK] Stored {stored} new price records")


def fetch_latest_prices(tickers: list[str]) -> dict[str, float]:
    """Return {ticker: latest_close} dict."""
    prices = fetch_prices(tickers, start=date.today() - timedelta(days=5),
                          store=False)
    result = {}
    for tk in tickers:
        if tk in prices.columns:
            val = prices[tk].dropna()
            if not val.empty:
                result[tk] = float(val.iloc[-1])
    return result


def fetch_fundamentals_yfinance(tickers: list[str],
                                store: bool = True) -> pd.DataFrame:
    """
    Fetch basic fundamental data via yfinance.
    Returns DataFrame with screening factors.
    """
    records = []
    today = date.today()
    prices_1y = fetch_prices(tickers,
                             start=today - timedelta(days=380),
                             store=False)

    for ticker in tickers:
        try:
            yfobj = yf.Ticker(ticker)
            info = yfobj.info or {}

            # 12-month momentum
            mom_12m = np.nan
            if ticker in prices_1y.columns:
                series = prices_1y[ticker].dropna()
                if len(series) > 20:
                    mom_12m = float(
                        (series.iloc[-1] / series.iloc[0] - 1) * 100
                    )

            # Analyst upside
            current = info.get("currentPrice") or info.get("regularMarketPrice")
            target = info.get("targetMeanPrice")
            analyst_upside = np.nan
            if current and target and current > 0:
                analyst_upside = float((target / current - 1) * 100)

            records.append({
                "ticker": ticker,
                "as_of_date": today,
                "name": info.get("longName", ticker),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "market_cap": info.get("marketCap", np.nan),
                "roce": info.get("returnOnEquity", np.nan),  # ROE as ROCE proxy
                "op_margin": info.get("operatingMargins", np.nan),
                "rev_growth": info.get("revenueGrowth", np.nan),
                "price_to_cf": info.get("priceToFreeCashflows", np.nan),
                "net_debt_ebitda": _compute_net_debt_ebitda(info),
                "momentum_12m": mom_12m,
                "analyst_upside": analyst_upside,
                "pe_ratio": info.get("trailingPE", np.nan),
                "dividend_yield": info.get("dividendYield", np.nan),
                "beta": info.get("beta", np.nan),
                "current_price": float(current) if current else np.nan,
            })
        except Exception as e:
            print(f"  [ERROR] Fundamentals error for {ticker}: {e}")

    df = pd.DataFrame(records)
    if df.empty:
        return df

    # Composite score
    df = _compute_composite_score(df)

    if store and not df.empty:
        _store_fundamentals(df)

    return df


def _compute_net_debt_ebitda(info: dict) -> float:
    """Estimate Net Debt/EBITDA from yfinance info dict."""
    try:
        total_debt = info.get("totalDebt", 0) or 0
        cash = info.get("totalCash", 0) or 0
        ebitda = info.get("ebitda") or info.get("operatingCashflow")
        if ebitda and ebitda > 0:
            net_debt = total_debt - cash
            return float(net_debt / ebitda)
    except Exception:
        pass
    return np.nan


def _compute_composite_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Composite score 0-100 using percentile ranks.
    Weights: ROCE 25%, Margin 15%, Growth 20%, PCF 15% (inv), Leverage 10% (inv),
             Momentum 15%.
    """
    factors = {
        "roce":          ("asc",  0.25),
        "op_margin":     ("asc",  0.15),
        "rev_growth":    ("asc",  0.20),
        "price_to_cf":   ("desc", 0.15),   # lower is better
        "net_debt_ebitda": ("desc", 0.10), # lower is better
        "momentum_12m":  ("asc",  0.15),
    }
    df = df.copy()
    score = pd.Series(0.0, index=df.index)

    for col, (direction, weight) in factors.items():
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        if series.notna().sum() < 3:
            continue
        pct = series.rank(pct=True, na_option="keep") * 100
        if direction == "desc":
            pct = 100 - pct
        score += pct.fillna(50) * weight

    df["composite_score"] = score.round(1)
    return df


def _store_fundamentals(df: pd.DataFrame):
    session = get_session()
    stored = 0
    for _, row in df.iterrows():
        existing = session.query(Fundamental).filter_by(
            ticker=row["ticker"], as_of_date=row["as_of_date"]).first()
        if existing:
            continue
        f = Fundamental(
            ticker=row["ticker"],
            as_of_date=row["as_of_date"],
            roce=row.get("roce"),
            op_margin=row.get("op_margin"),
            rev_growth=row.get("rev_growth"),
            price_to_cf=row.get("price_to_cf"),
            net_debt_ebitda=row.get("net_debt_ebitda"),
            momentum_12m=row.get("momentum_12m"),
            analyst_upside=row.get("analyst_upside"),
            sector=row.get("sector"),
            composite_score=row.get("composite_score"),
        )
        session.add(f)
        stored += 1
    session.commit()


# ─── Refinitiv Upgrade Layer (optional) ───────────────────────────────────────
def fetch_refinitiv_fundamentals(tickers: list[str]) -> pd.DataFrame:
    """
    Fetch richer fundamentals via Refinitiv Data Library.
    Only called if REFINITIV_APP_KEY is set in config.
    Falls back to yfinance silently.
    """
    if not REFINITIV_APP_KEY:
        return fetch_fundamentals_yfinance(tickers)
    try:
        import refinitiv.data as rd
        rd.open_session()
        fields = [
            "TR.ROCE", "TR.OperatingMargin", "TR.RevenueGrowth3Y",
            "TR.PriceToCashFlowPerShare", "TR.NetDebtToEBITDA",
            "TR.TotalReturn12M", "TR.AnalystPriceTarget",
            "TR.BuyPercent", "TR.TRBCIndustryGroup",
        ]
        data = rd.get_data(universe=tickers, fields=fields)
        # Map Refinitiv columns to our schema
        col_map = {
            "TR.ROCE": "roce",
            "TR.OperatingMargin": "op_margin",
            "TR.RevenueGrowth3Y": "rev_growth",
            "TR.PriceToCashFlowPerShare": "price_to_cf",
            "TR.NetDebtToEBITDA": "net_debt_ebitda",
            "TR.TotalReturn12M": "momentum_12m",
            "TR.TRBCIndustryGroup": "sector",
        }
        data = data.rename(columns=col_map)
        data["as_of_date"] = date.today()
        data = _compute_composite_score(data)
        rd.close_session()
        return data
    except Exception as e:
        print(f"  Refinitiv unavailable ({e}), falling back to yfinance")
        return fetch_fundamentals_yfinance(tickers)
