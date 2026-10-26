"""Parser laporan bulanan CR_LAP_309_PUSATNEW (.pdf / .xlsx / .xls).

Keluaran `ReportResult`:
- period            : (tahun, bulan) dari teks "BULAN : <Nama> <Tahun>"
- tarif             : DataFrame [tarif, key, golongan, tt, pelanggan, daya, kwh] (urutan sesuai laporan)
- golongan          : DataFrame index [S,R,B,I,P,L,TT,TOTAL] kolom [pelanggan, daya, kwh]
- warnings          : daftar peringatan validasi
Kolom dicari lewat kode kolom ("1", "2", "3", "4=5+6") dan teks header, bukan posisi tetap.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

import config
from modules import data_loader
from modules.column_utils import nospace_key, norm_text, parse_period_text, to_num
from modules.tarif_utils import (clean_tarif_label, golongan_of, is_subrow, is_tarif_label,
                                 is_tt, jumlah_kind, tarif_key)


class AmbiguousSheetError(Exception):
    def __init__(self, candidates: List[str]):
        super().__init__("Sheet laporan ambigu: " + ", ".join(candidates))
        self.candidates = candidates


class ReportParseError(Exception):
    pass


@dataclass
class ReportResult:
    period: tuple
    tarif: pd.DataFrame
    golongan: pd.DataFrame
    warnings: List[str] = field(default_factory=list)
    source: str = ""
    sheet: Optional[str] = None


# --------------------------------------------------------------------------- inti tabel
def _find_code_row(rows: List[list]):
    """Cari baris kode kolom (berisi '4=5+6'). Kembalikan (idx_baris, idx_kolom_kwh)."""
    target = nospace_key(config.REPORT_CODE_KWH)
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            if nospace_key(data_loader.cell_text(v)) == target:
                return i, j
    return None, None


def _col_by_code(row: list, code: str) -> Optional[int]:
    for j, v in enumerate(row):
        if nospace_key(data_loader.cell_text(v)) == nospace_key(code):
            return j
    return None


def _col_by_header(rows: List[list], upto: int, text: str) -> Optional[int]:
    for i in range(upto):
        for j, v in enumerate(rows[i]):
            if norm_text(v) == norm_text(text):
                return j
    return None


def parse_report_rows(rows: List[list]) -> tuple:
    """Parse baris-baris tabel laporan (hasil PDF atau Excel) → (tarif_df, golongan_df, warnings)."""
    code_i, kwh_c = _find_code_row(rows)
    if code_i is None:
        raise ReportParseError(f"Kolom berkode '{config.REPORT_CODE_KWH}' tidak ditemukan.")
    code_row = rows[code_i]
    tarif_c = _col_by_code(code_row, config.REPORT_CODE_TARIF)
    if tarif_c is None:
        tarif_c = _col_by_header(rows, code_i, config.REPORT_TARIF_HEADER)
    if tarif_c is None:
        raise ReportParseError("Kolom TARIF tidak ditemukan.")
    plg_c = _col_by_code(code_row, config.REPORT_CODE_PELANGGAN)
    daya_c = _col_by_code(code_row, config.REPORT_CODE_DAYA)

    def val(r, c):
        return to_num(r[c]) if c is not None and c < len(r) else np.nan

    tarif_rows, subtotals, total = [], {}, None
    for r in rows[code_i + 1:]:
        if tarif_c >= len(r):
            continue
        label = r[tarif_c]
        if label is None or norm_text(label) == "" or is_subrow(label):
            continue
        jk = jumlah_kind(label)
        rec = {"pelanggan": val(r, plg_c), "daya": val(r, daya_c), "kwh": val(r, kwh_c)}
        if jk == "TOTAL":
            total = rec
            break
        if jk is not None:
            subtotals[jk.lstrip("?")] = rec
            continue
        if not is_tarif_label(label):
            continue
        lab = clean_tarif_label(label)
        tarif_rows.append({"tarif": lab, "key": tarif_key(lab), "golongan": golongan_of(lab),
                           "tt": is_tt(lab), **rec})
    if total is None:
        raise ReportParseError("Baris grand total 'JUMLAH' tidak ditemukan.")
    tdf = pd.DataFrame(tarif_rows)
    for c in ("pelanggan", "daya", "kwh"):
        tdf[c] = to_num(tdf[c]).fillna(0.0)
    warnings: List[str] = []
    gol = {}
    for g in config.GOLONGAN:
        if g == "L":
            part = tdf[tdf["golongan"] == "L"]
            gol["L"] = {c: part[c].sum() for c in ("pelanggan", "daya", "kwh")}
            continue
        if g in subtotals:
            gol[g] = subtotals[g]
            part = tdf[tdf["golongan"] == g]
            if abs(part["kwh"].sum() - to_num(subtotals[g]["kwh"])) > config.TOTAL_TOLERANCE_KWH:
                warnings.append(f"JUMLAH {g} ({subtotals[g]['kwh']:,.3f}) ≠ jumlah baris tarif {g} "
                                f"({part['kwh'].sum():,.3f}).")
        else:
            part = tdf[tdf["golongan"] == g]
            gol[g] = {c: part[c].sum() for c in ("pelanggan", "daya", "kwh")}
            warnings.append(f"Baris 'JUMLAH {g}' tidak ada; dihitung dari baris tarif.")
    tt = tdf[tdf["tt"]]
    gol["TT"] = {c: tt[c].sum() for c in ("pelanggan", "daya", "kwh")}
    gol["TOTAL"] = total
    gdf = pd.DataFrame(gol).T[["pelanggan", "daya", "kwh"]].apply(to_num)
    s = gdf.loc[config.GOLONGAN, "kwh"].sum()
    if abs(s - gdf.loc["TOTAL", "kwh"]) > config.TOTAL_TOLERANCE_KWH:
        warnings.append(f"Validasi gagal: S+R+B+I+P+L = {s:,.3f} ≠ JUMLAH = {gdf.loc['TOTAL', 'kwh']:,.3f} "
                        f"(selisih {s - gdf.loc['TOTAL', 'kwh']:,.3f}).")
    return tdf, gdf, warnings


# --------------------------------------------------------------------------- PDF
def _parse_pdf(data: bytes) -> ReportResult:
    import pdfplumber
    rows, text = [], ""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
            for t in page.extract_tables():
                rows.extend([list(r) for r in t])
    period = parse_period_text(text)
    if period is None:
        raise ReportParseError("Teks 'BULAN : <Nama> <Tahun>' tidak ditemukan di PDF.")
    tdf, gdf, w = parse_report_rows(rows)
    return ReportResult(period, tdf, gdf, w, source="pdf")


# --------------------------------------------------------------------------- Excel
def _matrix_rows(mat: pd.DataFrame) -> List[list]:
    return [[None if (isinstance(v, float) and np.isnan(v)) else v for v in r] for r in mat.values.tolist()]


def _has_code(mat: pd.DataFrame) -> bool:
    return _find_code_row(_matrix_rows(mat))[0] is not None


def _period_in_matrix(mat: pd.DataFrame) -> Optional[tuple]:
    for r in _matrix_rows(mat)[:60]:
        line = " ".join(data_loader.cell_text(v) for v in r if v is not None)
        p = parse_period_text(line)
        if p:
            return p
    return None


def _parse_excel(data: bytes, filename: str, sheet: Optional[str]) -> ReportResult:
    mats = data_loader.read_matrices(data, filename)
    if sheet is None:
        candidates = [n for n, m in mats.items() if _has_code(m)]
        if not candidates:
            raise ReportParseError(f"Tidak ada sheet berisi kolom '{config.REPORT_CODE_KWH}'.")
        if len(candidates) == 1:
            sheet = candidates[0]
        else:
            hinted = [n for n in candidates if config.REPORT_SHEET_HINT.upper() in n.upper()]
            if len(hinted) == 1:
                sheet = hinted[0]
            else:
                raise AmbiguousSheetError(hinted or candidates)
    mat = mats[sheet]
    period = _period_in_matrix(mat)
    if period is None:
        for m in mats.values():
            period = _period_in_matrix(m)
            if period:
                break
    if period is None:
        raise ReportParseError("Teks 'BULAN : <Nama> <Tahun>' tidak ditemukan di file Excel.")
    tdf, gdf, w = parse_report_rows(_matrix_rows(mat))
    return ReportResult(period, tdf, gdf, w, source="excel", sheet=sheet)


def parse_report(data: bytes, filename: str, sheet: Optional[str] = None) -> ReportResult:
    ext = data_loader.ext_of(filename)
    if ext == ".pdf":
        return _parse_pdf(data)
    if ext in (".xlsx", ".xlsm", ".xls"):
        return _parse_excel(data, filename, sheet)
    raise ReportParseError(f"Format {ext} tidak didukung (pakai .pdf/.xlsx/.xls).")
