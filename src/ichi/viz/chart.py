from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

import pandas as pd

from ichi.scoring.engine import Scorecard


def render_chart(
    df: pd.DataFrame,
    scorecard: Scorecard,
    symbol: str,
    timeframe: str,
    output_path: str | None = None,
) -> None:
    """Render Ichimoku chart with scorecard panel.

    If output_path is given, saves PNG. Otherwise opens in browser.
    """
    # Convert timezone-aware DatetimeIndex to plain strings for kaleido/orjson compatibility
    x = df.index.strftime("%Y-%m-%d %H:%M:%S").tolist()

    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.72, 0.28],
        specs=[[{"type": "candlestick"}, {"type": "table"}]],
        horizontal_spacing=0.02,
    )

    # ── Candlesticks ──────────────────────────────────────────────────────────
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1,
        col=1,
    )

    # ── Ichimoku lines ────────────────────────────────────────────────────────
    fig.add_trace(
        go.Scatter(x=x, y=df["tk"], name="Tenkan", line=dict(color="#2962ff", width=1)),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=x, y=df["kj"], name="Kijun", line=dict(color="#b71c1c", width=1)),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=df["chikou"], name="Chikou",
            line=dict(color="#4caf50", width=1, dash="dot"),
        ),
        row=1, col=1,
    )

    # ── Cloud (SpanA / SpanB filled area) ─────────────────────────────────────
    # Split cloud into bullish and bearish segments for correct coloring
    span_a = df["span_a"]
    span_b = df["span_b"]

    # Bullish cloud (SpanA > SpanB)
    fig.add_trace(
        go.Scatter(
            x=x, y=span_a.where(span_a >= span_b),
            name="SpanA", line=dict(color="rgba(38,166,154,0.6)", width=0),
            showlegend=False,
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=span_b.where(span_a >= span_b),
            name="SpanB (bull)", line=dict(color="rgba(38,166,154,0.6)", width=0),
            fill="tonexty", fillcolor="rgba(38,166,154,0.15)",
            showlegend=False,
        ),
        row=1, col=1,
    )

    # Bearish cloud (SpanB > SpanA)
    fig.add_trace(
        go.Scatter(
            x=x, y=span_b.where(span_b > span_a),
            name="SpanB", line=dict(color="rgba(239,83,80,0.6)", width=0),
            showlegend=False,
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=span_a.where(span_b > span_a),
            name="SpanA (bear)", line=dict(color="rgba(239,83,80,0.6)", width=0),
            fill="tonexty", fillcolor="rgba(239,83,80,0.15)",
            showlegend=False,
        ),
        row=1, col=1,
    )

    # ── Scorecard panel (right column table) ──────────────────────────────────
    rows_data = _build_panel_rows(scorecard)
    labels = [r[0] for r in rows_data]
    marks = [r[1] for r in rows_data]
    colors = [r[2] for r in rows_data]

    header_text = (
        f"Bull Score  {scorecard.bull_score}/{scorecard.total_scoring_rules}   "
        f"Chikou {scorecard.chikou_angle_val:+.1f}°"
    )

    fig.add_trace(
        go.Table(
            header=dict(
                values=[header_text, ""],
                fill_color="#1e1e2e",
                font=dict(color="white", size=12),
                align="left",
            ),
            cells=dict(
                values=[labels, marks],
                fill_color=[["#1e1e2e"] * len(labels), ["#1e1e2e"] * len(marks)],
                font=dict(color=[["#e0e0e0"] * len(labels), colors], size=11),
                align=["left", "center"],
            ),
        ),
        row=1,
        col=2,
    )

    # ── Layout ────────────────────────────────────────────────────────────────
    last_date = df.index[-1].strftime("%Y-%m-%d") if len(df) > 0 else ""
    fig.update_layout(
        title=f"{symbol} {timeframe}  ·  {last_date}",
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        font=dict(color="#d1d4dc"),
        xaxis_rangeslider_visible=False,
        xaxis=dict(gridcolor="#2a2e39"),
        yaxis=dict(gridcolor="#2a2e39"),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
        height=700,
        width=1400,
    )

    if output_path:
        fig.write_image(output_path)
        print(f"Chart saved to {output_path}")
    else:
        fig.show()


def _build_panel_rows(scorecard: Scorecard) -> list[tuple[str, str, str]]:
    """Build (label, mark, color) rows for the scorecard table."""
    rows: list[tuple[str, str, str]] = []
    for section, results in scorecard.sections.items():
        rows.append((f"── {section}", "", "#888"))
        for r in results:
            if r.qualifies_bull:
                mark, color = "✓", "#26a69a"
            elif r.qualifies_bear:
                mark, color = "✗", "#ef5350"
            else:
                mark, color = "─", "#888888"
            detail = f"  ({r.detail})" if r.detail else ""
            rows.append((f"  {r.label}{detail}", mark, color))
    return rows
