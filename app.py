"""
Aplikasi Analitik Penjualan kWh — PT PLN (Persero) UP3 Medan Utara
Jalankan:  streamlit run app.py

Menu:
 1. Upload & ETL            — unggah 4 sumber data (sekali), ETL AP2T → DB I & DB B
 2. Analitik Pertumbuhan    — MoM, MoM-Tahun, YoY kumulatif per golongan, TT, target, jenis tarif
 3. Klaster Industri & Bisnis (Cluster KBLI) + rekonsiliasi dengan file asli
 4. Forecasting (ML)
 5. Deteksi Anomali (ML)
"""
from __future__ import annotations

import inspect
import io
import math
import re
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from modules import anomaly as an
from modules import charts as ch
from modules import etl_merge as etl
from modules import forecast as fc
from modules import growth_calc as gc
from modules import master_rekap as mr
from modules import pdf_parser as rp
from modules import ui
from modules.column_utils import fmt_id, fmt_pct, period_label, period_name, to_num
from modules.data_loader import file_hash

st.set_page_config(page_title="Analitik kWh — PLN UP3 Medan Utara", page_icon="⚡", layout="wide")



def _wide(fn) -> dict:
    """Lebar penuh yang kompatibel dengan Streamlit lama (use_container_width) & baru (width='stretch')."""
    try:
        p = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    if "width" in p and isinstance(p["width"].default, str):
        return {"width": "stretch"}
    return {"use_container_width": True} if "use_container_width" in p else {}


WIDE_CHART = _wide(st.plotly_chart)
WIDE_DF = _wide(st.dataframe)

MENUS = ["1. Upload & ETL", "2. Analitik Pertumbuhan", "3. Klaster Industri & Bisnis",
         "4. Forecasting (ML)", "5. Deteksi Anomali (ML)"]

# =========================================================================== state
ss = st.session_state
ss.setdefault("files", {"report": [], "master": None, "db": None, "ap2t": None})
ss.setdefault("report_sheet", {})
ss.setdefault("etl", None)            # (kunci, EtlResult)
ss.setdefault("fc_result", None)
ss.setdefault("an_result", None)


def _store_single(kind: str, key: str):
    f = ss.get(key)
    if f is not None:
        data = f.getvalue()
        ss.files[kind] = {"name": f.name, "data": data, "hash": file_hash(data)}
        if kind in ("db", "ap2t"):
            ss.etl = None


def _store_reports(key: str):
    for f in ss.get(key) or []:
        data = f.getvalue()
        h = file_hash(data)
        if not any(r["hash"] == h for r in ss.files["report"]):
            ss.files["report"].append({"name": f.name, "data": data, "hash": h})


# =========================================================================== cache parser
@st.cache_data(show_spinner="Membaca laporan bulanan…")
def cached_report(data: bytes, name: str, sheet: Optional[str]):
    return rp.parse_report(data, name, sheet)


@st.cache_data(show_spinner="Membaca master rekap (sheet KWH-MDU)…")
def cached_master(data: bytes, name: str):
    return mr.parse_master(data, name)


@st.cache_data(show_spinner="Membaca database klaster…")
def cached_db(data: bytes, name: str):
    return etl.load_cluster_db(data, name)


@st.cache_data(show_spinner="Membaca transaksi AP2T…")
def cached_ap2t(data: bytes, name: str):
    return etl.parse_ap2t(data, name)


@st.cache_data(show_spinner="Menggabungkan AP2T ke database…")
def cached_etl(db_data: bytes, db_name: str, ap_data: bytes, ap_name: str):
    return etl.run_etl(cached_db(db_data, db_name), cached_ap2t(ap_data, ap_name))


@st.cache_data(show_spinner=False)
def cached_etl_excel(db_data: bytes, db_name: str, ap_data: bytes, ap_name: str):
    return etl.etl_to_excel(cached_etl(db_data, db_name, ap_data, ap_name))


def get_master():
    f = ss.files["master"]
    if not f:
        return None, None
    try:
        return cached_master(f["data"], f["name"]), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def get_reports() -> Tuple[List[Tuple[str, object]], List[str]]:
    out, errs = [], []
    for f in ss.files["report"]:
        try:
            out.append((f["name"], cached_report(f["data"], f["name"], ss.report_sheet.get(f["hash"]))))
        except rp.AmbiguousSheetError:
            errs.append(f"{f['name']}: pilih sheet di Menu 1.")
        except Exception as e:  # noqa: BLE001
            errs.append(f"{f['name']}: {e}")
    return out, errs


def get_db():
    f = ss.files["db"]
    if not f:
        return None, None
    try:
        return cached_db(f["data"], f["name"]), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def get_ap2t():
    f = ss.files["ap2t"]
    if not f:
        return None, None
    try:
        return cached_ap2t(f["data"], f["name"]), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def etl_key():
    d, a = ss.files["db"], ss.files["ap2t"]
    return (d["hash"] if d else None, a["hash"] if a else None)


def get_cluster_data() -> Tuple[Optional[etl.EtlResult], str]:
    """Hasil ETL bila sudah diklik; bila belum → pratinjau merge AP2T; tanpa AP2T → DB apa adanya."""
    d, a = ss.files["db"], ss.files["ap2t"]
    if not d:
        return None, "none"
    if ss.etl and ss.etl[0] == etl_key():
        return ss.etl[1], "etl"
    if a:
        try:
            return cached_etl(d["data"], d["name"], a["data"], a["name"]), "preview"
        except Exception as e:  # noqa: BLE001
            st.error(f"Gagal menggabungkan AP2T: {e}")
    cdb, err = get_db()
    if cdb is None:
        return None, "none"
    return etl.db_only_result(cdb), "db_only"


def get_combined() -> Optional[gc.CombinedData]:
    master, _ = get_master()
    reports, _ = get_reports()
    if master is None and not reports:
        return None
    return gc.combine_sources(master, reports)


# =========================================================================== tampilan umum
def show_table(df: pd.DataFrame, pct_cols=(), dec: Dict[str, int] = None, height=None, hide_index=True):
    """Tabel dengan format angka Indonesia; NaN tampil '–'."""
    dec = dec or {}
    fmts = {}
    for c in df.columns:
        if c in pct_cols or "(%)" in str(c) or "poin %" in str(c):
            fmts[c] = (lambda v: fmt_pct(v))
        elif pd.api.types.is_numeric_dtype(df[c]):
            d = dec.get(c, 0)
            fmts[c] = (lambda v, d=d: fmt_id(v, d))
    sty = df.style.format(fmts, na_rep="–")
    kw = {**WIDE_DF, "hide_index": hide_index}
    if height:
        kw["height"] = height
    st.dataframe(sty, **kw)


