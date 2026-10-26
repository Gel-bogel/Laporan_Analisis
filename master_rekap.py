"""Parser master rekap "DATA USAHA AGA & PP UP3 MDU REKAP ..." sheet KWH-MDU.

Aturan:
- Hanya blok "Gabungan <tahun>" dengan tahun >= config.MASTER_START_YEAR.
- Header bulan dibaca dari baris "TARIF"; scan berhenti di sel kosong pertama setelah TARIF
  (blok Pasca/Prabayar di kanan diabaikan).
- Baris dibaca sampai baris "JUMLAH" (grand total) lalu berhenti.
- Daftar & urutan jenis tarif diambil dari file.
- Sel berisi selain angka (teks, '-', #VALUE!) dibaca 0 (config.NON_NUMERIC_AS_ZERO). Bulan dianggap sudah berjalan bila grand total
  bulan itu terisi angka ≠ 0; sel tarif kosong pada bulan berjalan = 0.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config
from modules import data_loader
from modules.column_utils import count_non_numeric, is_error_cell, month_from_token, norm_text, to_num, to_period
from modules.tarif_utils import (clean_tarif_label, golongan_of, is_tarif_label, is_tt,
                                 jumlah_kind, tarif_key)


class MasterParseError(Exception):
    pass


@dataclass
class MasterResult:
    golongan: pd.DataFrame          # index Period, kolom S,R,B,I,P,L,TT,TOTAL
    tarif: pd.DataFrame             # long: period, year, month, tarif, key, golongan, tt, kwh
    tarif_order: List[str]          # urutan key tarif sesuai file
    tarif_labels: Dict[str, str]    # key → label tampil
    years: List[int]
    sheet: str
    warnings: List[str] = field(default_factory=list)
    errors_cells: int = 0

    @property
    def periods(self) -> List[pd.Period]:
        return list(self.golongan.index)


def _resolve_sheet(names: List[str]) -> Optional[str]:
    want = re.sub(r"\s+", "", config.MASTER_SHEET_NAME).upper()
    for n in names:
        if re.sub(r"\s+", "", n).upper() == want:
            return n
    return None


def parse_master(data: bytes, filename: str, sheet: Optional[str] = None) -> MasterResult:
    names = data_loader.sheet_names(data, filename)
    sheet = sheet or _resolve_sheet(names)
    if sheet is None:
        raise MasterParseError(f"Sheet '{config.MASTER_SHEET_NAME}' tidak ditemukan. Sheet tersedia: {names}")
    mat = data_loader.read_matrices(data, filename, sheets=[sheet], max_cols=config.MASTER_SCAN_MAX_COLS)[sheet]
    colA = [norm_text(v) for v in mat.iloc[:, 0].tolist()]
    block_rx = re.compile(config.MASTER_BLOCK_PATTERN, re.I)

    starts = []
    for i, v in enumerate(colA):
        m = block_rx.match(v)
        if m:
            starts.append((i, int(m.group(1))))
    starts = [(i, y) for i, y in starts if y >= config.MASTER_START_YEAR]
    if not starts:
        raise MasterParseError(f"Tidak ada tabel 'Gabungan <tahun>' mulai {config.MASTER_START_YEAR}.")

    warnings: List[str] = []
    long_rows, gol_rows = [], []
    order: List[str] = []
    labels: Dict[str, str] = {}
    n_err = 0
    for bi, (start, year) in enumerate(starts):
        # --- header bulan
        hdr = None
        for j in range(start + 1, min(start + 1 + config.MASTER_HEADER_SEARCH_ROWS, len(mat))):
            if colA[j] == config.MASTER_HEADER_LABEL:
                hdr = j
                break
        if hdr is None:
            warnings.append(f"Gabungan {year}: baris header '{config.MASTER_HEADER_LABEL}' tidak ditemukan; dilewati.")
            continue
        month_cols = {}
        for c in range(1, mat.shape[1]):
            v = mat.iat[hdr, c]
            if v is None or norm_text(v) == "":
                break                                   # sel kosong pertama → stop
            mth = month_from_token(v)
            if mth is None:
                break
            month_cols[mth] = c
        # --- baris data sampai JUMLAH
        tarif_vals, sub_vals, total_vals = [], {}, None
        next_start = starts[bi + 1][0] if bi + 1 < len(starts) else len(mat)
        for r in range(hdr + 1, next_start):
            label = mat.iat[r, 0]
            if label is None or norm_text(label) == "":
                continue
            raw = {m: mat.iat[r, c] for m, c in month_cols.items()}
            n_err += count_non_numeric(list(raw.values()))
            vals = {m: to_num(x) for m, x in raw.items()}
            jk = jumlah_kind(label)
            if jk == "TOTAL":
                total_vals = vals
                break                                   # data liar di bawah diabaikan
            if jk is not None:
                sub_vals[jk.lstrip("?")] = vals
                continue
            if not is_tarif_label(label):
                continue
            lab = clean_tarif_label(label)
            k = tarif_key(lab)
            if k not in labels:
                labels[k] = lab
                order.append(k)
            tarif_vals.append((lab, k, vals, raw))
        if total_vals is None:
            warnings.append(f"Gabungan {year}: baris 'JUMLAH' tidak ditemukan; blok dilewati.")
            continue
        for mth in sorted(month_cols):
            tot = total_vals.get(mth, np.nan)
            if not np.isfinite(tot) or tot == 0:
                continue                                # bulan belum berjalan / tidak tersedia
            p = to_period(year, mth)
            gl = {}
            tarif_kwh = {}
            for lab, k, vals, raw in tarif_vals:
                v = vals[mth]
                if np.isnan(v) and not is_error_cell(raw[mth]):
                    v = 0.0                             # kosong di bulan berjalan = 0
                tarif_kwh[k] = v
                long_rows.append({"period": p, "year": year, "month": mth, "tarif": labels[k], "key": k,
                                  "golongan": golongan_of(lab), "tt": is_tt(lab), "kwh": v})
            for g in config.GOLONGAN:
                if g == "L":
                    gl["L"] = float(np.nansum([v for k, v in tarif_kwh.items() if golongan_of(labels[k]) == "L"]))
                elif g in sub_vals:
                    gl[g] = sub_vals[g][mth]
                else:
                    gl[g] = float(np.nansum([v for k, v in tarif_kwh.items() if golongan_of(labels[k]) == g]))
            gl["TT"] = float(np.nansum([v for k, v in tarif_kwh.items() if is_tt(labels[k])]))
            gl["TOTAL"] = tot
            s = sum(gl[g] for g in config.GOLONGAN)
            if abs(s - tot) > config.TOTAL_TOLERANCE_KWH:
                warnings.append(f"{p}: S+R+B+I+P+L = {s:,.3f} ≠ JUMLAH {tot:,.3f} (selisih {s - tot:,.3f}).")
            gl["period"] = p
            gol_rows.append(gl)
    if not gol_rows:
        raise MasterParseError("Tidak ada bulan berisi data pada tabel Gabungan.")
    gdf = pd.DataFrame(gol_rows).set_index("period").sort_index()
    gdf = gdf[~gdf.index.duplicated(keep="last")]
    tdf = pd.DataFrame(long_rows)
    return MasterResult(golongan=gdf[config.GOLONGAN + ["TT", "TOTAL"]], tarif=tdf, tarif_order=order,
                        tarif_labels=labels, years=sorted({y for _, y in starts}), sheet=sheet,
                        warnings=warnings, errors_cells=n_err)
