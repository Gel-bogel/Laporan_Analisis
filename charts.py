"""Grafik gaya laporan "YOY PENJUALAN" (Menu 2).

Bentuk mengikuti referensi user (warna TIDAK — warna mengikuti tema aplikasi):
- dua batang per kategori: pembanding dan realisasi;
- panah naik / turun di atas pasangan batang, dengan label persen;
- tabel data di bawah grafik: baris pembanding, realisasi, dan persen, sejajar dengan tiap kategori;
- legenda di bawah tabel.
Kategori terakhir (TOTAL/JUMLAH) boleh ditaruh di panel kanan dengan sumbu sendiri, supaya golongan
kecil tetap terbaca tanpa memotong batang (sumbu tidak dipotong seperti di Excel).
Latar grafik transparan sehingga menyatu dengan latar aplikasi; tinta teks, garis kisi, dan warna seri
dipilih dari config.YOY_THEME sesuai mode terang/gelap (set_mode dipanggil app.py).
"""
from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config
from modules.column_utils import fmt_id, fmt_pct, to_num


_MODE = {"value": "light"}


def set_mode(mode: str) -> None:
    """Pilih palet 'light' / 'dark' sesuai tema aplikasi Streamlit."""
    _MODE["value"] = mode if mode in config.YOY_THEME else "light"


def _t() -> dict:
    return config.YOY_THEME[_MODE["value"]]


def _finite(v) -> bool:
    v = to_num(v)
    return v is not None and np.isfinite(v)


def _cell(v, compact: bool) -> str:
    if not _finite(v):
        return "–"
    if compact and abs(to_num(v)) >= config.YOY_TABLE_COMPACT_UNIT:
        return fmt_id(to_num(v) / config.YOY_TABLE_COMPACT_UNIT, 2) + config.YOY_TABLE_COMPACT_SUFFIX
    return fmt_id(v, 0)


def _wrap(label: str) -> str:
    """Pecah label panjang menjadi beberapa baris (<br>) agar label sumbu x tidak dimiringkan."""
    if "<br>" in label or len(label) <= config.YOY_TICK_WRAP_CHARS:
        return label
    lines, cur = [], ""
    for w in label.split(" "):
        if cur and len(cur) + 1 + len(w) > config.YOY_TICK_WRAP_CHARS:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "<br>".join(lines)


