# analytics/risk.py
"""
Risk Analytics Module
- Volatility, Variance
- Sharpe Ratio
- Beta vs CAC 40
- Max Drawdown
- Correlation matrix
- Ledoit-Wolf covariance shrinkage
- VaR / CVaR
- Risk contribution per position
- Efficient frontier (Monte Carlo)
"""
import pandas as pd
import numpy as np
from datetime import date, timedelta
from sklearn.covariance import LedoitWolf
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    BENCHMARK_TICKER, RISK_FREE_RATE, TRADING_DAYS,
    EWMA_LAMBDA, VAR_CONFIDENCE
)
from ingestion.parser import compute_positions
from ingestion.market_data import fetch_prices


# ─── Core Returns Builder ─────────────────────────────────────────────────────

def get_returns(tickers: list[str], lookback_days: int = 756) -> pd.DataFrame:
    """
    Fetch daily log returns for given tickers + benchmark.
    Returns DataFrame: index=date, columns=tickers.
    """
    start = date.today() - timedelta(days=lookback_days)
    all_tickers = list(set(tickers + [BENCHMARK_TICKER]))
    prices = fetch_prices(all_tickers, start=start, store=True)
    if prices.empty:
        return pd.DataFrame()
    prices = prices.ffill().dropna(how="all")
    returns = np.log(prices / prices.shift(1)).dropna()
    return returns


# ─── Risk Metrics ─────────────────────────────────────────────────────────────

def compute_volatility(returns: pd.Series) -> float:
    """Annualized volatility from daily log returns."""
    return float(returns.std() * np.sqrt(TRADING_DAYS))


def compute_ewma_volatility(returns: pd.Series, lam: float = EWMA_LAMBDA) -> float:
    """EWMA (RiskMetrics) volatility — gives more weight to recent observations."""
    sq = returns ** 2
    ewma_var = sq.ewm(alpha=1 - lam, adjust=False).mean().iloc[-1]
    return float(np.sqrt(ewma_var * TRADING_DAYS))


def compute_sharpe(returns: pd.Series, rf: float = RISK_FREE_RATE) -> float:
    """Annualized Sharpe ratio."""
    ann_return = float(returns.mean() * TRADING_DAYS)
    ann_vol    = compute_volatility(returns)
    if ann_vol == 0:
        return 0.0
    return (ann_return - rf) / ann_vol


def compute_beta(asset_returns: pd.Series, bm_returns: pd.Series) -> float:
    """Beta of asset vs benchmark."""
    aligned = pd.concat([asset_returns, bm_returns], axis=1).dropna()
    if len(aligned) < 20:
        return np.nan
    cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
    return float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else np.nan


def compute_alpha(asset_returns: pd.Series, bm_returns: pd.Series,
                  rf: float = RISK_FREE_RATE) -> dict:
    """
    Jensen's alpha from CAPM regression.
    Returns alpha, beta, t_stat, r_squared.
    """
    from scipy import stats
    aligned = pd.concat([asset_returns, bm_returns], axis=1).dropna()
    if len(aligned) < 30:
        return {"alpha": np.nan, "beta": np.nan, "t_stat": np.nan, "r2": np.nan}
    x = aligned.iloc[:, 1].values
    y = aligned.iloc[:, 0].values
    rf_daily = rf / TRADING_DAYS
    excess_y = y - rf_daily
    excess_x = x - rf_daily
    slope, intercept, r, p, se = stats.linregress(excess_x, excess_y)
    t_stat = intercept / se if se > 0 else np.nan
    ann_alpha = intercept * TRADING_DAYS
    return {
        "alpha": float(ann_alpha),
        "beta": float(slope),
        "t_stat": float(t_stat),
        "r2": float(r ** 2),
        "p_value": float(p),
    }


def compute_max_drawdown(values: pd.Series) -> dict:
    """Maximum drawdown, duration, and recovery info."""
    roll_max = values.cummax()
    drawdown = (values - roll_max) / roll_max
    max_dd = float(drawdown.min())
    end_idx = drawdown.idxmin()
    # Find peak before trough
    peak_idx = values[:end_idx].idxmax()
    return {
        "max_drawdown_pct": round(max_dd * 100, 2),
        "peak_date": str(peak_idx),
        "trough_date": str(end_idx),
        "drawdown_days": int((pd.Timestamp(end_idx) - pd.Timestamp(peak_idx)).days),
    }


def compute_var_cvar(returns: pd.Series, confidence: float = VAR_CONFIDENCE) -> dict:
    """Historical VaR and CVaR."""
    clean = returns.dropna()
    if len(clean) < 20:
        return {"var_1d": np.nan, "cvar_1d": np.nan}
    var = float(np.percentile(clean, (1 - confidence) * 100))
    cvar = float(clean[clean <= var].mean())
    return {
        "var_1d_pct": round(var * 100, 3),
        "cvar_1d_pct": round(cvar * 100, 3),
        "var_10d_pct": round(var * np.sqrt(10) * 100, 3),
    }


# ─── Portfolio-Level Risk ──────────────────────────────────────────────────────

def compute_covariance_matrix(returns: pd.DataFrame,
                               shrink: bool = True) -> np.ndarray:
    """
    Annualized covariance matrix with optional Ledoit-Wolf shrinkage.
    """
    clean = returns.dropna()
    if shrink and len(clean) > clean.shape[1]:
        lw = LedoitWolf().fit(clean)
        cov = lw.covariance_ * TRADING_DAYS
    else:
        cov = clean.cov().values * TRADING_DAYS
    return cov


def compute_portfolio_risk(weights: np.ndarray, cov: np.ndarray) -> float:
    """Portfolio annualized volatility."""
    return float(np.sqrt(weights @ cov @ weights))


