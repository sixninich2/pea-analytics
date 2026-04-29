# dashboard/app.py
"""
PEA Analytics Dashboard — Dash multi-page application
Launch: python main.py  →  http://localhost:8050
"""
import dash
from dash import dcc, html, Input, Output, State, dash_table
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import date
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    DASH_PORT, DASH_DEBUG, PEA_OWNER, PEA_BROKER,
    PEA_OPEN_DATE, PEA_LOCK_END_DATE, PEA_MAX_DEPOSIT,
    BENCHMARK_TICKER, BENCHMARK_LABEL, BENCHMARK_OPTIONS,
)
def nav_link_style():
    return {
        "display": "block",
        "padding": "10px 15px",
        "color": "#cccccc",
        "textDecoration": "none",
        "fontSize": "14px"
    }
# ─── Theme ────────────────────────────────────────────────────────────────────
NAVY    = "#0D1B2A"
DARK    = "#1A2744"
CARD    = "#1E2F4D"
ACCENT  = "#3B82F6"
GREEN   = "#22C55E"
RED     = "#EF4444"
YELLOW  = "#F59E0B"
TEXT    = "#E2E8F0"
MUTED   = "#94A3B8"
WHITE   = "#FFFFFF"
BORDER  = "#2D4163"

def make_card(children, style=None):
    base = {
        "background": CARD, "borderRadius": "12px", "padding": "20px",
        "border": f"1px solid {BORDER}", "marginBottom": "16px",
    }
    if style:
        base.update(style)
    return html.Div(children, style=base)

def metric_card(title, value, subtitle=None, color=TEXT):
    return make_card([
        html.P(title, style={"color": MUTED, "fontSize": "12px",
                              "marginBottom": "4px", "textTransform": "uppercase",
                              "letterSpacing": "0.05em"}),
        html.H3(value, style={"color": color, "fontSize": "28px",
                               "fontWeight": "700", "margin": "0"}),
        html.P(subtitle or "", style={"color": MUTED, "fontSize": "12px",
                                       "marginTop": "4px"}),
    ], style={"flex": "1", "minWidth": "180px"})


app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    title="PEA Analytics",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

NAVBAR = html.Nav([
    html.Div([
        html.Span("📊", style={"fontSize": "20px"}),
        html.Span(" PEA Analytics", style={
            "color": WHITE, "fontWeight": "700", "fontSize": "18px",
            "marginLeft": "8px",
        }),
        html.Span(f" — {PEA_OWNER}", style={
            "color": MUTED, "fontSize": "13px", "marginLeft": "8px"
        }),
    ], style={"display": "flex", "alignItems": "center"}),
    html.Div([
        dcc.Link("Overview",        href="/",               style=nav_link_style()),
        dcc.Link("Performance",     href="/performance",    style=nav_link_style()),
        dcc.Link("Risk",            href="/risk",           style=nav_link_style()),
        dcc.Link("Costs",           href="/costs",          style=nav_link_style()),
        dcc.Link("Screening",       href="/screening",      style=nav_link_style()),
        dcc.Link("Recommendations", href="/recommendations", style=nav_link_style()),
        dcc.Link("Validate CSV",    href="/validate",       style={
            **nav_link_style(),
            "color": "#F59E0B",  # yellow — draws attention to data review
        }),
    ], style={"display": "flex", "gap": "4px"}),
], style={
    "display": "flex", "justifyContent": "space-between", "alignItems": "center",
    "background": DARK, "padding": "12px 24px",
    "borderBottom": f"1px solid {BORDER}", "position": "sticky",
    "top": "0", "zIndex": "100",
})

def nav_link_style():
    return {
        "color": MUTED, "textDecoration": "none", "padding": "8px 14px",
        "borderRadius": "8px", "fontSize": "14px", "fontWeight": "500",
    }

PEA_BANNER = html.Div([
    html.Span("🏦 ", style={"fontSize": "14px"}),
    html.Span(f"{PEA_BROKER} PEA | Opened: {PEA_OPEN_DATE} | "
              f"Tax-free from: {PEA_LOCK_END_DATE} | "
              f"Max deposit: {PEA_MAX_DEPOSIT:,.0f}€",
              style={"color": MUTED, "fontSize": "12px"}),
], style={
    "background": "#0F1E35", "padding": "8px 24px",
    "borderBottom": f"1px solid {BORDER}",
})

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    dcc.Store(id="store-refresh", data=0),
    dcc.Interval(id="interval-refresh", interval=60 * 1000, n_intervals=0),
    NAVBAR,
    PEA_BANNER,
    html.Div(id="page-content", style={
        "minHeight": "100vh", "background": NAVY,
        "padding": "24px", "fontFamily": "'Inter', 'Segoe UI', sans-serif",
    }),
], style={"background": NAVY, "minHeight": "100vh", "color": TEXT})