def yoy_chart(categories: Sequence[str], prev: Sequence[float], cur: Sequence[float],
              pct: Sequence[float], prev_label: str, cur_label: str, title: str,
              pct_label: str = "% PENCAPAIAN", separate_last: bool = False,
              height: Optional[int] = None, arrow_rule: str = "pct") -> go.Figure:
    """Grafik batang ganda + panah + tabel data.

    arrow_rule: "pct" → panah naik bila persen ≥ 0; "target" → naik bila persen ≥ 100 (capaian target).
    """
    cats = [_wrap(str(c)) for c in categories]
    prev = [to_num(v) for v in prev]
    cur = [to_num(v) for v in cur]
    pct = [to_num(v) for v in pct]
    n = len(cats)
    compact = n > config.YOY_TABLE_MAX_FULL_COLS
    tfont = config.YOY_TABLE_FONT_COMPACT if compact else config.YOY_TABLE_FONT
    split = separate_last and n > 1
    rows_px = config.YOY_TABLE_ROW_PX
    extra_lines = max(c.count("<br>") for c in cats) if cats else 0
    header_px = config.YOY_TABLE_HEADER_PX + config.YOY_TICK_LINE_PX * extra_lines
    n_rows = 3
    bottom = header_px + rows_px * n_rows + config.YOY_LEGEND_PX
    height = height or config.YOY_CHART_HEIGHT
    plot_h = max(120, height - config.YOY_TOP_PX - bottom)

    if split:
        fig = make_subplots(rows=1, cols=2, column_widths=[n - 1, 1.3],
                            horizontal_spacing=config.YOY_PANEL_SPACING)
        groups = [(list(range(n - 1)), 1), ([n - 1], 2)]
    else:
        fig = go.Figure()
        groups = [(list(range(n)), 1)]

    anns, shapes = [], []
    th = _t()
    rad = {"cornerradius": config.YOY_BAR_RADIUS}

    def add(trace, col):
        if split:
            fig.add_trace(trace, row=1, col=col)
        else:
            fig.add_trace(trace)

    for idx, col in groups:
        x = [cats[i] for i in idx]
        first = col == 1
        add(go.Bar(x=x, y=[prev[i] if _finite(prev[i]) else None for i in idx], name=prev_label,
                   marker=dict(color=th["prev"], line=dict(color=th["gap"], width=1), **rad),
                   legendgroup="prev", showlegend=first, hovertemplate="%{x}<br>" + prev_label + ": %{y:,.0f}<extra></extra>"),
            col)
        add(go.Bar(x=x, y=[cur[i] if _finite(cur[i]) else None for i in idx], name=cur_label,
                   marker=dict(color=th["cur"], line=dict(color=th["gap"], width=1), **rad),
                   legendgroup="cur", showlegend=first, hovertemplate="%{x}<br>" + cur_label + ": %{y:,.0f}<extra></extra>"),
            col)
        # panah (anotasi, ukuran piksel) + label persen di atas pasangan batang
        xref = "x" if col == 1 else "x2"
        yref = "y" if col == 1 else "y2"
        for i in idx:
            top = max([v for v in (prev[i], cur[i]) if _finite(v)] or [0.0])
            top = max(top, 0.0)
            lab_shift = config.YOY_ARROW_GAP_PX + config.YOY_ARROW_LEN_PX + 4
            if _finite(pct[i]):
                up = pct[i] >= (100.0 if arrow_rule == "target" else 0.0)
                colr = th["up"] if up else th["down"]
                head = config.YOY_ARROW_GAP_PX + (config.YOY_ARROW_LEN_PX if up else 0)
                anns.append(dict(x=cats[i], xref=xref, y=top, yref=yref, yshift=head, text="",
                                   showarrow=True, ax=0, ay=config.YOY_ARROW_LEN_PX if up else -config.YOY_ARROW_LEN_PX,
                                   arrowhead=2, arrowsize=0.8, opacity=0.9, arrowwidth=config.YOY_ARROW_WIDTH, arrowcolor=colr))
            anns.append(dict(x=cats[i], xref=xref, y=top, yref=yref, yshift=lab_shift, yanchor="bottom",
                               text=fmt_pct(pct[i]), showarrow=False,
                               font=dict(size=12, color=th["ink"])))
        # tabel data di bawah sumbu x, sejajar kategori
        for i in idx:
            for r, (val, color) in enumerate([(_cell(prev[i], compact), None), (_cell(cur[i], compact), None),
                                              (fmt_pct(pct[i]), None)]):
                anns.append(dict(x=cats[i], xref=xref, y=0, yref="paper", yanchor="top",
                                   yshift=-(header_px + rows_px * r), text=val, showarrow=False,
                                   font=dict(size=tfont, color=th["ink2"])))
    # label baris tabel (kiri) dengan kotak warna seperti legenda Excel
    row_labels = [(f"<span style='color:{th['prev']}'>●</span> {prev_label}"),
                  (f"<span style='color:{th['cur']}'>●</span> {cur_label}"),
                  (f"<span style='color:{th['muted']}'>●</span> {pct_label}")]
    for r, lab in enumerate(row_labels):
        anns.append(dict(x=0, xref="paper", xanchor="right", xshift=-6, y=0, yref="paper", yanchor="top",
                           yshift=-(header_px + rows_px * r), text=lab, showarrow=False, align="left",
                           font=dict(size=config.YOY_TABLE_FONT, color=th["ink2"])))
    # garis tabel
    for r in range(n_rows + 1):
        shapes.append(dict(type="line", xref="paper", x0=0, x1=1, yref="paper",
                      ysizemode="pixel", yanchor=0, y0=-(header_px - 4 + rows_px * r),
                      y1=-(header_px - 4 + rows_px * r), line=dict(color=th["grid"], width=1)))
    for ax in ("yaxis", "yaxis2") if split else ("yaxis",):
        fig.update_layout(**{ax: dict(rangemode="tozero", tickformat=",.0f", gridcolor=th["grid"], gridwidth=1,
                                      zeroline=True, zerolinecolor=th["axis"], showline=False,
                                      tickfont=dict(size=11, color=th["muted"]))})
    # ruang ekstra di atas agar panah & label tidak terpotong
    for idx, col in groups:
        vals = [v for i in idx for v in (prev[i], cur[i]) if _finite(v)]
        vmax = max(vals) if vals else 1.0
        vmin = min(0.0, min(vals)) if vals else 0.0
        ax = "yaxis" if col == 1 else "yaxis2"
        fig.update_layout(**{ax: dict(range=[vmin * config.YOY_HEADROOM, vmax * config.YOY_HEADROOM],
                                      tickformat=",.0f")})
    fig.update_layout(annotations=anns, shapes=shapes)
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", xref="paper",
                   font=dict(size=15, color=th["ink"], family=config.YOY_FONT_FAMILY, weight=600)),
        font=dict(family=config.YOY_FONT_FAMILY, color=th["ink2"]),
        barmode="group", bargap=config.YOY_BARGAP, bargroupgap=0.08, height=height,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(font=dict(family=config.YOY_FONT_FAMILY)),
        margin=dict(l=config.YOY_LEFT_PX, r=20, t=config.YOY_TOP_PX, b=bottom),
        legend=dict(orientation="h", x=0.5, xanchor="center", yanchor="top", bgcolor="rgba(0,0,0,0)",
                    font=dict(color=th["ink2"], size=12),
                    y=-(header_px + rows_px * n_rows + 8) / plot_h),
        separators=",.",
    )
    fig.update_xaxes(type="category", tickangle=0, showline=True, linecolor=th["axis"], showgrid=False,
                     tickfont=dict(size=12, color=th["ink2"]))
    fig.update_xaxes(tickmode="array", tickvals=[cats[i] for i in groups[0][0]], row=1, col=1) if split else \
        fig.update_xaxes(tickmode="array", tickvals=cats)
    return fig


