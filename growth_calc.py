"""Perhitungan pertumbuhan (Menu 2) dan analisis cluster KBLI + rekonsiliasi (Menu 3)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config
from modules.column_utils import normalize_cluster, parse_period_col, normalize_idpel, period_name, to_num, to_period
from modules.etl_merge import EtlSheetResult, compute_sd, sd_columns_for

SERIES_COLS = config.GOLONGAN + ["TT", "TOTAL"]


# =========================================================================== util
def pct(cur, prev):
    """Pertumbuhan %: NaN bila pembanding tidak ada / 0 (ditampilkan '–')."""
    cur, prev = to_num(cur), to_num(prev)
    if isinstance(cur, np.ndarray) or isinstance(prev, np.ndarray):
        cur, prev = np.asarray(cur, float), np.asarray(prev, float)
        with np.errstate(divide="ignore", invalid="ignore"):
            out = (cur - prev) / np.abs(prev) * 100.0
        out[~np.isfinite(out)] = np.nan
        return out
    if not np.isfinite(cur) or not np.isfinite(prev) or prev == 0:
        return np.nan
    return (cur - prev) / abs(prev) * 100.0


# =========================================================================== gabung master + laporan
@dataclass
class CombinedData:
    golongan: pd.DataFrame                 # index Period, kolom S..L, TT, TOTAL
    tarif: pd.DataFrame                    # long: period, year, month, tarif, key, golongan, tt, kwh
    tarif_order: List[str]
    tarif_labels: Dict[str, str]
    source: pd.Series                      # Period → 'master' / 'laporan (nama file)'
    notes: List[str] = field(default_factory=list)
    crosscheck: pd.DataFrame = field(default_factory=pd.DataFrame)


def combine_sources(master, reports: List[Tuple[str, object]]) -> CombinedData:
    """Master adalah acuan. Laporan hanya mengisi periode yang belum ada di master."""
    gol = master.golongan.copy() if master is not None else pd.DataFrame(columns=SERIES_COLS)
    tar = master.tarif.copy() if master is not None else pd.DataFrame(
        columns=["period", "year", "month", "tarif", "key", "golongan", "tt", "kwh"])
    order = list(master.tarif_order) if master is not None else []
    labels = dict(master.tarif_labels) if master is not None else {}
    source = pd.Series("master", index=gol.index, dtype=object)
    notes, checks = [], []
    for fname, rep in sorted(reports, key=lambda x: x[1].period):
        p = to_period(*rep.period)
        rg = rep.golongan["kwh"]
        if p in gol.index and source.get(p) == "master":
            notes.append(f"Periode {period_name(*rep.period)} sudah ada di master; data laporan "
                         f"({fname}) tidak menimpa.")
            for g in SERIES_COLS:
                mv, lv = gol.at[p, g], rg.get(g, np.nan)
                checks.append({"Periode": str(p), "Level": "Golongan", "Uraian": g,
                               "Master": mv, "Laporan": lv, "Selisih (laporan−master)": lv - mv})
            mt = tar[tar["period"] == p].set_index("key")["kwh"]
            for _, r in rep.tarif.iterrows():
                mv = mt.get(r["key"], np.nan)
                checks.append({"Periode": str(p), "Level": "Jenis tarif", "Uraian": r["tarif"],
                               "Master": mv, "Laporan": r["kwh"], "Selisih (laporan−master)": r["kwh"] - mv})
            continue
        if p in gol.index:                                # sudah diisi laporan lain
            notes.append(f"Periode {period_name(*rep.period)} sudah diisi laporan lain; {fname} diabaikan.")
            continue
        gol.loc[p] = [rg.get(g, np.nan) for g in SERIES_COLS]
        source.loc[p] = f"laporan ({fname})"
        notes.append(f"Periode {period_name(*rep.period)} belum ada di master; diisi dari laporan {fname}.")
        t = rep.tarif.copy()
        t["period"], t["year"], t["month"] = p, rep.period[0], rep.period[1]
        for k, lab in zip(t["key"], t["tarif"]):
            if k not in labels:
                labels[k] = lab
                order.append(k)
        tar = pd.concat([tar, t[["period", "year", "month", "tarif", "key", "golongan", "tt", "kwh"]]],
                        ignore_index=True)
    gol = gol.sort_index().astype(float)
    source = source.sort_index()
    return CombinedData(gol, tar, order, labels, source, notes, pd.DataFrame(checks))


# =========================================================================== metrik pertumbuhan
def _shift_year(p: pd.Period, n: int = 1) -> pd.Period:
    return pd.Period(year=p.year - n, month=p.month, freq="M")


def cumulative(series: pd.Series, p: pd.Period) -> float:
    """Kumulatif Jan..p pada tahun p; NaN bila ada bulan yang tidak tersedia."""
    need = [pd.Period(year=p.year, month=m, freq="M") for m in range(1, p.month + 1)]
    if any(q not in series.index or not np.isfinite(series.get(q, np.nan)) for q in need):
        return np.nan
    return float(series.loc[need].sum())


def growth_table(gol: pd.DataFrame, periods: List[pd.Period], cols: List[str]) -> pd.DataFrame:
    """Baris per (periode, golongan): kWh, MoM, MoM-Tahun, kumulatif, YoY kumulatif."""
    rows = []
    for p in periods:
        for g in cols:
            s = gol[g]
            cur = s.get(p, np.nan)
            prev = s.get(p - 1, np.nan)
            ly = s.get(_shift_year(p), np.nan)
            cum = cumulative(s, p)
            cum_ly = cumulative(s, _shift_year(p))
            rows.append({"Periode": str(p), "Golongan": g, "kWh": cur, "kWh bulan lalu": prev,
                         "MoM (%)": pct(cur, prev), "kWh bulan sama th lalu": ly,
                         "MoM-Tahun (%)": pct(cur, ly), "Kumulatif": cum,
                         "Kumulatif th lalu": cum_ly, "YoY Kumulatif (%)": pct(cum, cum_ly)})
    return pd.DataFrame(rows)


def target_table(gol: pd.DataFrame, end: pd.Period, targets: Dict[str, float]) -> pd.DataFrame:
    rows = []
    for g, t in targets.items():
        cum = cumulative(gol[g], end)
        rows.append({"Golongan": g, "Realisasi kumulatif": cum, "Target": t if t else np.nan,
                     "Capaian (%)": (cum / t * 100.0) if t and np.isfinite(cum) else np.nan})
    return pd.DataFrame(rows)


def tarif_yoy_cum(tar: pd.DataFrame, order: List[str], labels: Dict[str, str], golongan: str,
                  end: pd.Period) -> pd.DataFrame:
    """YoY kumulatif per jenis tarif untuk satu golongan (B atau I) s.d. periode `end`."""
    sub = tar[tar["golongan"] == golongan]
    prev_end = _shift_year(end)
    rows = []
    for k in [k for k in order if k in set(sub["key"])]:
        s = sub[sub["key"] == k].set_index("period")["kwh"]
        s = s[~s.index.duplicated(keep="last")]
        now, ly = cumulative(s, end), cumulative(s, prev_end)
        rows.append({"Jenis tarif": labels[k], f"Kumulatif {period_name(prev_end.year, prev_end.month)}": ly,
                     f"Kumulatif {period_name(end.year, end.month)}": now, "Selisih": now - ly,
                     "YoY Kumulatif (%)": pct(now, ly)})
    df = pd.DataFrame(rows)
    if len(df):
        c_ly, c_now = df.columns[1], df.columns[2]
        tot = {"Jenis tarif": "JUMLAH", c_ly: df[c_ly].sum(min_count=1), c_now: df[c_now].sum(min_count=1)}
        if df[c_ly].isna().any():
            tot[c_ly] = np.nan
        if df[c_now].isna().any():
            tot[c_now] = np.nan
        tot["Selisih"] = tot[c_now] - tot[c_ly]
        tot["YoY Kumulatif (%)"] = pct(tot[c_now], tot[c_ly])
        df = pd.concat([df, pd.DataFrame([tot])], ignore_index=True)
    return df


# =========================================================================== cluster (Menu 3)
def zero_fill(df: pd.DataFrame) -> pd.DataFrame:
    """Menu 3: nilai kosong / '-' / '–' menjadi 0 (kolom angka); teks kosong menjadi string kosong.

    Catatan: PERSENTASE dengan pembanding 0 secara matematis tak terdefinisi; sesuai aturan Menu 3
    nilainya ditampilkan 0 (config.CLUSTER_EMPTY_AS_ZERO).
    """
    if not config.CLUSTER_EMPTY_AS_ZERO or df is None or df.empty:
        return df
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_numeric_dtype(out[c]):
            out[c] = out[c].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        else:
            col = out[c].astype(object)
            dash = col.map(lambda v: isinstance(v, str) and v.strip() in ("-", "–", "—"))
            col = col.where(~dash, 0)
            out[c] = col.where(col.notna(), "")
    return out



def available_kwh_periods(s: EtlSheetResult) -> List[Tuple[int, int]]:
    return sorted(s.kwh_cols)


def _dedup_mask(ids: pd.Series) -> pd.Series:
    """True = baris dipakai (IDPEL ganda hanya dihitung sekali bila config mengaktifkan)."""
    if not config.DEDUP_IDPEL_IN_CLUSTER:
        return pd.Series(True, index=ids.index)
    return ~ids.duplicated(keep="first")


def cluster_frame(s: EtlSheetResult) -> pd.DataFrame:
    """Kolom bantu: IDPEL ternormalisasi, kunci cluster, nama cluster tampil."""
    df = s.df
    ids = df[s.idpel_col].map(normalize_idpel)
    raw = df[s.cluster_col] if s.cluster_col else pd.Series("(tanpa cluster)", index=df.index)
    raw = raw.fillna("(tanpa cluster)").astype(str)
    key = raw.map(normalize_cluster).replace("", "(tanpa cluster)")
    disp = raw.str.strip().str.replace(r"\s+", " ", regex=True).groupby(key).agg(
        lambda x: x.value_counts().index[0])
    return pd.DataFrame({"idpel": ids, "key": key, "cluster": key.map(disp), "use": _dedup_mask(ids)})


def cluster_compare(s: EtlSheetResult, base: Tuple[int, int], comp: Tuple[int, int],
                    clusters: Optional[List[str]] = None) -> Tuple[pd.DataFrame, List[str]]:
    """sd per cluster: base (pembanding) vs comp (yang dibandingkan). `clusters` = filter nama cluster."""
    info = cluster_frame(s)
    if clusters is not None:
        info = info.assign(use=info["use"] & info["cluster"].isin(clusters))
    warns = []
    for y, m in (base, comp):
        _, miss = sd_columns_for(s.kwh_cols, y, m)
        if miss:
            warns.append(f"sd {period_name(y, m)}: kolom KWH bulan {miss} tahun {y} tidak ada di database "
                         f"(dianggap 0).")
    sd_b = compute_sd(s.df, s.kwh_cols, *base)
    sd_c = compute_sd(s.df, s.kwh_cols, *comp)
    d = pd.DataFrame({"cluster": info["cluster"], "b": sd_b, "c": sd_c, "n": 1})[info["use"]]
    g = d.groupby("cluster").agg(pelanggan=("n", "sum"), b=("b", "sum"), c=("c", "sum"))
    lb, lc = f"sd {period_name(*base)}", f"sd {period_name(*comp)}"
    g = g.rename(columns={"pelanggan": "Jumlah pelanggan", "b": lb, "c": lc})
    g["SELISIH"] = g[lc] - g[lb]
    g["PERSENTASE (%)"] = pct(g[lc].to_numpy(), g[lb].to_numpy())
    tot_b = g[lb].sum()
    g["Kontribusi thd pertumbuhan (poin %)"] = g["SELISIH"] / tot_b * 100.0 if tot_b else np.nan
    g["Porsi sd sekarang (%)"] = g[lc] / g[lc].sum() * 100.0 if g[lc].sum() else np.nan
    g = g.sort_values(lc, ascending=False).reset_index().rename(columns={"cluster": "Cluster"})
    total = {"Cluster": "TOTAL" if clusters is None else "TOTAL (terfilter)", "Jumlah pelanggan": g["Jumlah pelanggan"].sum(), lb: g[lb].sum(),
             lc: g[lc].sum()}
    total["SELISIH"] = total[lc] - total[lb]
    total["PERSENTASE (%)"] = pct(total[lc], total[lb])
    total["Kontribusi thd pertumbuhan (poin %)"] = total["PERSENTASE (%)"]
    total["Porsi sd sekarang (%)"] = 100.0 if total[lc] else np.nan
    g = pd.concat([g, pd.DataFrame([total])], ignore_index=True)
    return zero_fill(g), warns


def cluster_detail(s: EtlSheetResult, cluster: str, base: Tuple[int, int], comp: Tuple[int, int]) -> pd.DataFrame:
    """Rincian hitungan satu cluster: kWh tiap bulan Jan..bulan per pelanggan, sd, SELISIH, PERSENTASE.

    Nilai kosong / selain angka dibaca 0 (sama dengan perhitungan tabel cluster).
    """
    info = cluster_frame(s)
    mask = (info["cluster"] == cluster) & info["use"]
    df = s.df[mask]
    out = pd.DataFrame({"IDPEL": info.loc[mask, "idpel"]})
    if s.nama_col:
        out["Nama"] = df[s.nama_col].values
    sd = {}
    for (y, m) in (base, comp):
        cols, _ = sd_columns_for(s.kwh_cols, y, m)
        for c in cols:
            p = parse_period_col(c)
            out[f"{config.CANON_MONTH_ABBR[p[2]]} {p[1]}"] = to_num(df[c]).fillna(0.0).values
        sd[(y, m)] = compute_sd(df, s.kwh_cols, y, m).values
        out[f"sd {period_name(y, m)}"] = sd[(y, m)]
    out["SELISIH"] = sd[comp] - sd[base]
    out["PERSENTASE (%)"] = pct(sd[comp], sd[base])
    tot = {c: out[c].sum() for c in out.columns if c not in ("IDPEL", "Nama")}
    tot["IDPEL"] = "TOTAL"
    tot["PERSENTASE (%)"] = pct(tot[f"sd {period_name(*comp)}"], tot[f"sd {period_name(*base)}"])
    out = pd.concat([out, pd.DataFrame([tot])], ignore_index=True)
    return zero_fill(out)


# =========================================================================== rekonsiliasi
@dataclass
class Reconciliation:
    summary: pd.DataFrame        # per alasan × periode: baris, kWh terkait, dampak
    details: Dict[str, pd.DataFrame]
    per_cluster: pd.DataFrame    # per cluster: file vs aplikasi vs pivot + sisa
    totals: pd.DataFrame         # ringkasan total file/app/pivot per periode
    notes: List[str]


def _row_components(s: EtlSheetResult, info: pd.DataFrame, y: int, m: int, ap_period: Tuple[int, int]):
    """Komponen per baris untuk sd (y, m): nilai file, aplikasi, dan istilah rekonsiliasi."""
    before, after = s.df_before, s.df
    cols_app, _ = sd_columns_for(s.kwh_cols, y, m)
    kwh_file = pd.Series(0.0, index=before.index)
    kwh_app = pd.Series(0.0, index=after.index)
    etl_empty = pd.Series(0.0, index=after.index)      # alasan 5: bulan AP2T kosong/0 di file
    etl_changed = pd.Series(0.0, index=after.index)    # alasan 8: nilai file ≠ AP2T
    for mm in range(1, m + 1):
        c = s.kwh_cols.get((y, mm))
        if c is None:
            continue
        a = to_num(after[c]).fillna(0.0)
        f = to_num(before[c]).fillna(0.0) if c in before.columns else pd.Series(0.0, index=before.index)
        kwh_app += a
        kwh_file += f
        if (y, mm) == tuple(ap_period):
            fe = to_num(before[c]) if c in before.columns else pd.Series(np.nan, index=before.index)
            empty = fe.isna() | (fe == 0)
            etl_empty += np.where(empty, f - a, 0.0)
            etl_changed += np.where(~empty, f - a, 0.0)
    sd_col = s.sd_cols_file.get((y, m))
    if sd_col is not None:
        sd_file = to_num(before[sd_col]).fillna(0.0)
        file_src = f"kolom '{sd_col}' di file"
    else:
        sd_file = kwh_file.copy()
        file_src = "jumlah kolom KWH di file (file tidak punya kolom sd periode ini)"
    use = info["use"]
    comp = pd.DataFrame({
        "idpel": info["idpel"], "cluster": info["cluster"], "use": use,
        "sd_file": sd_file, "kwh_file": kwh_file, "sd_app": kwh_app.where(use, 0.0),
        "r1": sd_file - kwh_file,                                   # sd file ≠ Σ KWH
        "r3": kwh_file.where(~use, 0.0),                            # IDPEL ganda (dihitung file, tidak oleh aplikasi)
        "r5": etl_empty.where(use, 0.0), "r8": etl_changed.where(use, 0.0),
    })
    return comp, file_src


REASONS = {
    "r1": "(1) sd di file berbeda dari jumlah KWH Jan–bulan itu (mis. di-nol-kan untuk pelanggan mutasi)",
    "r2": "(2) Pelanggan ada di AP2T tetapi belum ada di database (belum dihitung di kedua total)",
    "r3": "(3) IDPEL ganda di database → di file/pivot terhitung dua kali, aplikasi menghitung sekali",
    "r4": "(4) Pelanggan ada di database tetapi tidak ada di AP2T bulan itu (nilai bulan itu tetap dari file)",
    "r5": "(5) Bulan AP2T kosong/0 di file, diisi aplikasi dari AP2T",
    "r5i": "(5b) Sel KWH bulan lain kosong/0 di file (dihitung 0 di kedua sisi; menjelaskan pertumbuhan, bukan selisih; hitungan = sel)",
    "r6": "(6) Nama cluster sama dengan ejaan berbeda → digabung aplikasi",
    "r7": "(7) Pivot di file berbeda dengan jumlah kolom sd (pivot belum di-refresh / beda filter)",
    "r8": "(8) Nilai KWH bulan AP2T di file berbeda dengan AP2T → ditimpa AP2T",
}


def reconcile(s: EtlSheetResult, base: Tuple[int, int], comp_p: Tuple[int, int],
              ap_period: Optional[Tuple[int, int]]) -> Reconciliation:
    """Rekonsiliasi total file (kolom sd/pivot I3I2B2 asli) vs hasil aplikasi, per alasan.

    Identitas per periode: File − Aplikasi = (1) + (3) + (5) + (8) + sisa, dengan sisa = 0 bila
    semua selisih terjelaskan. (2), (4), (5b), (6) informatif (tidak mengubah total), (7) = pivot − file.
    """
    ap_period = tuple(ap_period) if ap_period else (0, 0)
    info = cluster_frame(s)
    periods = [("pembanding", base), ("dibandingkan", comp_p)]
    rows, details, notes, tot_rows = [], {}, [], []
    per_cluster = []
    comps = {}
    for tag, (y, m) in periods:
        comp, src = _row_components(s, info, y, m, ap_period)
        comps[tag] = comp
        lab = period_name(y, m)
        F, A = comp["sd_file"].sum(), comp["sd_app"].sum()
        piv = s.pivot.get((y, m))
        P = float(piv.sum()) if piv is not None else np.nan
        tot_rows.append({"Periode": f"sd {lab} ({tag})", "Sumber angka file": src,
                         "Total file": F, "Total aplikasi": A, "Selisih file−aplikasi": F - A,
                         "Total pivot di file": P,
                         "Selisih pivot−aplikasi": P - A if np.isfinite(P) else np.nan})
        explained = 0.0
        for r in ("r1", "r3", "r5", "r8"):
            mask = comp[r].abs() > 1e-9
            impact = float(comp.loc[mask, r].sum())
            explained += impact
            rows.append({"Periode": lab, "Alasan": REASONS[r], "Jumlah baris": int(mask.sum()),
                         "kWh terkait": impact, "Dampak ke selisih file−aplikasi": impact})
            if mask.any():
                det = s.df_before.loc[mask, [c for c in [s.idpel_col, s.nama_col, s.cluster_col] if c]].copy()
                det["Nilai file"] = comp.loc[mask, "sd_file"] if r == "r1" else comp.loc[mask, "kwh_file"]
                det["Nilai aplikasi"] = comp.loc[mask, "sd_app"] if r != "r1" else comp.loc[mask, "kwh_file"]
                det["Dampak"] = comp.loc[mask, r]
                details[f"{REASONS[r][:4]} {lab}"] = det
        residual = (F - A) - explained
        rows.append({"Periode": lab, "Alasan": "Sisa yang belum terjelaskan", "Jumlah baris": np.nan,
                     "kWh terkait": residual, "Dampak ke selisih file−aplikasi": residual})
        # pivot vs file (alasan 7)
        if piv is not None:
            fc = comp.groupby(comp["cluster"].map(normalize_cluster))["sd_file"].sum()
            diff = piv.reindex(piv.index.union(fc.index)).fillna(0) - fc.reindex(piv.index.union(fc.index)).fillna(0)
            dmask = diff.abs() > config.TOTAL_TOLERANCE_KWH
            rows.append({"Periode": lab, "Alasan": REASONS["r7"], "Jumlah baris": int(dmask.sum()),
                         "kWh terkait": float(diff[dmask].sum()),
                         "Dampak ke selisih file−aplikasi": np.nan})
            if dmask.any():
                details[f"(7)  {lab}"] = pd.DataFrame({"Cluster (kunci)": diff[dmask].index,
                                                       "Pivot − kolom sd": diff[dmask].values})
        # per cluster
        g = comp.groupby("cluster").agg(file=("sd_file", "sum"), app=("sd_app", "sum"),
                                        r1=("r1", "sum"), r3=("r3", "sum"), r5=("r5", "sum"), r8=("r8", "sum"))
        g["sisa"] = (g["file"] - g["app"]) - g[["r1", "r3", "r5", "r8"]].sum(axis=1)
        if piv is not None:
            g["pivot"] = g.index.map(lambda c: piv.get(normalize_cluster(c), np.nan))
        else:
            g["pivot"] = np.nan
        g.insert(0, "Periode", lab)
        per_cluster.append(g.reset_index())

    # alasan informatif (tidak mengubah selisih file−aplikasi)
    ap_lab = period_name(*ap_period) if ap_period != (0, 0) else "-"
    new_c = s.new_customers
    rows.append({"Periode": ap_lab, "Alasan": REASONS["r2"], "Jumlah baris": len(new_c),
                 "kWh terkait": float(new_c["KWH"].sum()) if len(new_c) else 0.0,
                 "Dampak ke selisih file−aplikasi": 0.0})
    if len(new_c):
        details["(2)  AP2T tidak ada di database"] = new_c
    ni = s.not_in_ap2t
    col = s.target_col
    rows.append({"Periode": ap_lab, "Alasan": REASONS["r4"], "Jumlah baris": len(ni),
                 "kWh terkait": float(to_num(ni[col]).fillna(0).sum()) if len(ni) else 0.0,
                 "Dampak ke selisih file−aplikasi": 0.0})
    if len(ni):
        details["(4)  Database tidak ada di AP2T"] = ni
    # (5b) bulan lain kosong/0
    zero_rows = []
    for tag, (y, m) in periods:
        for mm in range(1, m + 1):
            c = s.kwh_cols.get((y, mm))
            if c is None or (y, mm) == tuple(ap_period):
                continue
            v = to_num(s.df[c])
            z = (v.isna() | (v == 0)) & info["use"]
            for i in v.index[z]:
                zero_rows.append({"IDPEL": info.at[i, "idpel"], "Cluster": info.at[i, "cluster"],
                                  "Kolom": c, "Isi file": "kosong" if pd.isna(v[i]) else "0"})
    zr = pd.DataFrame(zero_rows).drop_duplicates() if zero_rows else pd.DataFrame()
    rows.append({"Periode": "semua", "Alasan": REASONS["r5i"], "Jumlah baris": len(zr),
                 "kWh terkait": 0.0, "Dampak ke selisih file−aplikasi": 0.0})
    if len(zr):
        details["(5b) Sel KWH kosong/0"] = zr
    # (6) ejaan cluster
    raw = s.df[s.cluster_col].fillna("").astype(str).str.strip() if s.cluster_col else pd.Series(dtype=str)
    var = pd.DataFrame({"raw": raw, "key": info["key"], "cluster": info["cluster"]})
    vc = var.groupby("key")["raw"].nunique()
    multi = vc[vc > 1].index
    if len(multi):
        sd_c = compute_sd(s.df, s.kwh_cols, *comp_p)
        vv = var[var["key"].isin(multi)].assign(sd=sd_c)
        det = vv.groupby(["cluster", "raw"]).agg(Baris=("sd", "size"), kWh=("sd", "sum")).reset_index()
        det.columns = ["Cluster (gabungan)", "Ejaan di file", "Jumlah baris", f"sd {period_name(*comp_p)}"]
        details["(6)  Variasi ejaan cluster"] = det
        rows.append({"Periode": period_name(*comp_p), "Alasan": REASONS["r6"], "Jumlah baris": int(len(det)),
                     "kWh terkait": float(det.iloc[:, -1].sum()), "Dampak ke selisih file−aplikasi": 0.0})
    else:
        rows.append({"Periode": period_name(*comp_p), "Alasan": REASONS["r6"], "Jumlah baris": 0,
                     "kWh terkait": 0.0, "Dampak ke selisih file−aplikasi": 0.0})
    pc = pd.concat(per_cluster, ignore_index=True).rename(columns={
        "cluster": "Cluster", "file": "File", "app": "Aplikasi", "pivot": "Pivot di file",
        "r1": "(1) sd≠ΣKWH", "r3": "(3) ganda", "r5": "(5) kosong→AP2T", "r8": "(8) ditimpa AP2T",
        "sisa": "Sisa"})
    if not s.pivot:
        notes.append("File database tidak memiliki tabel pivot berkolom sd; perbandingan pivot dilewati.")
    return Reconciliation(pd.DataFrame(rows), details, pc, pd.DataFrame(tot_rows), notes)