# ─── Router ───────────────────────────────────────────────────────────────────
@app.callback(Output("page-content", "children"),
              Input("url", "pathname"))
def render_page(pathname):
    if pathname == "/performance":
        return layout_performance()
    elif pathname == "/risk":
        return layout_risk()
    elif pathname == "/costs":
        return layout_costs()
    elif pathname == "/screening":
        return layout_screening()
    elif pathname == "/recommendations":
        return layout_recommendations()
    elif pathname == "/validate":
        return layout_validate()
    else:
        return layout_overview()


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
def layout_overview():
    try:
        from analytics.performance import compute_performance_summary, build_portfolio_value_series
        summary = compute_performance_summary()
        df = build_portfolio_value_series()
    except Exception as e:
        return html.Div(f"Error loading data: {e}",
                        style={"color": RED, "padding": "40px"})

    if not summary:
        return html.Div("No data yet. Run: python main.py --ingest",
                        style={"color": MUTED, "padding": "40px", "fontSize": "18px"})

    # ── KPI cards ─────────────────────────────────────────────────────────────
    return_color = GREEN if summary.get("total_return_pct", 0) >= 0 else RED
    alpha_color  = GREEN if summary.get("alpha", 0) >= 0 else RED

    days_lock = (PEA_LOCK_END_DATE - date.today()).days
    lock_pct  = max(0, min(100, (1 - days_lock / (365.25 * 5)) * 100))

    kpis = html.Div([
        metric_card("Portfolio Value",
                    f"€{summary.get('current_value', 0):,.2f}",
                    f"Invested: €{summary.get('invested_capital', 0):,.2f}"),
        metric_card("Total Return",
                    f"{summary.get('total_return_pct', 0):+.2f}%",
                    f"€{summary.get('total_return_eur', 0):+.2f}",
                    color=return_color),
        metric_card("TWR",
                    f"{summary.get('twr', 0):+.2f}%",
                    f"Benchmark: {summary.get('benchmark_return', 0):+.2f}%"),
        metric_card(f"Alpha vs {BENCHMARK_LABEL}",
                    f"{summary.get('alpha', 0):+.2f}%",
                    "Time-weighted excess return", color=alpha_color),
        metric_card("IRR (MWR)",
                    f"{summary.get('mwr_irr', 0):+.2f}%",
                    "Personalized money-weighted"),
        metric_card("Max Drawdown",
                    f"{summary.get('max_drawdown_pct', 0):.2f}%",
                    "Peak-to-trough", color=RED),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "12px",
              "marginBottom": "20px"})

    # ── Portfolio vs Benchmark chart ───────────────────────────────────────────
    chart = html.Div()
    if df is not None and not df.empty and "date" in df.columns:
        fig = go.Figure()
        if "portfolio_indexed" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["portfolio_indexed"],
                name="Mon PEA", line=dict(color=ACCENT, width=2.5),
                hovertemplate="<b>PEA</b>: %{y:.1f}<br>Date: %{x}<extra></extra>",
            ))
        if "benchmark_indexed" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["benchmark_indexed"],
                name="CAC 40", line=dict(color=YELLOW, width=1.5, dash="dot"),
                hovertemplate="<b>CAC 40</b>: %{y:.1f}<br>Date: %{x}<extra></extra>",
            ))
        _style_fig(fig, "Portfolio vs CAC 40 (indexed to 100)")
        chart = make_card(dcc.Graph(figure=fig, config={"displayModeBar": False}))

    # ── Allocation pie ─────────────────────────────────────────────────────────
    pie = html.Div()
    try:
        from ingestion.parser import compute_positions
        from ingestion.market_data import fetch_latest_prices
        positions = compute_positions()
        if not positions.empty:
            prices = fetch_latest_prices(positions["ticker"].tolist())
            mv = {r["ticker"]: prices.get(r["ticker"], r["avg_cost"]) * r["quantity"]
                  for _, r in positions.iterrows()}
            pie_fig = go.Figure(go.Pie(
                labels=list(mv.keys()), values=list(mv.values()),
                hole=0.4, textinfo="label+percent",
                marker=dict(colors=px.colors.qualitative.Set2),
            ))
            _style_fig(pie_fig, "Asset Allocation", height=350)
            pie = make_card(dcc.Graph(figure=pie_fig, config={"displayModeBar": False}))
    except Exception:
        pass

    # ── Cost summary strip ─────────────────────────────────────────────────────
    cost_strip = make_card([
        html.P("💸 Cost Summary", style={"color": MUTED, "fontSize": "12px",
               "textTransform": "uppercase", "marginBottom": "8px"}),
        html.Div([
            html.Span(f"Broker fees: €{summary.get('total_broker_fees', 0):.2f}",
                      style={"marginRight": "24px", "color": YELLOW}),
            html.Span(f"TTF: €{summary.get('total_ttf', 0):.2f}",
                      style={"marginRight": "24px", "color": YELLOW}),
            html.Span(f"Total explicit costs: €{summary.get('total_costs', 0):.2f}",
                      style={"color": RED}),
        ]),
    ])

    # ── PEA lock-in progress ───────────────────────────────────────────────────
    lock_bar = make_card([
        html.P("🔒 PEA 5-Year Tax-Free Lock-In Progress",
               style={"color": MUTED, "fontSize": "12px", "marginBottom": "8px"}),
        html.Div([
            html.Div(style={
                "height": "8px", "borderRadius": "4px", "background": BORDER,
                "overflow": "hidden",
            }, children=[
                html.Div(style={
                    "height": "100%", "width": f"{lock_pct:.1f}%",
                    "background": f"linear-gradient(90deg, {GREEN}, {ACCENT})",
                    "borderRadius": "4px",
                })
            ]),
            html.P(f"{lock_pct:.1f}% complete — {days_lock} days remaining until {PEA_LOCK_END_DATE}",
                   style={"color": MUTED, "fontSize": "12px", "marginTop": "6px"}),
        ]),
    ])

    return html.Div([
        html.H2("Portfolio Overview", style={"color": WHITE, "marginBottom": "20px",
                                              "fontWeight": "700"}),
        kpis, chart,
        html.Div([pie, html.Div([cost_strip, lock_bar], style={"flex": "1"})],
                 style={"display": "flex", "gap": "16px", "alignItems": "flex-start"}),
    ])


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
def layout_performance():
    try:
        from analytics.performance import compute_performance_summary
        summary = compute_performance_summary()
    except Exception as e:
        return html.Div(f"Error: {e}", style={"color": RED})

    if not summary:
        return html.Div("No performance data available.", style={"color": MUTED})

    kpis = html.Div([
        metric_card("TWR", f"{summary.get('twr', 0):+.2f}%",
                    "Time-Weighted Return"),
        metric_card("IRR (MWR)", f"{summary.get('mwr_irr', 0):+.2f}%",
                    "Money-Weighted Return"),
        metric_card(f"Alpha vs {BENCHMARK_LABEL}",
                    f"{summary.get('alpha', 0):+.2f}%",
                    f"vs {BENCHMARK_LABEL}",
                    GREEN if summary.get("alpha", 0) >= 0 else RED),
        metric_card("Dividends", f"€{summary.get('dividends_received', 0):.2f}",
                    "Tax-free inside PEA", GREEN),
        metric_card("Max Drawdown", f"{summary.get('max_drawdown_pct', 0):.2f}%",
                    "", RED),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "12px",
              "marginBottom": "20px"})

    bm_selector = make_card(
        html.Div([
            html.Label("Benchmark comparison:",
                       style={"color": MUTED, "fontSize": "12px",
                              "marginBottom": "6px", "display": "block"}),
            dcc.Dropdown(
                id="benchmark-selector",
                options=[{"label": k, "value": v}
                         for k, v in BENCHMARK_OPTIONS.items()],
                value=BENCHMARK_TICKER,
                clearable=False,
                style={"width": "220px", "color": "#000"},
            ),
        ]),
        style={"marginBottom": "0"},
    )

    return html.Div([
        html.H2("Performance Analysis", style={"color": WHITE, "marginBottom": "20px",
                                               "fontWeight": "700"}),
        kpis,
        bm_selector,
        # Charts populated by the benchmark-selector callback below
        html.Div(id="perf-charts-container"),
    ])