def excel_bytes(sheets: Dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        used = set()
        for name, df in sheets.items():
            nm = re.sub(r"[\[\]:*?/\\]", "-", str(name)).strip()[:31] or "Sheet"
            while nm in used:
                nm = (nm[:28] + f"_{len(used)}")[:31]
            used.add(nm)
            df.to_excel(xw, sheet_name=nm, index=False)
    return buf.getvalue()


def pct_text(values) -> List[str]:
    return [fmt_pct(v) for v in values]


def bar_pct(x, y, title, color=None, horizontal=False, height=None):
    y = [to_num(v) for v in y]
    yv = [0 if (v is None or not np.isfinite(v)) else v for v in y]
    colors = color or [config.COLOR_UP if v >= 0 else config.COLOR_DOWN for v in yv]
    if horizontal:
        tr = go.Bar(y=x, x=yv, orientation="h", text=pct_text(y), textposition="outside", marker_color=colors,
                    cliponaxis=False)
    else:
        tr = go.Bar(x=x, y=yv, text=pct_text(y), textposition="outside", marker_color=colors, cliponaxis=False)
    fig = go.Figure(tr)
    fig.update_layout(title=title, height=height or 380, margin=dict(l=10, r=40, t=50, b=10),
                      yaxis_title=None if horizontal else "%", xaxis_title="%" if horizontal else None)
    if horizontal:
        fig.update_yaxes(autorange="reversed")
    return fig


def _etl_done() -> bool:
    return bool(ss.etl and ss.etl[0] == etl_key())


def sidebar_status():
    f = ss.files
    names = [r["name"] for r in f["report"]]
    items = [
        {"label": "Laporan bulanan", "detail": f"{len(names)} file" if names else "Belum diunggah",
         "tip": "\n".join(names), "badge": "Tersimpan" if names else "Belum", "kind": "ok" if names else "off"},
    ]
    for kind, label in (("master", "Master rekap"), ("db", "Database klaster"), ("ap2t", "Transaksi AP2T")):
        it = f[kind]
        items.append({"label": label, "detail": ui.short_name(it["name"], 30) if it else "Belum diunggah",
                      "tip": it["name"] if it else "", "badge": "Tersimpan" if it else "Belum",
                      "kind": "ok" if it else "off"})
    done = _etl_done()
    items.append({"label": "Proses ETL",
                  "detail": f"Periode {period_name(*ss.etl[1].period)}" if done else "Belum dijalankan",
                  "badge": "Selesai" if done else "Belum", "kind": "ok" if done else "off"})
    ui.sidebar_status(items, footer="File tersimpan selama sesi browser ini aktif. Unggah ulang hanya bila ada "
                                    "versi baru.")


# =========================================================================== MENU 1
UPLOAD_CARDS = {
    # kunci: (ikon, warna ikon, judul, keterangan, format)
    "report": ("file", "blue", "Laporan Bulanan", "CR_LAP_309_PUSATNEW · boleh lebih dari satu bulan",
               ("pdf", "xlsx", "xls")),
    "master": ("sheet", "teal", "Master Rekap DATA USAHA", "AGA & PP UP3 MDU · sheet KWH-MDU", ("xlsx", "xls")),
    "db": ("database", "indigo", "Database Klaster", "I3I2B2 · sheet DB I & DB B", ("xlsx", "xls")),
    "ap2t": ("receipt", "amber", "Transaksi AP2T", "Medan Utara · Laporan detil tarif I3, I4 & B3", ("xls", "xlsx")),
}


def _uploader(label: str, types, key: str, **kw):
    return st.file_uploader(label, type=list(types), key=key, label_visibility="collapsed", **kw)


def _card_report():
    ic, tone, title, sub, fmts = UPLOAD_CARDS["report"]
    ui.card_header(ic, title, sub, fmts, tone)
    _uploader("Unggah laporan bulanan", fmts, "up_report", accept_multiple_files=True,
              on_change=_store_reports, args=("up_report",))
    if not ss.files["report"]:
        ui.empty_hint("Belum ada laporan tersimpan.")
    for f in list(ss.files["report"]):
        meta, status, kind = "", "Tersimpan", "ok"
        try:
            res = cached_report(f["data"], f["name"], ss.report_sheet.get(f["hash"]))
            meta = f"Periode {period_name(*res.period)}" + (f" · sheet {res.sheet}" if res.sheet else "")
            if res.warnings:
                status, kind = f"{len(res.warnings)} catatan", "warn"
        except rp.AmbiguousSheetError as e:
            meta, status, kind = "Pilih sheet laporan", "Perlu dipilih", "warn"
            sel = st.selectbox("Sheet laporan", e.candidates, key=f"sheet_{f['hash']}")
            if st.button("Pakai sheet ini", key=f"usesheet_{f['hash']}"):
                ss.report_sheet[f["hash"]] = sel
                st.rerun()
        except Exception as e:  # noqa: BLE001
            meta, status, kind = f"Gagal dibaca: {e}", "Gagal", "bad"
        c1, c2 = st.columns([6, 1], vertical_alignment="center")
        ui.file_row(f["name"], meta, status, kind, where=c1, icon_name="file")
        if c2.button("", key=f"del_rep_{f['hash']}", icon=":material/delete:", help="Hapus laporan ini",
                     type="tertiary"):
            ss.files["report"] = [r for r in ss.files["report"] if r["hash"] != f["hash"]]
            st.rerun()


def _card_single(kind: str, key: str, getter, meta_fn):
    ic, tone, title, sub, fmts = UPLOAD_CARDS[kind]
    ui.card_header(ic, title, sub, fmts, tone)
    _uploader(f"Unggah {title.lower()}", fmts, key, on_change=_store_single, args=(kind, key))
    obj = None
    if not ss.files[kind]:
        ui.empty_hint("Belum ada file tersimpan.")
        return None
    obj, err = getter()
    if err:
        ui.file_row(ss.files[kind]["name"], str(err), "Gagal", "bad", icon_name=ic)
        return None
    warns = getattr(obj, "warnings", []) or []
    ui.file_row(ss.files[kind]["name"], meta_fn(obj),
                f"{len(warns)} catatan" if warns else "Tersimpan", "warn" if warns else "ok", icon_name=ic)
    return obj


def _meta_master(m) -> str:
    per = m.periods
    return (f"Gabungan {m.years[0]}–{m.years[-1]} · {len(per)} bulan s.d. {per[-1]}" if per and m.years
            else "Tidak ada periode berisi data")


def _meta_db(cdb) -> str:
    return " · ".join(f"{k}: {fmt_id(len(s.df))} baris" for k, s in cdb.sheets.items())


def _meta_ap2t(ap) -> str:
    return f"Periode {period_name(*ap.period)} · {fmt_id(len(ap.df))} pelanggan"


def _card_etl(cdb, ap):
    ui.card_header("sync", "Proses ETL", "Isi kolom KWH bulan AP2T ke DB I & DB B (rute tarif I* → DB I, B* → DB B), "
                   "lalu hitung ulang sd Januari s.d. bulan berjalan.", (), "cyan")
    ready = bool(cdb and ap)
    ui.checklist([("Database klaster", bool(cdb)), ("Transaksi AP2T", bool(ap)), ("ETL dijalankan", _etl_done())])
    kw = _wide(st.button)
    if st.button("Jalankan ETL (DB I & DB B sekaligus)", type="primary", icon=":material/play_arrow:",
                 disabled=not ready, key="run_etl", **kw):
        d, a = ss.files["db"], ss.files["ap2t"]
        ss.etl = (etl_key(), cached_etl(d["data"], d["name"], a["data"], a["name"]))
    if not ready:
        ui.empty_hint("Unggah Database Klaster dan Transaksi AP2T untuk mengaktifkan tombol ETL.")
        return
    if _etl_done():
        res: etl.EtlResult = ss.etl[1]
        stats = []
        for k, s in res.sheets.items():
            stats += [(fmt_id(s.filled_rows), f"{k} · baris terisi"), (fmt_id(len(s.new_customers)),
                                                                      f"{k} · pelanggan baru (belum di DB)")]
        ui.stat_grid(stats)
        d, a = ss.files["db"], ss.files["ap2t"]
        st.download_button("Unduh Excel hasil ETL", data=cached_etl_excel(d["data"], d["name"], a["data"], a["name"]),
                           file_name=etl.etl_filename(res), icon=":material/download:",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           **_wide(st.download_button))


def _detail_report():
    if not ss.files["report"]:
        st.info("Belum ada laporan bulanan.")
        return
    for f in list(ss.files["report"]):
        try:
            res = cached_report(f["data"], f["name"], ss.report_sheet.get(f["hash"]))
        except rp.AmbiguousSheetError:
            st.warning(f"{f['name']}: pilih sheet laporan di kartu Laporan Bulanan.")
            continue
        except Exception as e:  # noqa: BLE001
            st.error(f"{f['name']}: gagal membaca — {e}")
            continue
        with st.expander(f"📄 {f['name']}", expanded=len(ss.files["report"]) == 1):
            st.success(f"Periode: **{period_name(*res.period)}**" + (f" — sheet '{res.sheet}'" if res.sheet else ""))
            for w in res.warnings:
                st.warning(w)
            if not res.warnings:
                st.caption("Validasi S+R+B+I+P+L = JUMLAH: ✅ sesuai.")
            g = res.golongan.reset_index().rename(columns={"index": "Golongan", "pelanggan": "Pelanggan",
                                                           "daya": "Daya (VA)", "kwh": "kWh"})
            t1, t2 = st.tabs(["Per golongan", "Per jenis tarif"])
            with t1:
                show_table(g, dec={"kWh": 3})
            with t2:
                t = res.tarif[["tarif", "golongan", "pelanggan", "daya", "kwh"]].rename(columns={
                    "tarif": "Jenis tarif", "golongan": "Golongan", "pelanggan": "Pelanggan",
                    "daya": "Daya (VA)", "kwh": "kWh"})
                show_table(t, dec={"kWh": 3})


def _detail_master(m):
    if not ss.files["master"]:
        st.info("Belum ada master rekap.")
        return
    if m is None:
        st.error(get_master()[1])
        return
    per = m.periods
    st.success(f"Tabel Gabungan dibaca: {', '.join(map(str, m.years))} "
               f"(mulai {config.MASTER_START_YEAR}; tabel sebelumnya diabaikan). "
               f"Periode berisi data: {per[0]} s.d. {per[-1]} ({len(per)} bulan), "
               f"{len(m.tarif_order)} jenis tarif.")
    if m.errors_cells:
        st.info(f"{m.errors_cells} sel berisi data selain angka (teks, '-', #VALUE! dsb.) dibaca sebagai 0.")
    for w in m.warnings:
        st.warning(w)


def _detail_db(cdb):
    if not ss.files["db"]:
        st.info("Belum ada database klaster.")
        return
    if cdb is None:
        st.error(get_db()[1])
        return
    rows = []
    for k, s in cdb.sheets.items():
        per = sorted(s.kwh_cols)
        rows.append({"Sheet": f"{k} ({s.sheet})", "Pelanggan (baris)": len(s.df),
                     "Kolom cluster": s.cluster_col or "–",
                     "Kolom KWH": f"{len(per)} ({period_label(*per[0])} s.d. {period_label(*per[-1])})" if per else "0",
                     "Pivot sd ditemukan": ", ".join(period_name(*p) for p in sorted(s.pivot)) or "–"})
    show_table(pd.DataFrame(rows))
    st.caption("Kolom sd<BULAN><TAHUN> di file tidak dipakai untuk hitungan; aplikasi menghitung sendiri "
               "kumulatif dari kolom KWH (kolom sd file hanya dipakai untuk penjelasan selisih di Menu 3).")
    for w in cdb.warnings:
        st.warning(w)


def _detail_ap2t(ap):
    if not ss.files["ap2t"]:
        st.info("Belum ada transaksi AP2T.")
        return
    if ap is None:
        st.error(get_ap2t()[1])
        return
    c = st.columns(4)
    c[0].metric("Periode", period_name(*ap.period))
    c[1].metric("Pelanggan (baris)", fmt_id(len(ap.df)))
    c[2].metric("Total kWh terbaca", fmt_id(ap.df["KWH"].sum()))
    c[3].metric("Baris TOTAL di file", fmt_id(ap.total_row_kwh))
    by = ap.df.groupby("TARIF").agg(Pelanggan=("IDPEL", "count"), kWh=("KWH", "sum")).reset_index()
    show_table(by)
    for w in ap.warnings:
        st.warning(w)


def _detail_etl():
    if not _etl_done():
        st.info("ETL belum dijalankan. Klik **Jalankan ETL** pada kartu Proses ETL.")
        return
    res: etl.EtlResult = ss.etl[1]
    st.success(f"ETL selesai untuk periode {period_name(*res.period)}.")
    for w in res.warnings:
        st.warning(w)
    for k, s in res.sheets.items():
        st.markdown(f"**{k}** — kolom `{s.target_col}` {'dibuat baru' if s.created_col else 'dipakai ulang'}")
        c = st.columns(5)
        c[0].metric("Baris terisi", fmt_id(s.filled_rows))
        c[1].metric("IDPEL cocok", fmt_id(s.matched_idpel))
        c[2].metric("Pelanggan baru", fmt_id(len(s.new_customers)), help="Ada di AP2T, belum ada di database")
        c[3].metric("IDPEL ganda di DB", fmt_id(len(s.db_duplicates)))
        c[4].metric("Tidak ada di AP2T", fmt_id(len(s.not_in_ap2t)), help="Ada di database, tidak ada di AP2T")
        with st.expander(f"Detail {k}"):
            st.markdown("Pelanggan baru (ada di AP2T, belum ada di database):")
            show_table(s.new_customers)
            st.markdown("IDPEL ganda di database:")
            show_table(s.db_duplicates)
            st.markdown("Pelanggan database yang tidak ada di AP2T bulan ini:")
            show_table(s.not_in_ap2t)


def page_upload():
    ui.page_header(MENUS[0], MENUS)
    ui.section("Sumber data", "Cukup unggah sekali; semua menu memakai file yang tersimpan. "
                              "Unggah file baru untuk mengganti versi lama.", "folder")
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1, st.container(key="card_report"):
        _card_report()
    with c2, st.container(key="card_master"):
        m = _card_single("master", "up_master", get_master, _meta_master)
    with c3, st.container(key="card_db"):
        cdb = _card_single("db", "up_db", get_db, _meta_db)

    ui.section("Transaksi bulanan & ETL", "Unggah transaksi AP2T bulan terbaru, lalu jalankan ETL ke database "
                                          "klaster.", "sync")
    d1, d2 = st.columns([1, 2], gap="medium")
    with d1, st.container(key="card_ap2t"):
        ap = _card_single("ap2t", "up_ap2t", get_ap2t, _meta_ap2t)
    with d2, st.container(key="card_etl"):
        _card_etl(cdb, ap)

    ui.section("Detail pembacaan file", "Tabel hasil baca, validasi, dan catatan untuk tiap sumber data.", "search")
    tabs = st.tabs(["Laporan bulanan", "Master rekap", "Database klaster", "Transaksi AP2T", "Hasil ETL"])
    with tabs[0]:
        _detail_report()
    with tabs[1]:
        _detail_master(m)
    with tabs[2]:
        _detail_db(cdb)
    with tabs[3]:
        _detail_ap2t(ap)
    with tabs[4]:
        _detail_etl()

# =========================================================================== MENU 2
def _theme_mode() -> str:
    """'dark' bila aplikasi memakai tema gelap (Streamlit ≥ 1.46: st.context.theme), selain itu 'light'."""
    try:
        return "dark" if str(st.context.theme.type).lower() == "dark" else "light"
    except Exception:  # noqa: BLE001  (Streamlit lama tidak punya st.context.theme)
        return "light"


def _pname(p: pd.Period) -> str:
    return period_name(p.year, p.month)


def _yoy_fig(tbl, cols, period, prev_col, cur_col, pct_col, prev_label, cur_label, title, pct_label,
             separate_last=False):
    c, pv, cu_, pc = ch.growth_rows(tbl, cols, str(period), prev_col, cur_col, pct_col)
    return ch.yoy_chart(c, pv, cu_, pc, prev_label, cur_label, title, pct_label=pct_label,
                        separate_last=separate_last)


TREND_METRICS = {
    "MoM (vs bulan sebelumnya)": ("kWh bulan lalu", "kWh", "MoM (%)", "Bulan sebelumnya", "Bulan berjalan", "% MoM"),
    "MoM-Tahun (vs bulan sama tahun lalu)": ("kWh bulan sama th lalu", "kWh", "MoM-Tahun (%)", "Bulan sama th lalu",
                                             "Bulan berjalan", "% MoM-TAHUN"),
    "YoY Kumulatif": ("Kumulatif th lalu", "Kumulatif", "YoY Kumulatif (%)", "Kumulatif th lalu",
                      "Kumulatif th ini", "% PENCAPAIAN"),
}


def _trend_figs(tbl, g, metric, title):
    prev_col, cur_col, pct_col, pl, cl, pctl = TREND_METRICS[metric]
    sub = tbl[tbl["Golongan"] == g]
    return ch.yoy_charts_by_year(sub["Periode"], sub[prev_col], sub[cur_col], sub[pct_col], pl, cl, title,
                                 pct_label=pctl)


def page_growth():
    ui.page_header(MENUS[1], MENUS)
    ch.set_mode(_theme_mode())
    comb = get_combined()
    _, rep_errs = get_reports()
    for e in rep_errs:
        st.warning(e)
    if comb is None or comb.golongan.empty:
        st.info("Unggah master rekap dan/atau laporan bulanan di Menu 1.")
        return
    for n in comb.notes:
        st.info(n)
    if not comb.crosscheck.empty:
        with st.expander("Cek silang laporan vs master (periode yang sama)", expanded=True):
            cc = comb.crosscheck.copy()
            show_table(cc, dec={"Master": 3, "Laporan": 3, "Selisih (laporan−master)": 3})
    labels = [str(p) for p in comb.golongan.index]
    if len(labels) < 2:
        st.warning("Minimal dua periode diperlukan.")
        return
    start_l, end_l = st.select_slider("Periode analisis", options=labels, value=(labels[0], labels[-1]))
    periods = [p for p in comb.golongan.index if start_l <= str(p) <= end_l]
    end = periods[-1]
    st.caption("Sumber tiap periode: " + ", ".join(f"{p}: {s}" for p, s in comb.source.items() if s != "master")
               if (comb.source != "master").any() else "Sumber semua periode: master rekap.")
    cols6 = config.GOLONGAN + ["TOTAL"]
    tbl = gc.growth_table(comb.golongan, periods, cols6)
    ly = pd.Period(year=end.year - 1, month=end.month, freq="M")

    # ----- ringkasan periode akhir (gaya laporan YOY PENJUALAN)
    st.subheader(f"Golongan S, R, B, I, P, L — {_pname(end)}")
    st.caption("Batang biru = pembanding, hijau-toska = realisasi; panah hijau naik / merah turun dengan persen "
               "pertumbuhan; tabel data di bawah grafik. TOTAL memakai sumbu sendiri di panel kanan agar "
               "golongan kecil tetap terbaca.")
    st.plotly_chart(_yoy_fig(tbl, cols6, end, "Kumulatif th lalu", "Kumulatif", "YoY Kumulatif (%)",
                             str(end.year - 1), str(end.year), f"YOY PENJUALAN sd {_pname(end)}", "% PENCAPAIAN",
                             separate_last=True), **WIDE_CHART)
    tabs = st.tabs(["MoM", "MoM-Tahun (vs bulan sama tahun lalu)", "Tren per bulan", "Tabel"])
    with tabs[0]:
        st.plotly_chart(_yoy_fig(tbl, cols6, end, "kWh bulan lalu", "kWh", "MoM (%)", _pname(end - 1), _pname(end),
                                 f"MoM PENJUALAN {_pname(end)} vs {_pname(end - 1)}", "% MoM",
                                 separate_last=True), **WIDE_CHART)
    with tabs[1]:
        st.plotly_chart(_yoy_fig(tbl, cols6, end, "kWh bulan sama th lalu", "kWh", "MoM-Tahun (%)", _pname(ly),
                                 _pname(end), f"PENJUALAN {_pname(end)} vs {_pname(ly)}", "% MoM-TAHUN",
                                 separate_last=True), **WIDE_CHART)
    with tabs[2]:
        metric = st.radio("Ukuran", list(TREND_METRICS), horizontal=True, key="trend_metric")
        st.caption("Satu grafik per tahun kalender dalam rentang periode yang dipilih.")
        for g in cols6:
            for f in _trend_figs(tbl, g, metric, f"{g} — {config.GOLONGAN_LABEL.get(g, g)}: {metric}"):
                st.plotly_chart(f, **WIDE_CHART)
    with tabs[3]:
        show_table(tbl, dec={"kWh": 3})
        st.download_button("⬇️ Unduh tabel", excel_bytes({"Pertumbuhan": tbl}), "pertumbuhan_golongan.xlsx")

    # ----- target
    st.subheader(f"Target & capaian (kumulatif s.d. {period_name(end.year, end.month)})")
    st.caption("Isi target kWh (kosong/0 = tidak dihitung). Capaian = realisasi kumulatif Jan s.d. bulan akhir ÷ target.")
    cols = st.columns(7)
    targets = {}
    for i, g in enumerate(config.GOLONGAN + ["TT"]):
        targets[g] = cols[i].number_input(f"Target {g}", min_value=0.0, value=0.0,
                                          step=float(config.TARGET_STEP_KWH), format="%.0f", key=f"tgt_{g}")
    tt_tbl = gc.target_table(comb.golongan, end, targets)
    show_table(tt_tbl, dec={"Realisasi kumulatif": 3})
    have = tt_tbl.dropna(subset=["Capaian (%)"])
    if len(have):
        st.plotly_chart(ch.yoy_chart(have["Golongan"], have["Target"], have["Realisasi kumulatif"],
                                     have["Capaian (%)"], "Target", f"Realisasi sd {_pname(end)}",
                                     f"CAPAIAN TARGET sd {_pname(end)}", pct_label="% CAPAIAN",
                                     arrow_rule="target"), **WIDE_CHART)

    # ----- TT
    st.subheader("TT — Tegangan Tinggi (tarif I.4)")
    tt = gc.growth_table(comb.golongan, periods, ["TT"])
    for f in ch.yoy_charts_by_year(tt["Periode"], tt["kWh bulan sama th lalu"], tt["kWh"], tt["MoM-Tahun (%)"],
                                   "Bulan sama th lalu", "Bulan berjalan", "TT — YOY PER BULAN", pct_label="% YOY"):
        st.plotly_chart(f, **WIDE_CHART)
    for f in ch.yoy_charts_by_year(tt["Periode"], tt["Kumulatif th lalu"], tt["Kumulatif"], tt["YoY Kumulatif (%)"],
                                   "Kumulatif th lalu", "Kumulatif th ini", "TT — YOY KUMULATIF",
                                   pct_label="% PENCAPAIAN"):
        st.plotly_chart(f, **WIDE_CHART)
    r = tt[tt["Periode"] == str(end)].iloc[0]
    m = st.columns(4)
    m[0].metric(f"kWh TT {period_name(end.year, end.month)}", fmt_id(r["kWh"]))
    m[1].metric("Kumulatif", fmt_id(r["Kumulatif"]), fmt_pct(r["YoY Kumulatif (%)"]) + " YoY")
    m[2].metric("Kumulatif th lalu", fmt_id(r["Kumulatif th lalu"]))
    t_tt = targets.get("TT") or 0
    m[3].metric("Capaian target TT", fmt_pct(r["Kumulatif"] / t_tt * 100) if t_tt else "–")
    with st.expander("Tabel TT"):
        show_table(tt.drop(columns=["Golongan"]))

    # ----- per jenis tarif
    st.subheader("Rincian per jenis tarif — YoY kumulatif")
    choice = st.selectbox("Golongan", ["Bisnis", "Industri"])
    code = "B" if choice == "Bisnis" else "I"
    jt = gc.tarif_yoy_cum(comb.tarif, comb.tarif_order, comb.tarif_labels, code, end)
    if jt.empty:
        st.info("Tidak ada data jenis tarif untuk golongan ini.")
        return
    st.plotly_chart(ch.yoy_chart(jt["Jenis tarif"], jt.iloc[:, 1], jt.iloc[:, 2], jt["YoY Kumulatif (%)"],
                                 str(end.year - 1), str(end.year),
                                 f"YOY PENJUALAN {choice.upper()} PER JENIS TARIF sd {_pname(end)}",
                                 pct_label="% PENCAPAIAN", separate_last=True), **WIDE_CHART)
    show_table(jt)
    st.download_button("⬇️ Unduh tabel jenis tarif", excel_bytes({choice: jt}), f"yoy_jenis_tarif_{choice}.xlsx")


# =========================================================================== MENU 3
SORT_OPTS = {"Bawaan (urutan data)": None, "PERSENTASE terbesar → terkecil": False,
             "PERSENTASE terkecil → terbesar": True}


def _sort_by_pct(tbl: pd.DataFrame, ascending):
    """Urutkan baris cluster menurut PERSENTASE (%); baris TOTAL tetap paling bawah."""
    if ascending is None:
        return tbl
    is_tot = tbl["Cluster"].astype(str).str.startswith("TOTAL")
    body = tbl[~is_tot].copy()
    body["_p"] = to_num(body["PERSENTASE (%)"]).fillna(0)
    body = body.sort_values("_p", ascending=ascending, kind="stable").drop(columns="_p")
    return pd.concat([body, tbl[is_tot]], ignore_index=True)


CHART_MODES = {"Persentase selisih (%)": "pct", "Selisih kWh": "kwh"}


def _kwh_text(values) -> List[str]:
    out = []
    for v in values:
        x = to_num(v)
        x = 0.0 if (x is None or not np.isfinite(x)) else x
        out.append(("▲ +" if x > 0 else ("▼ " if x < 0 else "")) + fmt_id(x) + " kWh")
    return out


def _cluster_charts(tbl: pd.DataFrame, lb: str, lc: str, follow_sort: bool = False, mode: str = "pct"):
    """mode 'pct' → grafik memakai PERSENTASE (%); mode 'kwh' → grafik memakai SELISIH (kWh)."""
    body = tbl[~tbl["Cluster"].astype(str).str.startswith("TOTAL")]
    h = max(400, config.CHART_ROW_HEIGHT * len(body) * 2)
    tot_b = body[lb].sum()
    fig = go.Figure()
    fig.add_trace(go.Bar(y=body["Cluster"], x=body[lb], orientation="h", name=lb, marker_color=config.COLOR_BASE,
                         text=[f"porsi {fmt_pct(v / tot_b * 100 if tot_b else 0.0)}" for v in body[lb]],
                         textposition="outside", cliponaxis=False))
    fig.add_trace(go.Bar(y=body["Cluster"], x=body[lc], orientation="h", name=lc, marker_color=config.COLOR_COMP,
                         text=(_kwh_text(body["SELISIH"]) if mode == "kwh" else
                               [("▲ " if to_num(v) >= 0 else "▼ ") + fmt_pct(v) for v in body["PERSENTASE (%)"]]),
                         textposition="outside", cliponaxis=False))
    lbl2 = "selisih kWh" if mode == "kwh" else "pertumbuhan %"
    fig.update_layout(barmode="group", height=h, title=f"{lb} vs {lc} per cluster (label: porsi / {lbl2})",
                      margin=dict(l=10, r=80, t=50, b=10), legend=dict(orientation="h", y=-0.02))
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, **WIDE_CHART)
    c1, c2 = st.columns(2)
    col = "SELISIH" if mode == "kwh" else "PERSENTASE (%)"
    srt = body.assign(_p=to_num(body[col]).fillna(0)).sort_values(
        "_p", ascending=False, kind="stable").drop(columns="_p")
    vals = [0 if not np.isfinite(v) else v for v in to_num(srt[col]).fillna(0)]
    colors = [config.COLOR_UP if v >= 0 else config.COLOR_DOWN for v in vals]
    if mode == "kwh":
        f2 = go.Figure(go.Bar(y=srt["Cluster"], x=vals, orientation="h", marker_color=colors,
                              text=_kwh_text(srt["SELISIH"]), textposition="outside", cliponaxis=False,
                              customdata=to_num(srt["PERSENTASE (%)"]).fillna(0),
                              hovertemplate="%{y}<br>SELISIH: %{x:,.0f} kWh<br>Growth: %{customdata:.2f}%"
                                            "<extra></extra>"))
        ttl, xt = f"GROWTH YoY (selisih kWh) — {lc} − {lb}, urut terbesar → terkecil", "kWh"
    else:
        f2 = go.Figure(go.Bar(y=srt["Cluster"], x=vals, orientation="h", marker_color=colors,
                              text=pct_text(srt["PERSENTASE (%)"]), textposition="outside", cliponaxis=False,
                              customdata=srt["SELISIH"],
                              hovertemplate="%{y}<br>Growth: %{x:.2f}%<br>SELISIH: %{customdata:,.0f} kWh"
                                            "<extra></extra>"))
        ttl, xt = f"GROWTH YoY (%) — {lc} vs {lb}, urut terbesar → terkecil", "%"
    f2.update_layout(title=ttl, height=max(400, config.CHART_ROW_HEIGHT * len(srt)),
                     margin=dict(l=10, r=90 if mode == "kwh" else 60, t=50, b=10), xaxis_title=xt)
    f2.update_yaxes(autorange="reversed")
    c1.plotly_chart(f2, **WIDE_CHART)
    k = "Kontribusi thd pertumbuhan (poin %)"
    srt2 = body if follow_sort else body.sort_values(k, ascending=False)
    c2.plotly_chart(bar_pct(srt2["Cluster"], srt2[k], "GROWTH CLUSTER — kontribusi thd pertumbuhan total (poin %)",
                            horizontal=True, height=max(400, config.CHART_ROW_HEIGHT * len(srt2))),
                    **WIDE_CHART)