def compute_risk_contributions(weights: np.ndarray,
                                cov: np.ndarray,
                                tickers: list[str]) -> pd.DataFrame:
    """
    Marginal and percentage risk contribution per position.
    RC_i = w_i × (Σw)_i / σ_p
    """
    port_vol = compute_portfolio_risk(weights, cov)
    if port_vol == 0:
        return pd.DataFrame()
    marginal = cov @ weights
    rc = weights * marginal / port_vol
    pct_rc = rc / port_vol * 100
    return pd.DataFrame({
        "ticker": tickers,
        "weight_pct": (weights * 100).round(2),
        "marginal_risk": marginal.round(6),
        "risk_contribution": rc.round(6),
        "risk_contribution_pct": pct_rc.round(2),
    }).sort_values("risk_contribution_pct", ascending=False)


def compute_full_risk_report(session=None) -> dict:
    """
    Full risk report for the current portfolio.
    """
    positions = compute_positions(session=session)
    if positions.empty:
        return {"error": "No open positions"}

    tickers = positions["ticker"].tolist()
    returns = get_returns(tickers)
    if returns.empty:
        return {"error": "No price data"}

    bm_col = BENCHMARK_TICKER if BENCHMARK_TICKER in returns.columns else None
    bm_returns = returns[bm_col] if bm_col else None

    # Portfolio weights from current market values
    from ingestion.market_data import fetch_latest_prices
    prices = fetch_latest_prices(tickers)
    market_values = {}
    for _, pos in positions.iterrows():
        tk = pos["ticker"]
        px = prices.get(tk, pos["avg_cost"])
        market_values[tk] = px * pos["quantity"]
    total_mv = sum(market_values.values())
    if total_mv == 0:
        return {"error": "Zero portfolio value"}

    weights_dict = {tk: v / total_mv for tk, v in market_values.items()}
    # Filter to tickers with returns data
    valid_tickers = [t for t in tickers if t in returns.columns]
    if not valid_tickers:
        return {"error": "No returns data for holdings"}

    w = np.array([weights_dict.get(t, 0) for t in valid_tickers])
    w = w / w.sum()  # normalize

    ret_matrix = returns[valid_tickers].dropna()
    cov = compute_covariance_matrix(ret_matrix, shrink=True)

    # Portfolio returns (weighted)
    port_returns = (ret_matrix * w).sum(axis=1)

    # Metrics
    port_vol    = compute_portfolio_risk(w, cov)
    sharpe      = compute_sharpe(port_returns)
    dd_info     = compute_max_drawdown(pd.Series(
        (port_returns.cumsum() + 1).values,
        index=port_returns.index
    ))
    var_info    = compute_var_cvar(port_returns)
    rc_df       = compute_risk_contributions(w, cov, valid_tickers)

    # Per-asset metrics
    asset_metrics = []
    for tk in valid_tickers:
        r = returns[tk].dropna()
        beta_val = compute_beta(r, bm_returns) if bm_returns is not None else np.nan
        alpha_info = compute_alpha(r, bm_returns) if bm_returns is not None else {}
        asset_metrics.append({
            "ticker": tk,
            "weight_pct": round(weights_dict.get(tk, 0) * 100, 2),
            "annualized_vol_pct": round(compute_volatility(r) * 100, 2),
            "ewma_vol_pct": round(compute_ewma_volatility(r) * 100, 2),
            "sharpe": round(compute_sharpe(r), 3),
            "beta": round(float(beta_val), 3) if not np.isnan(beta_val) else None,
            "alpha_annual": round(alpha_info.get("alpha", 0) * 100, 3) if alpha_info else None,
            "alpha_t_stat": round(alpha_info.get("t_stat", np.nan), 2) if alpha_info else None,
        })

    # Correlation matrix
    corr_matrix = ret_matrix.corr().round(3)

    return {
        "portfolio_vol_pct": round(port_vol * 100, 2),
        "portfolio_sharpe": round(sharpe, 3),
        "max_drawdown": dd_info,
        "var": var_info,
        "risk_contributions": rc_df.to_dict("records"),
        "asset_metrics": asset_metrics,
        "correlation_matrix": corr_matrix,
        "weights": dict(zip(valid_tickers, (w * 100).round(2))),
    }


# ─── Efficient Frontier ───────────────────────────────────────────────────────

def compute_efficient_frontier(tickers: list[str],
                                n_portfolios: int = 3000) -> pd.DataFrame:
    """
    Monte Carlo efficient frontier simulation.
    Returns DataFrame: vol, return, sharpe, weights per portfolio.
    """
    returns = get_returns(tickers)
    if returns.empty:
        return pd.DataFrame()

    valid = [t for t in tickers if t in returns.columns]
    if len(valid) < 2:
        return pd.DataFrame()

    ret_matrix = returns[valid].dropna()
    mean_returns = ret_matrix.mean() * TRADING_DAYS
    cov = compute_covariance_matrix(ret_matrix, shrink=True)

    results = []
    for _ in range(n_portfolios):
        w = np.random.dirichlet(np.ones(len(valid)))
        port_vol  = np.sqrt(w @ cov @ w)
        port_ret  = float(mean_returns @ w)
        port_sharpe = (port_ret - RISK_FREE_RATE) / port_vol if port_vol > 0 else 0
        results.append({
            "vol": round(port_vol * 100, 3),
            "return": round(port_ret * 100, 3),
            "sharpe": round(port_sharpe, 3),
            **{f"w_{t}": round(ww * 100, 2) for t, ww in zip(valid, w)},
        })

    return pd.DataFrame(results)