def yoy_charts_by_year(periods: Sequence[str], prev, cur, pct, prev_label: str, cur_label: str,
                       title: str, pct_label: str = "% PENCAPAIAN") -> List[go.Figure]:
    """Deret bulanan panjang dipecah per tahun kalender (≤12 bulan per grafik) agar tabel tetap terbaca.

    periods berformat 'YYYY-MM'; kategori grafik memakai singkatan bulan.
    """
    import pandas as pd
    df = pd.DataFrame({"p": [str(x) for x in periods], "prev": list(prev), "cur": list(cur), "pct": list(pct)})
    df["y"] = df["p"].str[:4]
    df["m"] = df["p"].str[5:7].astype(int)
    figs = []
    for y, g in df.groupby("y", sort=True):
        cats = [config.CANON_MONTH_ABBR[m].title() for m in g["m"]]
        figs.append(yoy_chart(cats, g["prev"], g["cur"], g["pct"], prev_label, cur_label,
                              f"{title} — {y}", pct_label=pct_label))
    return figs


def growth_rows(tbl, cols: List[str], period: str, prev_col: str, cur_col: str, pct_col: str):
    """Ambil (kategori, pembanding, realisasi, persen) dari growth_table untuk satu periode."""
    sub = tbl[tbl["Periode"] == period].set_index("Golongan").reindex(cols)
    return list(sub.index), sub[prev_col].tolist(), sub[cur_col].tolist(), sub[pct_col].tolist()