Z = gc.zero_fill


def _cluster_help(lb: str, lc: str, tbl: pd.DataFrame):
    """Penjelasan arti kolom tabel cluster, termasuk rumus kontribusi."""
    body = tbl[~tbl["Cluster"].astype(str).str.startswith("TOTAL")]
    tot = tbl.iloc[-1]
    ex = body.sort_values("SELISIH", ascending=False).iloc[0] if len(body) else None
    k = "Kontribusi thd pertumbuhan (poin %)"
    with st.expander("ℹ️ Arti kolom & rumus (termasuk Kontribusi thd pertumbuhan)"):
        st.markdown(
            f"- **{lb} / {lc}** = jumlah kWh Januari s.d. bulan itu, per cluster.\n"
            f"- **SELISIH** = {lc} − {lb}.\n"
            f"- **PERSENTASE (%)** = SELISIH ÷ {lb} × 100 → pertumbuhan cluster itu sendiri.\n"
            f"- **Kontribusi thd pertumbuhan (poin %)** = SELISIH cluster ÷ **TOTAL {lb} semua cluster** × 100 → "
            "berapa *poin persen* dari pertumbuhan total yang disumbang cluster itu. Jumlah kontribusi semua "
            "cluster = PERSENTASE baris TOTAL. Positif = ikut menaikkan, negatif = menahan pertumbuhan total.\n"
            f"- **Porsi sd sekarang (%)** = {lc} cluster ÷ TOTAL {lc} × 100.\n"
            "- Nilai yang kosong ditampilkan **0**. PERSENTASE cluster yang pembandingnya 0 (cluster baru) "
            "juga ditampilkan 0 karena pembagian dengan 0 tidak bisa dihitung.")
        if ex is not None and tot[lb]:
            st.markdown(
                f"**Contoh dari data ini — {ex['Cluster']}:** SELISIH {fmt_id(ex['SELISIH'])} kWh ÷ TOTAL {lb} "
                f"{fmt_id(tot[lb])} kWh × 100 = **{fmt_pct(ex[k])} poin**. Artinya dari pertumbuhan total "
                f"{fmt_pct(tot['PERSENTASE (%)'])}, sebanyak {fmt_pct(ex[k])} poin berasal dari cluster ini; "
                f"sedangkan pertumbuhan cluster itu sendiri {fmt_pct(ex['PERSENTASE (%)'])}.")