@app.callback(
    Output("perf-charts-container", "children"),
    Input("benchmark-selector", "value"),
)
def update_performance_charts(benchmark_ticker):
    """Re-render performance charts when benchmark selection changes."""
    bm_ticker = benchmark_ticker or BENCHMARK_TICKER
    bm_name = {v: k for k, v in BENCHMARK_OPTIONS.items()}.get(bm_ticker, bm_ticker)

    try:
        from analytics.performance import build_portfolio_value_series
        df = build_portfolio_value_series(benchmark_ticker=bm_ticker)
    except Exception as e:
        return html.Div(f"Chart error: {e}", style={"color": RED})

    if df is None or df.empty:
        return html.Div("No price data available for selected benchmark.",
                        style={"color": MUTED, "padding": "20px"})

    # Market value vs invested capital
    fig_val = go.Figure()
    fig_val.add_trace(go.Scatter(
        x=df["date"], y=df["portfolio_value"],
        name="Market Value", line=dict(color=GREEN, width=2),
    ))
    fig_val.add_trace(go.Scatter(
        x=df["date"], y=df["invested_capital"],
        name="Invested Capital", line=dict(color=MUTED, dash="dash"),
    ))
    _style_fig(fig_val, "Portfolio Market Value vs Invested Capital (€)")

    # TWR vs benchmark
    fig_twr = go.Figure()
    if "twr" in df.columns:
        fig_twr.add_trace(go.Scatter(
            x=df["date"], y=df["twr"],
            name="TWR (%)", fill="tozeroy",
            fillcolor="rgba(59,130,246,0.1)",
            line=dict(color=ACCENT, width=2),
        ))
    if "benchmark_return" in df.columns:
        fig_twr.add_trace(go.Scatter(
            x=df["date"], y=df["benchmark_return"],
            name=f"{bm_name} (%)", line=dict(color=YELLOW, dash="dot"),
        ))
    fig_twr.add_hline(y=0, line=dict(color=BORDER, dash="dash"), opacity=0.5)
    _style_fig(fig_twr, f"Cumulative Return: Portfolio vs {bm_name} (%)")

    # Drawdown
    fig_dd = go.Figure()
    if "drawdown" in df.columns:
        fig_dd.add_trace(go.Scatter(
            x=df["date"], y=df["drawdown"],
            name="Drawdown (%)", fill="tozeroy",
            fillcolor="rgba(239,68,68,0.2)",
            line=dict(color=RED, width=1.5),
        ))
    fig_dd.add_hline(y=0, line=dict(color=BORDER), opacity=0.3)
    _style_fig(fig_dd, "Portfolio Drawdown (%)", height=280)

    return [
        make_card(dcc.Graph(figure=fig_val, config={"displayModeBar": False})),
        make_card(dcc.Graph(figure=fig_twr, config={"displayModeBar": False})),
        make_card(dcc.Graph(figure=fig_dd, config={"displayModeBar": False})),
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: RISK
# ══════════════════════════════════════════════════════════════════════════════
def layout_risk():
    try:
        from analytics.risk import compute_full_risk_report, compute_efficient_frontier
        from ingestion.parser import compute_positions
        risk = compute_full_risk_report()
    except Exception as e:
        return html.Div(f"Error: {e}", style={"color": RED})

    if "error" in risk:
        return html.Div(risk["error"], style={"color": MUTED, "padding": "40px"})

    # KPIs
    kpis = html.Div([
        metric_card("Portfolio Volatility",
                    f"{risk.get('portfolio_vol_pct', 0):.2f}%",
                    "Annualized"),
        metric_card("Sharpe Ratio",
                    f"{risk.get('portfolio_sharpe', 0):.3f}",
                    ">1.0 is good",
                    GREEN if risk.get("portfolio_sharpe", 0) > 1 else YELLOW),
        metric_card("Max Drawdown",
                    f"{risk.get('max_drawdown', {}).get('max_drawdown_pct', 0):.2f}%",
                    "", RED),
        metric_card("VaR (95%, 1D)",
                    f"{risk.get('var', {}).get('var_1d_pct', 0):.3f}%",
                    "Historical"),
        metric_card("CVaR (95%, 1D)",
                    f"{risk.get('var', {}).get('cvar_1d_pct', 0):.3f}%",
                    "Expected shortfall", RED),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "12px",
              "marginBottom": "20px"})

    # Correlation heatmap
    corr_chart = html.Div()
    if "correlation_matrix" in risk and not risk["correlation_matrix"].empty:
        corr = risk["correlation_matrix"]
        fig_corr = go.Figure(go.Heatmap(
            z=corr.values, x=corr.columns, y=corr.index,
            colorscale="RdBu_r", zmid=0, zmin=-1, zmax=1,
            text=corr.round(2).values, texttemplate="%{text}",
            colorbar=dict(tickfont=dict(color=TEXT)),
        ))
        _style_fig(fig_corr, "Asset Correlation Matrix", height=400)
        corr_chart = make_card(dcc.Graph(figure=fig_corr, config={"displayModeBar": False}))

    # Risk contribution chart
    rc_chart = html.Div()
    if risk.get("risk_contributions"):
        rc_df = pd.DataFrame(risk["risk_contributions"])
        fig_rc = go.Figure(go.Bar(
            x=rc_df["ticker"], y=rc_df["risk_contribution_pct"],
            marker_color=[GREEN if v < 33 else (YELLOW if v < 50 else RED)
                          for v in rc_df["risk_contribution_pct"]],
            text=rc_df["risk_contribution_pct"].round(1).astype(str) + "%",
            textposition="outside",
        ))
        _style_fig(fig_rc, "Risk Contribution per Position (%)", height=320)
        rc_chart = make_card(dcc.Graph(figure=fig_rc, config={"displayModeBar": False}))

    # Per-asset table
    asset_table = html.Div()
    if risk.get("asset_metrics"):
        am_df = pd.DataFrame(risk["asset_metrics"])
        asset_table = make_card([
            html.H3("Per-Asset Risk Metrics", style={"color": WHITE, "marginBottom": "12px",
                                                      "fontSize": "16px"}),
            _make_table(am_df, id="asset-risk-table"),
        ])

    # Efficient frontier
    ef_chart = html.Div()
    try:
        from ingestion.parser import compute_positions
        positions = compute_positions()
        if not positions.empty:
            tickers = positions["ticker"].tolist()
            ef_df = compute_efficient_frontier(tickers, n_portfolios=2000)
            if not ef_df.empty:
                fig_ef = go.Figure()
                fig_ef.add_trace(go.Scatter(
                    x=ef_df["vol"], y=ef_df["return"],
                    mode="markers",
                    marker=dict(size=4, color=ef_df["sharpe"],
                                colorscale="Viridis", opacity=0.6,
                                colorbar=dict(title="Sharpe",
                                              tickfont=dict(color=TEXT))),
                    name="Simulated portfolios",
                    hovertemplate="Vol: %{x:.2f}%<br>Return: %{y:.2f}%<extra></extra>",
                ))
                # Add current portfolio point
                if risk.get("portfolio_vol_pct"):
                    from analytics.performance import compute_performance_summary
                    s = compute_performance_summary()
                    fig_ef.add_trace(go.Scatter(
                        x=[risk["portfolio_vol_pct"]],
                        y=[s.get("twr", 0)],
                        mode="markers+text",
                        marker=dict(size=14, color=RED, symbol="star"),
                        text=["Your PEA"], textposition="top center",
                        textfont=dict(color=RED),
                        name="Current portfolio",
                    ))
                _style_fig(fig_ef, "Efficient Frontier — Risk vs Return")
                ef_chart = make_card(dcc.Graph(figure=fig_ef, config={"displayModeBar": False}))
    except Exception:
        pass

    return html.Div([
        html.H2("Risk Analytics", style={"color": WHITE, "marginBottom": "20px",
                                          "fontWeight": "700"}),
        kpis,
        html.Div([corr_chart, rc_chart], style={"display": "flex", "gap": "16px"}),
        asset_table,
        ef_chart,
    ])


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: COSTS
# ══════════════════════════════════════════════════════════════════════════════
def layout_costs():
    try:
        from analytics.costs import (compute_per_transaction_costs,
                                      compute_cost_summary,
                                      position_break_even_table)
        from ingestion.parser import get_transactions_df
        txs = get_transactions_df()
        summary = compute_cost_summary(txs)
        per_tx = compute_per_transaction_costs(txs)
        be_table = position_break_even_table()

        # ── Format fee columns as explicit euro amounts (never collapses to 0.0)
        if not per_tx.empty:
            _EUR_COLS = {
                "notional":        "€{:.2f}",
                "broker_fee":      "€{:.4f}",
                "ttf":             "€{:.4f}",
                "spread_cost_est": "€{:.4f}",
                "slippage_est":    "€{:.4f}",
                "total_one_way":   "€{:.4f}",
                "round_trip_total":"€{:.4f}",
            }
            _PCT_COLS = {
                "break_even_pct": "{:.4f}%",
                "fee_drag_pct":   "{:.4f}%",
            }
            for col, fmt in {**_EUR_COLS, **_PCT_COLS}.items():
                if col in per_tx.columns:
                    per_tx[col] = per_tx[col].apply(
                        lambda x, f=fmt: f.format(float(x))
                        if isinstance(x, (int, float)) else x
                    )
    except Exception as e:
        return html.Div(f"Error: {e}", style={"color": RED})

    kpis = html.Div([
        metric_card("Broker Fees Paid",
                    f"€{summary.get('total_broker_fees', 0):.2f}",
                    f"{summary.get('avg_fee_rate', 0):.3f}% avg rate"),
        metric_card("TTF Paid",
                    f"€{summary.get('total_ttf', 0):.2f}",
                    "Taxe sur Transactions Financières"),
        metric_card("Spread Cost (est.)",
                    f"€{summary.get('total_spread_est', 0):.2f}",
                    "Bid-ask spread estimate"),
        metric_card("Total Explicit",
                    f"€{summary.get('total_explicit_costs', 0):.2f}",
                    "Broker + TTF"),
        metric_card("All-In Round-Trip",
                    f"€{summary.get('total_all_in_costs', 0):.2f}",
                    "Fees + spread + slippage"),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "12px",
              "marginBottom": "20px"})

    # Per-transaction cost table
    tx_table = html.Div()
    if not per_tx.empty:
        tx_table = make_card([
            html.H3("Transaction Cost Breakdown",
                    style={"color": WHITE, "fontSize": "16px", "marginBottom": "12px"}),
            _make_table(per_tx, id="cost-table"),
        ])

    # Break-even table
    be_section = html.Div()
    if not be_table.empty:
        rows = []
        for _, r in be_table.iterrows():
            status = "✅ Above break-even" if r["above_breakeven"] else "⚠️ Below break-even"
            rows.append({
                "Ticker": r["ticker"],
                "Qty": r["quantity"],
                "Avg Cost": f"€{r['avg_cost']:.4f}",
                "Current Price": f"€{r['current_price']:.4f}",
                "Break-even Price": f"€{r['breakeven_price']:.4f}",
                "Break-even %": f"{r['breakeven_vs_entry_pct']:.3f}%",
                "Current Gain %": f"{r['current_gain_pct']:+.2f}%",
                "P&L €": f"€{r['total_pnl_eur']:+.2f}",
                "Status": status,
            })
        be_section = make_card([
            html.H3("Break-Even Analysis by Position",
                    style={"color": WHITE, "fontSize": "16px", "marginBottom": "12px"}),
            html.P("Break-even price = avg cost + entry fees/qty + estimated exit fee/qty",
                   style={"color": MUTED, "fontSize": "12px", "marginBottom": "12px"}),
            _make_table(pd.DataFrame(rows), id="be-table"),
        ])

    # Cost waterfall
    wf_fig = go.Figure(go.Bar(
        x=["Broker Fees", "TTF", "Spread (est.)", "Slippage (est.)"],
        y=[summary.get("total_broker_fees", 0), summary.get("total_ttf", 0),
           summary.get("total_spread_est", 0), summary.get("total_slippage_est", 0)],
        marker_color=[ACCENT, YELLOW, RED, RED],
        text=[f"€{v:.2f}" for v in [
            summary.get("total_broker_fees", 0), summary.get("total_ttf", 0),
            summary.get("total_spread_est", 0), summary.get("total_slippage_est", 0)]],
        textposition="outside",
    ))
    _style_fig(wf_fig, "Cost Breakdown: All Trading Costs (€)", height=320)

    return html.Div([
        html.H2("Hidden Cost Analysis", style={"color": WHITE, "marginBottom": "20px",
                                                "fontWeight": "700"}),
        html.P([
            "Broker: Crédit Mutuel | Euronext online rate: 0.50% | TTF: 0.40% (French large-caps) | ",
            html.Strong("Custody: 0.125%/semester", style={"color": YELLOW}),
        ], style={"color": MUTED, "fontSize": "13px", "marginBottom": "16px"}),
        kpis,
        make_card(dcc.Graph(figure=wf_fig, config={"displayModeBar": False})),
        be_section,
        tx_table,
    ])


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: SCREENING
# ══════════════════════════════════════════════════════════════════════════════
def layout_screening():
    try:
        from ingestion.market_data import fetch_fundamentals_yfinance, SCREENING_UNIVERSE
        df = fetch_fundamentals_yfinance(SCREENING_UNIVERSE[:25], store=True)
    except Exception as e:
        return html.Div(f"Error: {e}", style={"color": RED})

    if df.empty:
        return html.Div("Could not fetch screening data.", style={"color": MUTED})

    display_cols = [
        "ticker", "name", "sector", "composite_score",
        "roce", "op_margin", "rev_growth", "price_to_cf",
        "net_debt_ebitda", "momentum_12m", "analyst_upside",
        "pe_ratio", "dividend_yield", "beta", "current_price",
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    df_display = df[display_cols].sort_values("composite_score", ascending=False)

    # Format
    for col in ["roce", "op_margin", "rev_growth"]:
        if col in df_display.columns:
            df_display[col] = df_display[col].apply(
                lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—")
    for col in ["composite_score", "price_to_cf", "net_debt_ebitda",
                "momentum_12m", "analyst_upside", "pe_ratio", "beta"]:
        if col in df_display.columns:
            df_display[col] = df_display[col].apply(
                lambda x: f"{x:.1f}" if pd.notna(x) else "—")

    # Score bar chart
    top20 = df.nlargest(20, "composite_score")
    fig_scores = go.Figure(go.Bar(
        x=top20["composite_score"], y=top20["ticker"],
        orientation="h",
        marker=dict(
            color=top20["composite_score"],
            colorscale=[[0, RED], [0.5, YELLOW], [1, GREEN]],
            showscale=False,
        ),
        text=top20["composite_score"].round(1).astype(str),
        textposition="outside",
    ))
    _style_fig(fig_scores, "Top 20 by Composite Score (0–100)", height=500)
    fig_scores.update_layout(yaxis=dict(autorange="reversed"))

    return html.Div([
        html.H2("Stock Screening — PEA Eligible Universe",
                style={"color": WHITE, "marginBottom": "8px", "fontWeight": "700"}),
        html.P("Source: yfinance | Weights: ROCE 25% · Margin 15% · Growth 20% · PCF 15% · Leverage 10% · Momentum 15%",
               style={"color": MUTED, "fontSize": "12px", "marginBottom": "20px"}),
        make_card(dcc.Graph(figure=fig_scores, config={"displayModeBar": False})),
        make_card([
            html.H3("Full Universe Ranking",
                    style={"color": WHITE, "fontSize": "16px", "marginBottom": "12px"}),
            _make_table(df_display, id="screening-table"),
        ]),
    ])


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════════
def layout_recommendations():
    try:
        from recommendations.engine import generate_recommendations
        recs = generate_recommendations()
    except Exception as e:
        return html.Div(f"Error: {e}", style={"color": RED})

    cards = []
    for rec in recs:
        signal    = rec.get("signal", "HOLD")
        sig_color = rec.get("signal_color", YELLOW)
        sig_icon  = rec.get("signal_icon", "→")
        is_new    = rec.get("is_candidate", False)
        pnl_color = GREEN if rec.get("pnl_pct", 0) >= 0 else RED

        reason_items = [
            html.Li(r, style={"color": MUTED, "fontSize": "13px",
                               "marginBottom": "4px"})
            for r in rec.get("reasons", [])
        ]

        header = html.Div([
            html.Span(f"{sig_icon} {signal}", style={
                "background": sig_color, "color": WHITE,
                "padding": "4px 12px", "borderRadius": "6px",
                "fontWeight": "700", "fontSize": "13px",
            }),
            html.Span(" 🆕 New Candidate" if is_new else "",
                      style={"color": ACCENT, "fontSize": "12px",
                             "marginLeft": "8px"}),
        ], style={"marginBottom": "12px"})

        body = html.Div([
            html.Div([
                html.Strong(rec.get("ticker", ""), style={"color": WHITE,
                            "fontSize": "18px", "marginRight": "8px"}),
                html.Span(rec.get("name", "")[:40],
                          style={"color": MUTED, "fontSize": "13px"}),
            ]),
            html.Div([
                html.Span(f"Score: {rec.get('composite_score', 0):.0f}/100",
                          style={"color": ACCENT, "marginRight": "16px"}),
                html.Span(f"Weight: {rec.get('weight_pct', 0):.1f}%",
                          style={"marginRight": "16px", "color": TEXT}),
                html.Span(f"P&L: {rec.get('pnl_pct', 0):+.2f}% (€{rec.get('pnl_eur', 0):+.2f})",
                          style={"color": pnl_color, "marginRight": "16px"}),
                html.Span(f"Risk contrib: {rec.get('risk_contribution', 0):.1f}%",
                          style={"color": MUTED}),
            ], style={"margin": "8px 0", "fontSize": "14px"}),
            html.Ul(reason_items, style={"marginTop": "8px", "paddingLeft": "20px"}),
        ])

        cards.append(make_card([header, body],
                                style={"borderLeft": f"4px solid {sig_color}"}))

    return html.Div([
        html.H2("Investment Recommendations",
                style={"color": WHITE, "marginBottom": "8px", "fontWeight": "700"}),
        html.P("Signals integrate: composite score · risk contribution · break-even cost · PEA lock-in · diversification",
               style={"color": MUTED, "fontSize": "12px", "marginBottom": "20px"}),
        *cards,
    ])


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: VALIDATE CSV
# ══════════════════════════════════════════════════════════════════════════════
def layout_validate():
    """
    Show the current transactions.csv with each field tagged as:
      confirmed  — white text (explicitly in CSV)
      inferred   — yellow text, prefixed [~]  (system default)
      missing    — red bold text, prefixed [!]  (required but absent)
    """
    import os
    txs_path = os.path.join("data", "transactions.csv")

    if not os.path.exists(txs_path):
        return html.Div(
            "transactions.csv not found at data/transactions.csv",
            style={"color": RED, "padding": "40px"},
        )

    try:
        from ingestion.parser import parse_csv
        from ingestion.validator import (
            validate_transactions, validation_to_dataframe,
            REQUIRED_FIELDS, OPTIONAL_FIELDS_DEFAULTS,
        )
        raw_df  = parse_csv(txs_path)
        result  = validate_transactions(raw_df)
        disp_df = validation_to_dataframe(result)
    except Exception as e:
        return html.Div(f"Validation error: {e}", style={"color": RED, "padding": "40px"})

    s = result["summary"]

    # ── Summary badges ─────────────────────────────────────────────────────
    badge_style = lambda bg: {
        "background": bg, "color": WHITE,
        "padding": "4px 12px", "borderRadius": "6px",
        "fontSize": "13px", "fontWeight": "700",
        "marginRight": "8px",
    }
    summary_row = html.Div([
        html.Span(f"Rows: {s['total_rows']}", style=badge_style(DARK)),
        html.Span(f"Confirmed: {s['confirmed']}", style=badge_style("#166534")),
        html.Span(f"Inferred [~]: {s['inferred']}", style=badge_style("#92400e")),
        html.Span(
            f"Missing [!]: {s['missing']}",
            style=badge_style("#991b1b" if s['missing'] > 0 else "#166534"),
        ),
    ], style={"marginBottom": "16px"})

    # ── Warnings list ──────────────────────────────────────────────────────
    warnings_section = html.Div()
    if result["warnings"]:
        warnings_section = make_card([
            html.P("Warnings", style={"color": YELLOW, "fontWeight": "700",
                                      "marginBottom": "8px"}),
            html.Ul([
                html.Li(w, style={"color": YELLOW, "fontSize": "13px",
                                  "marginBottom": "4px"})
                for w in result["warnings"]
            ], style={"paddingLeft": "20px", "margin": 0}),
        ])

    # ── Color-coded table ──────────────────────────────────────────────────
    all_cols = disp_df.columns.tolist()

    # Build per-column style conditions for [~] and [!] markers
    style_conditions = [
        {"if": {"row_index": "odd"}, "backgroundColor": "#152038"},
    ]
    for col in all_cols:
        style_conditions.append({
            "if": {"filter_query": f"{{{col}}} contains '[~]'"},
            "color": YELLOW,
        })
        style_conditions.append({
            "if": {"filter_query": f"{{{col}}} contains '[!]'"},
            "color": RED, "fontWeight": "700",
        })

    table = dash_table.DataTable(
        id="validate-table",
        columns=[{"name": c.replace("_", " ").title(), "id": c} for c in all_cols],
        data=disp_df.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={
            "backgroundColor": CARD, "color": TEXT,
            "border": f"1px solid {BORDER}",
            "padding": "8px 12px", "fontSize": "13px",
            "fontFamily": "Inter, Segoe UI, sans-serif",
            "whiteSpace": "normal",
        },
        style_header={
            "backgroundColor": DARK, "color": TEXT,
            "fontWeight": "700", "border": f"1px solid {BORDER}",
        },
        style_data_conditional=style_conditions,
        page_size=50,
    )

    # ── Legend ─────────────────────────────────────────────────────────────
    legend = make_card(html.Div([
        html.Span("Legend: ", style={"color": MUTED, "fontSize": "12px"}),
        html.Span("plain = confirmed from CSV  ",
                  style={"color": TEXT, "fontSize": "12px", "marginRight": "16px"}),
        html.Span("[~] inferred = system default — review before relying on it  ",
                  style={"color": YELLOW, "fontSize": "12px", "marginRight": "16px"}),
        html.Span("[!] MISSING = required field absent — fix CSV or use --force  ",
                  style={"color": RED, "fontSize": "12px", "fontWeight": "700"}),
    ]))

    ingestion_note = html.P(
        "This page is read-only. To ingest: python main.py --ingest  "
        "| To skip validation gate: python main.py --ingest --force",
        style={"color": MUTED, "fontSize": "12px", "marginTop": "8px"},
    )

    return html.Div([
        html.H2("CSV Validation — Pre-Ingestion Review",
                style={"color": WHITE, "marginBottom": "8px", "fontWeight": "700"}),
        html.P(
            "Each field is tagged: confirmed (from CSV) · inferred (system default) · missing (required but absent).",
            style={"color": MUTED, "fontSize": "13px", "marginBottom": "16px"},
        ),
        summary_row,
        legend,
        warnings_section,
        make_card([
            html.H3("Transaction Field Confidence",
                    style={"color": WHITE, "fontSize": "16px", "marginBottom": "12px"}),
            table,
        ]),
        ingestion_note,
    ])


# ─── Utilities ────────────────────────────────────────────────────────────────

def _style_fig(fig, title="", height=380):
    fig.update_layout(
        title=dict(text=title, font=dict(color=TEXT, size=15)),
        paper_bgcolor=CARD, plot_bgcolor=CARD,
        font=dict(color=TEXT, family="Inter, Segoe UI, sans-serif"),
        height=height,
        margin=dict(l=10, r=10, t=45, b=10),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=BORDER),
        xaxis=dict(gridcolor=BORDER, linecolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, linecolor=BORDER, zerolinecolor=BORDER),
        hovermode="x unified",
    )


def _make_table(df: pd.DataFrame, id: str):
    if df.empty:
        return html.P("No data", style={"color": MUTED})
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].apply(lambda x: str(x) if not isinstance(x, (int, float, str)) else x)
    return dash_table.DataTable(
        id=id,
        columns=[{"name": c.replace("_", " ").title(), "id": c} for c in df.columns],
        data=df.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={
            "backgroundColor": CARD, "color": TEXT, "border": f"1px solid {BORDER}",
            "padding": "8px 12px", "fontSize": "13px",
            "fontFamily": "Inter, Segoe UI, sans-serif",
        },
        style_header={
            "backgroundColor": DARK, "color": TEXT, "fontWeight": "700",
            "border": f"1px solid {BORDER}",
        },
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#152038"},
        ],
        page_size=20,
        sort_action="native",
        filter_action="native",
    )
