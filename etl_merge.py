"""ETL: transaksi AP2T → database klaster I3I2B2 (sheet DB I & DB B).

- parse_ap2t : baca "LAPORAN DETIL TARIF I3 I4 DAN B3"; kolom dicari lewat teks header.
- load_cluster_db : baca DB I / DB B (+ pivot bila ada) tanpa memakai kolom sd dari file.
- run_etl : isi kolom KWH bulan AP2T berdasarkan IDPEL, hitung ulang sd, laporan kecocokan.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config
from modules import data_loader
from modules.column_utils import (canon_col, count_non_numeric, find_col, norm_text, normalize_cluster, normalize_idpel,
                                  parse_period_col, parse_period_text, period_name, to_num)


class Ap2tParseError(Exception):
    pass


# =========================================================================== AP2T
@dataclass
class Ap2tResult:
    df: pd.DataFrame                  # IDPEL, NAMA PELANGGAN, KODE KEPERLUAN, KEPERLUAN, TARIF, KWH
    period: Tuple[int, int]
    total_row_kwh: float              # angka baris TOTAL di file (untuk verifikasi)
    duplicates: pd.DataFrame
    warnings: List[str] = field(default_factory=list)


def _find_header_cells(mat: pd.DataFrame):
    """Kembalikan {nama_kolom: (baris, kolom)} dan posisi kolom JUMLAH kWh."""
    nrows = min(len(mat), config.AP2T_HEADER_SEARCH_ROWS)
    found: Dict[str, Tuple[int, int]] = {}
    group_cells, jumlah_cells, other_groups = [], [], []
    for r in range(nrows):
        for c in range(mat.shape[1]):
            t = norm_text(data_loader.cell_text(mat.iat[r, c]))
            if not t:
                continue
            for key, pat in config.AP2T_HEADER_PATTERNS.items():
                if key not in found and re.search(pat, t):
                    found[key] = (r, c)
            if re.search(config.AP2T_KWH_GROUP_PATTERN, t):
                group_cells.append((r, c))
            elif re.search(config.AP2T_KWH_SUBHEADER_PATTERN, t):
                jumlah_cells.append((r, c))
            elif r < nrows and len(t) > 6 and c > 0:
                other_groups.append((r, c))
    if not group_cells:
        raise Ap2tParseError("Header grup 'PEMAKAIAN KWH' tidak ditemukan.")
    gr, gc = group_cells[0]
    # batas kanan grup = header grup lain di baris yang sama, di kanan gc
    right = [c for r, c in other_groups if r == gr and c > gc]
    limit = min(right) if right else mat.shape[1]
    cands = [(r, c) for r, c in jumlah_cells if r > gr and gc <= c < limit]
    if not cands:
        raise Ap2tParseError("Sel 'JUMLAH' di bawah 'PEMAKAIAN KWH' tidak ditemukan.")
    kwh_rc = sorted(cands, key=lambda x: (x[1], x[0]))[0]
    missing = [k for k in ("IDPEL", "TARIF") if k not in found]
    if missing:
        raise Ap2tParseError(f"Header wajib tidak ditemukan: {missing}")
    return found, kwh_rc


def parse_ap2t(data: bytes, filename: str) -> Ap2tResult:
    mats = data_loader.read_matrices(data, filename)
    last_err = None
    for sheet, mat in mats.items():
        try:
            found, kwh_rc = _find_header_cells(mat)
        except Ap2tParseError as e:
            last_err = e
            continue
        warnings = []
        header_bottom = max([r for r, _ in found.values()] + [kwh_rc[0]])
        id_c = found["IDPEL"][1]
        rows, total_kwh = [], np.nan
        started = False
        n_txt = 0
        for r in range(header_bottom + 1, len(mat)):
            first_texts = [norm_text(data_loader.cell_text(mat.iat[r, c])) for c in range(min(mat.shape[1], id_c + 1))]
            if any(re.search(config.AP2T_TOTAL_PATTERN, t) for t in first_texts if t):
                total_kwh = to_num(mat.iat[r, kwh_rc[1]])
                break
            idp = normalize_idpel(mat.iat[r, id_c])
            if len(idp) < config.IDPEL_MIN_DIGITS:
                if started and all(mat.iat[r, c] is None for c in range(mat.shape[1])):
                    continue
                continue
            started = True
            kraw = mat.iat[r, kwh_rc[1]]
            if count_non_numeric([kraw]):
                n_txt += 1
            rec = {"IDPEL": idp, "KWH": to_num(kraw)}
            for key in ("NAMA PELANGGAN", "KODE KEPERLUAN", "KEPERLUAN", "TARIF", "THBLLAP"):
                if key in found:
                    rec[key] = data_loader.cell_text(mat.iat[r, found[key][1]]).strip()
            rows.append(rec)
        if not rows:
            last_err = Ap2tParseError("Tidak ada baris data IDPEL.")
            continue
        df = pd.DataFrame(rows)
        if n_txt:
            warnings.append(f"{n_txt} sel kWh AP2T berisi data selain angka; dibaca sebagai 0.")
        for k in ("NAMA PELANGGAN", "KODE KEPERLUAN", "KEPERLUAN", "TARIF"):
            if k not in df:
                df[k] = ""
                warnings.append(f"Kolom '{k}' tidak ditemukan di file AP2T.")
        df["TARIF"] = df["TARIF"].map(norm_text)
        # --- periode
        period = None
        if "THBLLAP" in df:
            vals = df["THBLLAP"].dropna().unique()
            for v in vals:
                m = re.match(config.THBL_PATTERN, str(v).strip())
                if m:
                    period = (int(m.group(1)), int(m.group(2)))
                    break
            if len(vals) > 1:
                warnings.append(f"THBLLAP berisi lebih dari satu periode: {list(vals)}")
        if period is None:
            text = " ".join(data_loader.cell_text(v) for v in mat.iloc[:header_bottom + 1].values.ravel() if v is not None)
            period = parse_period_text(text)
        if period is None:
            raise Ap2tParseError("Periode tidak ditemukan (THBLLAP maupun 'BULAN : ...').")
        dup = df[df["IDPEL"].duplicated(keep=False)].copy()
        if len(dup):
            warnings.append(f"{dup['IDPEL'].nunique()} IDPEL muncul lebih dari sekali di AP2T; kWh dijumlahkan.")
        cols = ["IDPEL", "NAMA PELANGGAN", "KODE KEPERLUAN", "KEPERLUAN", "TARIF", "KWH"]
        if np.isfinite(total_kwh) and abs(df["KWH"].sum() - total_kwh) > config.TOTAL_TOLERANCE_KWH:
            warnings.append(f"Total kWh terbaca {df['KWH'].sum():,.0f} ≠ baris TOTAL {total_kwh:,.0f}.")
        return Ap2tResult(df[cols], period, total_kwh, dup[cols], warnings)
    raise Ap2tParseError(str(last_err) if last_err else "File AP2T tidak dapat dibaca.")


def ap2t_aggregated(ap: Ap2tResult) -> pd.DataFrame:
    """Satu baris per IDPEL (kWh dijumlah bila ganda)."""
    g = ap.df.groupby("IDPEL", sort=False)
    out = g.agg({"NAMA PELANGGAN": "first", "KODE KEPERLUAN": "first", "KEPERLUAN": "first",
                 "TARIF": "first", "KWH": "sum"}).reset_index()
    return out


# =========================================================================== Database klaster
@dataclass
class DbSheet:
    name: str                          # "DB I" / "DB B"
    sheet: str                         # nama sheet asli di file
    df: pd.DataFrame                   # tabel mentah (kolom asli)
    idpel_col: str
    cluster_col: Optional[str]
    nama_col: Optional[str]
    kwh_cols: Dict[Tuple[int, int], str]   # (tahun, bulan) → nama kolom KWH
    sd_cols: Dict[Tuple[int, int], str]    # kolom sd di file (HANYA untuk rekonsiliasi)
    pivot: Dict[Tuple[int, int], pd.Series] = field(default_factory=dict)  # sd per cluster dari pivot
    pivot_labels: Dict[Tuple[int, int], pd.Series] = field(default_factory=dict)


@dataclass
class ClusterDb:
    sheets: Dict[str, DbSheet]
    warnings: List[str] = field(default_factory=list)


def _period_cols(columns, kind):
    out = {}
    for c in columns:
        p = parse_period_col(c)
        if p and p[0] == kind:
            out.setdefault((p[1], p[2]), c)
    return out


def _header_row(mat: pd.DataFrame) -> Optional[int]:
    for r in range(min(len(mat), config.DB_HEADER_SEARCH_ROWS)):
        for v in mat.iloc[r].tolist():
            if re.search(config.DB_IDPEL_PATTERN, norm_text(data_loader.cell_text(v)), re.I):
                return r
    return None


def _parse_pivots(mats: Dict[str, pd.DataFrame], skip: List[str]):
    """Temukan tabel pivot (Row Labels | Sum of sd...) → list of (labels, {periode: Series})."""
    found = []
    for name, mat in mats.items():
        if name in skip:
            continue
        for r in range(len(mat)):
            for c in range(mat.shape[1]):
                t = str(mat.iat[r, c]).strip().lower() if mat.iat[r, c] is not None else ""
                if not any(re.match(p, t) for p in config.PIVOT_ROW_LABEL_PATTERNS):
                    continue
                cols = {}
                for cc in range(c + 1, mat.shape[1]):
                    h = mat.iat[r, cc]
                    if h is None:
                        break
                    hname = re.sub(config.PIVOT_VALUE_PREFIX_PATTERN, "", str(h).strip(), flags=re.I)
                    p = parse_period_col(hname)
                    if p and p[0] == "SD":
                        cols.setdefault((p[1], p[2]), cc)
                if not cols:
                    continue
                labels, vals = [], {k: [] for k in cols}
                for rr in range(r + 1, len(mat)):
                    lab = mat.iat[rr, c]
                    if lab is None or str(lab).strip() == "":
                        break
                    if any(re.match(p, str(lab).strip().lower()) for p in config.PIVOT_GRAND_TOTAL_PATTERNS):
                        continue
                    labels.append(str(lab))
                    for k, cc in cols.items():
                        vals[k].append(to_num(mat.iat[rr, cc]))
                found.append((labels, {k: pd.Series(v, index=labels) for k, v in vals.items()}))
    return found


def load_cluster_db(data: bytes, filename: str) -> ClusterDb:
    mats = data_loader.read_matrices(data, filename)
    sheets, warnings = {}, []
    used = []
    for key, spec in config.DB_SHEETS.items():
        sname = next((n for n in mats if re.match(spec["sheet_pattern"], n.strip(), re.I)), None)
        if sname is None:
            warnings.append(f"Sheet '{key}' tidak ditemukan di database klaster.")
            continue
        used.append(sname)
        mat = mats[sname]
        hr = _header_row(mat)
        if hr is None:
            warnings.append(f"Sheet '{sname}': header IDPEL tidak ditemukan.")
            continue
        df = data_loader.matrix_to_table(mat, hr)
        idc = find_col(df.columns, config.DB_IDPEL_PATTERN)
        df = df[df[idc].map(normalize_idpel).str.len() > 0].reset_index(drop=True)
        kc = list(_period_cols(df.columns, "KWH").values())
        nn = count_non_numeric(df[kc]) if kc else 0
        if nn:
            warnings.append(f"Sheet '{sname}': {nn} sel kolom KWH berisi data selain angka (mis. '-', teks) "
                            f"dibaca sebagai 0.")
        clc = find_col(df.columns, config.DB_CLUSTER_PATTERNS)
        if clc is None:
            warnings.append(f"Sheet '{sname}': kolom Cluster tidak ditemukan.")
        sheets[key] = DbSheet(name=key, sheet=sname, df=df, idpel_col=idc, cluster_col=clc,
                              nama_col=find_col(df.columns, config.DB_NAMA_PATTERN),
                              kwh_cols=_period_cols(df.columns, "KWH"), sd_cols=_period_cols(df.columns, "SD"))
    # pivot → cocokkan ke sheet berdasarkan kesamaan label cluster
    for labels, series in _parse_pivots(mats, used):
        keys = {normalize_cluster(x) for x in labels}
        best, score = None, 0
        for k, s in sheets.items():
            if s.cluster_col is None:
                continue
            dbk = set(s.df[s.cluster_col].map(normalize_cluster))
            sc = len(keys & dbk) / max(len(keys), 1)
            if sc > score:
                best, score = k, sc
        if best is None or score < 0.5:
            continue
        for per, ser in series.items():
            if per not in sheets[best].pivot:                    # tabel pivot pertama yang dipakai
                sheets[best].pivot_labels[per] = ser
                sheets[best].pivot[per] = ser.groupby(ser.index.map(normalize_cluster)).sum()
    return ClusterDb(sheets, warnings)


# =========================================================================== sd & ETL
def sd_columns_for(kwh_cols: Dict[Tuple[int, int], str], year: int, month: int) -> Tuple[List[str], List[int]]:
    """Kolom KWH Jan..month pada tahun `year` dan daftar bulan yang tidak ada kolomnya."""
    cols, missing = [], []
    for m in range(1, int(month) + 1):
        c = kwh_cols.get((int(year), m))
        if c is None:
            missing.append(m)
        else:
            cols.append(c)
    return cols, missing


def compute_sd(df: pd.DataFrame, kwh_cols: Dict[Tuple[int, int], str], year: int, month: int) -> pd.Series:
    """sd<BULAN><TAHUN> = Σ KWH Januari..bulan (dihitung aplikasi; kolom sd file tidak dipakai)."""
    cols, _ = sd_columns_for(kwh_cols, year, month)
    if not cols:
        return pd.Series(np.nan, index=df.index)
    return to_num(df[cols]).fillna(0.0).sum(axis=1)


@dataclass
class EtlSheetResult:
    name: str
    df: pd.DataFrame                   # database setelah diisi (kolom asli + kolom baru)
    df_before: pd.DataFrame            # database mentah (untuk rekonsiliasi)
    kwh_cols: Dict[Tuple[int, int], str]
    sd_cols_file: Dict[Tuple[int, int], str]
    idpel_col: str
    cluster_col: Optional[str]
    nama_col: Optional[str]
    target_col: str
    created_col: bool
    filled_rows: int
    matched_idpel: int
    new_customers: pd.DataFrame        # IDPEL AP2T yang tidak ada di database
    db_duplicates: pd.DataFrame        # IDPEL ganda di database
    not_in_ap2t: pd.DataFrame          # pelanggan database yang tidak ada di AP2T bulan itu
    ap2t_rows: int
    ap2t_kwh: float
    pivot: Dict[Tuple[int, int], pd.Series] = field(default_factory=dict)
    pivot_labels: Dict[Tuple[int, int], pd.Series] = field(default_factory=dict)


@dataclass
class EtlResult:
    period: Tuple[int, int]
    sheets: Dict[str, EtlSheetResult]
    unrouted: pd.DataFrame             # baris AP2T dengan awalan tarif yang tidak dirutekan
    warnings: List[str] = field(default_factory=list)


def _merge_sheet(db: DbSheet, ap_part: pd.DataFrame, year: int, month: int) -> EtlSheetResult:
    df = db.df.copy()
    ids = df[db.idpel_col].map(normalize_idpel)
    kwh_cols = dict(db.kwh_cols)
    created = False
    col = kwh_cols.get((year, month))
    if col is None:
        col = canon_col("KWH", year, month)
        existing = [c for c in df.columns if parse_period_col(c) and parse_period_col(c)[0] == "KWH"]
        pos = (list(df.columns).index(existing[-1]) + 1) if existing else len(df.columns)
        df.insert(pos, col, np.nan)                            # kolom baru diisi np.nan
        kwh_cols[(year, month)] = col
        created = True
    df[col] = to_num(df[col])
    ap_map = ap_part.set_index("IDPEL")["KWH"]
    matched = ids.isin(ap_map.index)
    df.loc[matched, col] = ids[matched].map(ap_map).astype(float).values
    # kolom sd dihitung ulang (kolom sd file ditimpa hasil hitungan; kolom baru ditambahkan)
    for (y, m) in sorted({(year, month), (year - 1, month)} | set(db.sd_cols)):
        cols, _ = sd_columns_for(kwh_cols, y, m)
        if not cols:
            continue
        name = db.sd_cols.get((y, m)) or canon_col("SD", y, m)
        df[name] = compute_sd(df, kwh_cols, y, m)
    dup_mask = ids.duplicated(keep=False)
    keep = [c for c in [db.idpel_col, db.nama_col, db.cluster_col] if c]
    new_c = ap_part[~ap_part["IDPEL"].isin(set(ids))].copy()
    not_in = df.loc[~matched, keep + [col]].copy()
    return EtlSheetResult(
        name=db.name, df=df, df_before=db.df.copy(), kwh_cols=kwh_cols, sd_cols_file=dict(db.sd_cols),
        idpel_col=db.idpel_col, cluster_col=db.cluster_col, nama_col=db.nama_col, target_col=col,
        created_col=created, filled_rows=int(matched.sum()), matched_idpel=int(ids[matched].nunique()),
        new_customers=new_c, db_duplicates=df.loc[dup_mask, keep].assign(_IDPEL_norm=ids[dup_mask]),
        not_in_ap2t=not_in, ap2t_rows=len(ap_part), ap2t_kwh=float(ap_part["KWH"].sum()),
        pivot=dict(db.pivot), pivot_labels=dict(db.pivot_labels))


def run_etl(cdb: ClusterDb, ap: Ap2tResult) -> EtlResult:
    year, month = ap.period
    agg = ap2t_aggregated(ap)
    out, warnings = {}, []
    routed = pd.Series(False, index=agg.index)
    for key, spec in config.DB_SHEETS.items():
        mask = agg["TARIF"].str.upper().str.startswith(spec["tarif_prefix"].upper())
        routed |= mask
        if key not in cdb.sheets:
            warnings.append(f"{key} tidak tersedia; {int(mask.sum())} baris AP2T tarif "
                            f"{spec['tarif_prefix']}* tidak diproses.")
            continue
        out[key] = _merge_sheet(cdb.sheets[key], agg[mask].reset_index(drop=True), year, month)
    unrouted = agg[~routed]
    if len(unrouted):
        warnings.append(f"{len(unrouted)} baris AP2T bertarif selain awalan yang dirutekan.")
    return EtlResult((year, month), out, unrouted, warnings)


def db_only_result(cdb: ClusterDb) -> EtlResult:
    """Tanpa AP2T: database dipakai apa adanya (bulan terbaru = kolom KWH terakhir)."""
    out, period = {}, None
    for key, db in cdb.sheets.items():
        if not db.kwh_cols:
            continue
        last = max(db.kwh_cols)
        period = max(period, last) if period else last
        empty_ap = pd.DataFrame(columns=["IDPEL", "NAMA PELANGGAN", "KODE KEPERLUAN", "KEPERLUAN", "TARIF", "KWH"])
        keep = [c for c in [db.idpel_col, db.nama_col, db.cluster_col] if c]
        out[key] = EtlSheetResult(
            name=key, df=db.df.copy(), df_before=db.df.copy(), kwh_cols=dict(db.kwh_cols),
            sd_cols_file=dict(db.sd_cols), idpel_col=db.idpel_col, cluster_col=db.cluster_col,
            nama_col=db.nama_col, target_col=db.kwh_cols[last], created_col=False, filled_rows=0,
            matched_idpel=0, new_customers=empty_ap, db_duplicates=db.df.loc[
                db.df[db.idpel_col].map(normalize_idpel).duplicated(keep=False), keep],
            not_in_ap2t=db.df.iloc[0:0][keep + [db.kwh_cols[last]]], ap2t_rows=0, ap2t_kwh=0.0,
            pivot=dict(db.pivot), pivot_labels=dict(db.pivot_labels))
    return EtlResult(period, out, pd.DataFrame(), ["AP2T belum diunggah: database dipakai apa adanya."])


def etl_to_excel(res: EtlResult) -> bytes:
    buf = io.BytesIO()
    y, m = res.period
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summary = []
        for key, s in res.sheets.items():
            s.df.to_excel(xw, sheet_name=key[:31], index=False)
            summary.append({"Sheet": key, "Kolom diisi": s.target_col,
                            "Kolom baru?": "Ya" if s.created_col else "Tidak (dipakai ulang)",
                            "Baris AP2T": s.ap2t_rows, "kWh AP2T": s.ap2t_kwh,
                            "Baris database terisi": s.filled_rows,
                            "IDPEL cocok": s.matched_idpel,
                            "Pelanggan baru (tidak ada di DB)": len(s.new_customers),
                            "Baris IDPEL ganda di DB": len(s.db_duplicates),
                            "Pelanggan DB tidak ada di AP2T": len(s.not_in_ap2t)})
        pd.DataFrame(summary).to_excel(xw, sheet_name="Ringkasan ETL", index=False)
        for key, s in res.sheets.items():
            tag = key.replace(" ", "")
            s.new_customers.to_excel(xw, sheet_name=f"Baru {tag}"[:31], index=False)
            s.db_duplicates.to_excel(xw, sheet_name=f"Ganda {tag}"[:31], index=False)
            s.not_in_ap2t.to_excel(xw, sheet_name=f"Tidak di AP2T {tag}"[:31], index=False)
        if len(res.unrouted):
            res.unrouted.to_excel(xw, sheet_name="AP2T tidak dirutekan", index=False)
    return buf.getvalue()


def etl_filename(res: EtlResult) -> str:
    y, m = res.period
    return f"I3I2B2_hasil_ETL_{period_name(y, m).replace(' ', '_')}.xlsx"