def page_cluster():
    ui.page_header(MENUS[2], MENUS, title="Klaster Industri & Bisnis (KBLI)")
    res, mode = get_cluster_data()
    if res is None:
        st.info("Unggah database klaster I3I2B2 (dan AP2T bulan terbaru) di Menu 1.")
        return
    msg = {"etl": "Sumber: hasil ETL (Menu 1).",
           "preview": "Sumber: pratinjau penggabungan AP2T ke database (tombol ETL belum diklik).",
           "db_only": "Sumber: database apa adanya (AP2T belum diunggah)."}[mode]
    st.caption(msg + f" Bulan terbaru: {period_name(*res.period)}.")
    ap_period = res.period if mode in ("etl", "preview") else None
    tabs = st.tabs(list(res.sheets))
    for tab, (key, s) in zip(tabs, res.sheets.items()):
        with tab:
            periods = sorted(s.kwh_cols)
            labels = [period_name(*p) for p in periods]
            latest = tuple(res.period) if tuple(res.period) in s.kwh_cols else periods[-1]
            same_ly = (latest[0] - 1, latest[1])
            c1, c2 = st.columns(2)
            b_idx = periods.index(same_ly) if same_ly in periods else 0
            base_l = c1.selectbox("Bulan pembanding", labels, index=b_idx, key=f"base_{key}")
            comp_l = c2.selectbox("Bulan yang dibandingkan", labels, index=periods.index(latest), key=f"comp_{key}")
            base, comp = periods[labels.index(base_l)], periods[labels.index(comp_l)]
            all_cl = sorted(gc.cluster_frame(s)["cluster"].unique())
            chosen = st.multiselect("Filter cluster (kosong = semua cluster)", all_cl, key=f"flt_{key}")
            tbl, warns = gc.cluster_compare(s, base, comp, chosen or None)
            for w in warns:
                st.warning(w)
            lb, lc = f"sd {period_name(*base)}", f"sd {period_name(*comp)}"
            tot = tbl.iloc[-1]
            m = st.columns(4)
            m[0].metric(lb, fmt_id(tot[lb]))
            m[1].metric(lc, fmt_id(tot[lc]))
            m[2].metric("SELISIH", fmt_id(tot["SELISIH"]))
            m[3].metric("PERSENTASE", fmt_pct(tot["PERSENTASE (%)"]))
            # st.dataframe diurutkan di browser dan tidak memberi tahu Python, jadi grafik tidak bisa
            # mengikuti klik header tabel. Urutan dipilih di sini; tabel DAN grafik mengikuti pilihan ini.
            sort_l = st.radio("Urutkan tabel & grafik menurut PERSENTASE (%)", list(SORT_OPTS), horizontal=True,
                              key=f"sort_{key}")
            tbl = _sort_by_pct(tbl, SORT_OPTS[sort_l])
            mode_l = st.radio("Tampilkan grafik dalam bentuk", list(CHART_MODES), horizontal=True,
                              key=f"chartmode_{key}")
            _cluster_charts(tbl, lb, lc, follow_sort=SORT_OPTS[sort_l] is not None, mode=CHART_MODES[mode_l])
            show_table(tbl)
            _cluster_help(lb, lc, tbl)
            with st.expander("🧮 Rincian perhitungan per pelanggan (untuk cek manual)"):
                cl_opts = [c for c in tbl["Cluster"] if not str(c).startswith("TOTAL")]
                pick_cl = st.selectbox("Cluster", cl_opts, key=f"detcl_{key}")
                det = gc.cluster_detail(s, pick_cl, base, comp)
                st.caption("sd = jumlah kWh Januari s.d. bulan itu. SELISIH = sd terbaru − sd pembanding. "
                           "PERSENTASE = SELISIH ÷ sd pembanding × 100. Sel kosong / '-' / teks dibaca 0. "
                           "kWh bulan AP2T diambil dari file AP2T.")
                show_table(det, dec={"PERSENTASE (%)": 2})
                st.download_button("⬇️ Unduh rincian", excel_bytes({pick_cl[:31]: det}),
                                   f"rincian_{key.replace(' ', '')}.xlsx", key=f"dldet_{key}")
            st.download_button("⬇️ Unduh tabel cluster (Excel)", excel_bytes({key: tbl}),
                               f"cluster_{key.replace(' ', '')}_{period_label(*comp)}.xlsx", key=f"dl_{key}")
            with st.expander("🔎 Penjelasan bila hasil berbeda dari file laporan I3I2B2 asli"):
                rc = gc.reconcile(s, base, comp, ap_period)
                st.markdown("**Total file vs aplikasi** — File − Aplikasi = (1)+(3)+(5)+(8)+sisa; "
                            "sisa 0 berarti seluruh selisih terjelaskan.")
                show_table(Z(rc.totals))
                show_table(Z(rc.summary))
                for n in rc.notes:
                    st.caption(n)
                st.markdown("**Per cluster**")
                show_table(Z(rc.per_cluster))
                if rc.details:
                    names = {f"{n} ({len(d)} baris)": n for n, d in rc.details.items()}
                    pick = st.selectbox("Lihat daftar rinci per alasan", list(names), key=f"det_{key}_{base}_{comp}")
                    show_table(Z(rc.details[names[pick]]))
                st.download_button("⬇️ Unduh rekonsiliasi", excel_bytes(
                    {"Total": Z(rc.totals), "Alasan": Z(rc.summary), "Per cluster": Z(rc.per_cluster),
                     **{k[:28]: Z(v) for k, v in rc.details.items()}}),
                    f"rekonsiliasi_{key.replace(' ', '')}.xlsx", key=f"dlr_{key}")


# =========================================================================== MENU 4
def page_forecast():
    ui.page_header(MENUS[3], MENUS)
    with st.expander("ℹ️ Tentang menu ini — fungsi, data, model, dan pengaturan"):
        st.markdown(
            "**Fungsi menu ini:** memperkirakan penjualan kWh beberapa bulan ke depan dari pola historis, "
            "sebagai bahan perencanaan penjualan dan penetapan/pemantauan target.\n\n"
            "**Data yang dipakai:** deret kWh bulanan per golongan (S, R, B, I, P, L), TT (I.4), atau total UP3 dari "
            f"master rekap (mulai tabel Gabungan {config.MASTER_START_YEAR}) ditambah laporan bulanan untuk periode yang "
            "belum ada di master.\n\n"
            "**Model:** *XGBoost* belajar dari kWh bulan-bulan sebelumnya (lag), rata-rata bergerak, pola musiman "
            "bulanan, porsi hari Ramadhan dan bulan Idul Fitri, serta tren; bila xgboost tidak terpasang dipakai "
            "*GradientBoosting* (scikit-learn). *Prophet* memodelkan tren + musiman tahunan (+ efek Ramadhan).\n\n"
            "**Pengaturan:** *Horizon* = berapa bulan ke depan yang diperkirakan. *Hold-out* = berapa bulan terakhir "
            "yang disembunyikan dari model untuk menguji akurasinya (model menebak bulan-bulan itu, lalu dibandingkan "
            "dengan angka sebenarnya).\n\n"
            f"**Syarat data minimal:** {config.FORECAST_MIN_TRAIN_POINTS} bulan data latih + jumlah bulan hold-out, "
            "berurutan tanpa bolong.")
    comb = get_combined()
    if comb is None:
        st.warning("Unggah master rekap / laporan bulanan di Menu 1.")
        return
    opts = ["TOTAL"] + config.GOLONGAN + ["TT"]
    c = st.columns(4)
    opt_lbl = {f"{g} — {config.GOLONGAN_LABEL.get(g, g)}": g for g in opts}
    target = opt_lbl[c[0].selectbox("Deret", list(opt_lbl))]
    models = ["XGBoost (fallback GradientBoosting)"] + (["Prophet"] if fc.prophet_available() else [])
    model = c[1].selectbox("Model", models)
    horizon = c[2].number_input("Horizon (bulan)", 1, config.FORECAST_HORIZON_MAX, config.FORECAST_HORIZON_DEFAULT)
    holdout = c[3].number_input("Hold-out (bulan)", 1, config.FORECAST_HORIZON_MAX, config.FORECAST_HOLDOUT_DEFAULT)
    if not fc.prophet_available():
        st.caption("Prophet tidak terpasang di lingkungan ini (pip install prophet) — pilihan Prophet disembunyikan.")
    series = comb.golongan[target].dropna()
    problem = fc.check_series(series, int(holdout))
    if problem:
        st.warning(problem)
        return
    if st.button("▶️ Jalankan forecast", type="primary"):
        with st.spinner("Melatih model…"):
            try:
                if model == "Prophet":
                    r = fc.run_prophet_forecast(series, int(horizon), int(holdout))
                else:
                    r = fc.run_tree_forecast(series, int(horizon), int(holdout))
                ss.fc_result = ((target, model, int(horizon), int(holdout), len(series)), r)
            except Exception as e:  # noqa: BLE001
                st.error(f"Forecast gagal: {e}")
    if not ss.fc_result or ss.fc_result[0] != (target, model, int(horizon), int(holdout), len(series)):
        return
    r: fc.ForecastResult = ss.fc_result[1]
    for w in r.warnings:
        st.warning(w)
    st.markdown(f"**Model dipakai:** {r.model}")
    m = st.columns(3)
    m[0].metric("MAPE hold-out", fmt_pct(r.metrics["MAPE (%)"]))
    m[1].metric("RMSE hold-out (kWh)", fmt_id(r.metrics["RMSE (kWh)"]))
    m[2].metric(f"Perkiraan {period_name(r.forecast.index[0].year, r.forecast.index[0].month)}",
                fmt_id(r.forecast['yhat'].iloc[0]))
    x_h = [str(p) for p in r.history.index]
    x_f = [str(p) for p in r.forecast.index]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_h, y=r.history.values, name="Aktual", mode="lines+markers"))
    fig.add_trace(go.Scatter(x=[str(p) for p in r.test_pred.index], y=r.test_pred.values, name="Tebakan hold-out",
                             mode="lines+markers", line=dict(dash="dot")))
    fig.add_trace(go.Scatter(x=x_f + x_f[::-1], y=list(r.forecast["upper"]) + list(r.forecast["lower"])[::-1],
                             fill="toself", fillcolor="rgba(21,101,192,0.15)", line=dict(width=0),
                             name="Interval"))
    fig.add_trace(go.Scatter(x=x_f, y=r.forecast["yhat"], name="Perkiraan", mode="lines+markers",
                             line=dict(color=config.COLOR_COMP)))
    fig.update_layout(height=460, yaxis_title="kWh", margin=dict(t=30, b=10))
    st.plotly_chart(fig, **WIDE_CHART)
    out = r.forecast.reset_index().rename(columns={"index": "Periode", "yhat": "Perkiraan kWh",
                                                   "lower": "Batas bawah", "upper": "Batas atas"})
    out["Periode"] = out["Periode"].astype(str)
    show_table(out)
    st.download_button("⬇️ Unduh perkiraan", excel_bytes({"Forecast": out}), f"forecast_{target}.xlsx")
    mape = r.metrics["MAPE (%)"]
    band = next(lbl for lim, lbl in config.MAPE_BANDS if (mape if np.isfinite(mape) else float("inf")) <= lim)
    avg = r.history.iloc[-int(holdout):].mean()
    st.success(
        "**Cara membaca hasil**\n\n"
        f"- **MAPE {fmt_pct(mape)}** artinya, saat diuji pada {int(holdout)} bulan terakhir yang disembunyikan, "
        f"tebakan model rata-rata meleset sekitar {fmt_pct(mape)} dari angka sebenarnya → tergolong **{band}**.\n"
        f"- **RMSE {fmt_id(r.metrics['RMSE (kWh)'])} kWh** adalah besar kesalahan tipikal dalam kWh "
        f"(≈ {fmt_pct(r.metrics['RMSE (kWh)'] / avg * 100 if avg else np.nan)} dari rata-rata kWh bulanan periode uji); "
        "kesalahan besar diberi bobot lebih.\n"
        "- **Interval** (area biru) adalah rentang wajar tempat angka realisasi kemungkinan besar jatuh; "
        "makin jauh ke depan makin lebar karena ketidakpastian bertambah.\n"
        "- **Pemakaian:** jadikan perkiraan sebagai titik tengah penyusunan/pemantauan target, dan batas bawah "
        "sebagai skenario waspada. Bila realisasi keluar dari interval, telusuri penyebabnya (pelanggan besar, "
        "gangguan, mutasi, koreksi rekening).\n"
        "- **Batasan:** ini perkiraan berbasis pola masa lalu, bukan kepastian. Model tidak tahu kejadian baru "
        "(pelanggan besar baru/berhenti, perubahan tarif, pemadaman). Data historis yang pendek membuat hasil kurang "
        "stabil; perbarui setiap bulan setelah laporan baru diunggah.")


# =========================================================================== MENU 5
def page_anomaly():
    ui.page_header(MENUS[4], MENUS)
    with st.expander("ℹ️ Tentang menu ini — fungsi, data, model, dan pengaturan"):
        st.markdown(
            "**Fungsi menu ini:** menandai pelanggan Industri/Bisnis (DB I / DB B) yang konsumsinya melonjak atau "
            "turun tidak wajar, dan mengelompokkan pelanggan berdasarkan bentuk pola konsumsinya — untuk menentukan "
            "prioritas pengecekan lapangan atau pengecekan data.\n\n"
            "**Pengaturan:** *Jendela bulan* = berapa bulan terakhir yang dianalisis. *Contamination* = perkiraan "
            "porsi pelanggan yang dianggap janggal (0,05 = sekitar 5% ditandai). *Jumlah kelompok pola* = berapa "
            "kelompok K-Means yang dibentuk.\n\n"
            "**Metode:** *Isolation Forest* membaca pertumbuhan bulan-ke-bulan (MoM) tiap pelanggan dan memberi skor "
            "kejanggalan. *K-Means* mengelompokkan pola konsumsi yang sudah dinormalisasi z-score per pelanggan, "
            "sehingga pelanggan besar dan kecil dibandingkan dari bentuk polanya, bukan besarnya.\n\n"
            "**Penting:** hasil bukan vonis pelanggaran, melainkan daftar prioritas untuk ditelusuri.")
    res, mode = get_cluster_data()
    if res is None:
        st.warning("Unggah database klaster (dan AP2T) di Menu 1.")
        return
    c = st.columns(4)
    key = c[0].selectbox("Database", list(res.sheets))
    s = res.sheets[key]
    periods = sorted(s.kwh_cols)
    end = tuple(res.period) if tuple(res.period) in s.kwh_cols else periods[-1]
    n_av = len([p for p in periods if p <= end])
    window = c[1].number_input("Jendela bulan", 3, max(3, n_av), min(config.ANOMALY_WINDOW_DEFAULT, n_av))
    cont = c[2].slider("Contamination", 0.01, config.ANOMALY_CONTAMINATION_MAX, config.ANOMALY_CONTAMINATION_DEFAULT,
                       0.01)
    k = c[3].number_input("Jumlah kelompok pola (K)", 2, config.KMEANS_K_MAX, config.KMEANS_K_DEFAULT)
    params = (key, int(window), float(cont), int(k), end, etl_key())
    if st.button("▶️ Jalankan deteksi anomali", type="primary"):
        with st.spinner("Menghitung…"):
            try:
                ss.an_result = (params, an.run_anomaly(s, int(window), end, float(cont), int(k)))
            except Exception as e:  # noqa: BLE001
                st.error(f"Gagal: {e}")
    if not ss.an_result or ss.an_result[0] != params:
        return
    r: an.AnomalyResult = ss.an_result[1]
    for w in r.warnings:
        st.warning(w)
    st.caption(f"Jendela: {r.months[0]} s.d. {r.months[-1]}")
    m = st.columns(3)
    m[0].metric("Pelanggan dianalisis", fmt_id(len(r.table)))
    m[1].metric("Ditandai anomali", fmt_id((r.table["Anomali?"] == "Ya").sum()))
    m[2].metric("Kelompok pola", fmt_id(len(r.pattern_names)))
    fig = go.Figure()
    for flag, colr in [("Tidak", config.COLOR_BASE), ("Ya", config.COLOR_DOWN)]:
        d = r.table[r.table["Anomali?"] == flag]
        fig.add_trace(go.Scatter(x=d["MoM terakhir (%)"], y=d["Skor anomali"], mode="markers", name=f"Anomali: {flag}",
                                 marker=dict(color=colr, size=9), text=d["IDPEL"]))
    fig.update_layout(title="Skor anomali vs pertumbuhan MoM bulan terakhir", xaxis_title="MoM terakhir (%)",
                      yaxis_title="Skor anomali", height=420)
    st.plotly_chart(fig, **WIDE_CHART)
    only = st.checkbox("Tampilkan hanya yang ditandai anomali", value=True)
    tbl = r.table[r.table["Anomali?"] == "Ya"] if only else r.table
    show_table(tbl, dec={"Skor anomali": 3})
    st.subheader("Kelompok pola konsumsi (K-Means, z-score)")
    f2 = go.Figure()
    for i, name in r.pattern_names.items():
        n = int((r.table["Kelompok pola"] == i).sum())
        f2.add_trace(go.Scatter(x=r.months, y=r.centroids.iloc[i], mode="lines+markers",
                                name=f"Kelompok {i} ({n} plg): {name}"))
    f2.update_layout(height=420, yaxis_title="z-score (0 = rata-rata pelanggan itu)", legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(f2, **WIDE_CHART)
    pick = st.selectbox("Lihat pola satu pelanggan", r.table["IDPEL"].tolist())
    mat = an.consumption_matrix(s, int(window), end)
    if pick in mat.index:
        f3 = go.Figure(go.Bar(x=list(mat.columns), y=mat.loc[pick].values, marker_color=config.COLOR_COMP))
        f3.update_layout(height=320, title=f"kWh bulanan IDPEL {pick}", yaxis_title="kWh")
        st.plotly_chart(f3, **WIDE_CHART)
    st.download_button("⬇️ Unduh hasil anomali", excel_bytes({"Anomali": r.table,
                                                              "Pola kelompok": r.centroids.assign(
                                                                  Pola=[r.pattern_names[i] for i in r.centroids.index])}),
                       f"anomali_{key.replace(' ', '')}.xlsx")
    st.success(
        "**Cara membaca hasil**\n\n"
        "- **Skor anomali**: makin tinggi makin janggal pola pertumbuhan MoM pelanggan itu dibanding pelanggan lain. "
        "Kolom *Anomali? = Ya* adalah porsi teratas sesuai *contamination*.\n"
        "- **Perubahan MoM terbesar** dan bulannya menunjukkan kapan lonjakan/penurunan terjadi.\n"
        "- **Kelompok pola**: pelanggan dalam satu kelompok memiliki bentuk kurva mirip (mis. *tren naik*, "
        "*tren turun*, *relatif stabil*, *berfluktuasi*). Pelanggan yang polanya tidak lazim untuk cluster usahanya "
        "layak dicek.\n"
        "- **Contoh tindak lanjut**: cek meter/kWh meter & CT (turun mendadak), cek mutasi (ubah daya/tarif, "
        "pindah/berhenti), cek kemungkinan salah input stand/faktor kali (lonjakan satu bulan lalu normal), "
        "konfirmasi ke pelanggan (perubahan kapasitas produksi).\n"
        "- **Batasan**: model hanya melihat angka kWh; perubahan wajar (musim produksi, libur, ekspansi) juga bisa "
        "ditandai. Pelanggan baru dengan data pendek cenderung terlihat melonjak. Gunakan sebagai daftar telusur, "
        "bukan kesimpulan.")


# =========================================================================== main
def main():
    ui.inject_css()
    if ui.MISSING_CONFIG:
        import os
        st.warning(
            f"config.py yang terbaca adalah versi lama: `{os.path.abspath(config.__file__)}` — tidak memuat "
            f"{', '.join(ui.MISSING_CONFIG)}. Aplikasi memakai nilai bawaan tampilan. Ganti config.py dengan "
            "versi dari paket proyek terbaru, lalu hentikan (Ctrl+C) dan jalankan ulang `streamlit run app.py`.")
    ui.sidebar_brand()
    page = ui.nav(MENUS)
    sidebar_status()
    {MENUS[0]: page_upload, MENUS[1]: page_growth, MENUS[2]: page_cluster,
     MENUS[3]: page_forecast, MENUS[4]: page_anomaly}[page]()


main()
