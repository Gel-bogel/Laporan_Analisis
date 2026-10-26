"""Utilitas teks, angka, periode, dan nama kolom (tanpa angka bisnis)."""
from __future__ import annotations

import math
import re
from typing import Iterable, Optional

import numpy as np
import pandas as pd

import config


# --------------------------------------------------------------------------- angka
def _clean_scalar(x):
    """Sel kosong (pd.NA/None/NaN/'') → np.nan. Sel error Excel ('#VALUE!', '#N/A', ...) → 0 bila
    config.NON_NUMERIC_AS_ZERO, selain itu np.nan."""
    if x is None or x is pd.NA or x is pd.NaT:
        return np.nan
    if isinstance(x, float) and math.isnan(x):
        return np.nan
    if isinstance(x, str):
        s = x.strip()
        if s == "":
            return np.nan
        if s.startswith("#"):                     # "#VALUE!", "#DIV/0!", "#N/A", "#ERR"
            return 0.0 if config.NON_NUMERIC_AS_ZERO else np.nan
        return s
    return x


def parse_number_text(s: str) -> float:
    """Angka teks gaya laporan: '1,679,038,400' atau '281,990,380.991'."""
    t = s.replace(" ", "").replace(config.REPORT_THOUSANDS_SEP, "")
    if config.REPORT_DECIMAL_SEP != ".":
        t = t.replace(config.REPORT_DECIMAL_SEP, ".")
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        # data selain angka ('-', 'nihil', 'x', ...) → 0 (config.NON_NUMERIC_AS_ZERO)
        return 0.0 if config.NON_NUMERIC_AS_ZERO else np.nan
    return -v if neg else v


def to_num(obj):
    """Konversi aman ke numerik.

    - sel kosong (pd.NA/None/NaN/'') → np.nan (artinya "tidak ada data"; tiap menu memutuskan
      apakah ditampilkan 0 atau '–');
    - sel berisi data selain angka ('-', teks, '#VALUE!') → 0 bila config.NON_NUMERIC_AS_ZERO.
    Menerima skalar, list, Series, atau DataFrame.
    """
    if isinstance(obj, pd.DataFrame):
        return obj.apply(to_num)
    if isinstance(obj, pd.Series):
        cleaned = obj.astype(object).map(_clean_scalar)
        cleaned = cleaned.map(lambda v: parse_number_text(v) if isinstance(v, str) else v)
        out = pd.to_numeric(cleaned, errors="coerce").astype(float)
        if config.NON_NUMERIC_AS_ZERO:                 # objek lain yang bukan angka (tanggal, dll.)
            out = out.where(out.notna() | cleaned.isna(), 0.0)
        return out
    if isinstance(obj, (list, tuple, np.ndarray)):
        return to_num(pd.Series(list(obj))).to_numpy()
    v = _clean_scalar(obj)
    if isinstance(v, float) and math.isnan(v):
        return np.nan                                  # kosong tetap "tidak ada data"
    if isinstance(v, str):
        return parse_number_text(v)
    if isinstance(v, (bool, np.bool_)):
        return float(v)
    try:
        out = float(pd.to_numeric(v, errors="coerce"))
    except (TypeError, ValueError):
        out = np.nan
    if np.isnan(out) and config.NON_NUMERIC_AS_ZERO:
        return 0.0
    return out


def count_non_numeric(obj) -> int:
    """Jumlah sel yang TIDAK kosong tetapi bukan angka (teks, '-', '#VALUE!', ...)."""
    if isinstance(obj, pd.DataFrame):
        return int(sum(count_non_numeric(obj[c]) for c in obj.columns))
    ser = pd.Series(obj).astype(object)

    def bad(v):
        if v is None or v is pd.NA or (isinstance(v, float) and math.isnan(v)):
            return False
        if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
            return False
        if isinstance(v, str):
            t = v.strip()
            if t == "":
                return False
            if t.startswith("#"):
                return True
            t = t.replace(" ", "").replace(config.REPORT_THOUSANDS_SEP, "").strip("()")
            try:
                float(t if config.REPORT_DECIMAL_SEP == "." else t.replace(config.REPORT_DECIMAL_SEP, "."))
                return False
            except ValueError:
                return True
        return True
    return int(ser.map(bad).sum())


def is_error_cell(x) -> bool:
    return isinstance(x, str) and x.strip().startswith("#")


# --------------------------------------------------------------------------- teks
def norm_text(x) -> str:
    """Huruf besar, spasi tunggal, tanpa spasi tepi. None → ''."""
    if x is None or (isinstance(x, float) and math.isnan(x)) or x is pd.NA:
        return ""
    return re.sub(r"\s+", " ", str(x)).strip().upper()


def nospace_key(x) -> str:
    return re.sub(r"\s+", "", norm_text(x))


def normalize_cluster(x) -> str:
    """Kunci cluster: tanpa peduli huruf besar/kecil & spasi ganda (seperti pivot Excel)."""
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return ""
    return re.sub(r"\s+", " ", str(x)).strip().casefold()


def normalize_idpel(x) -> str:
    """IDPEL → string digit saja (buang '.0', spasi, karakter non-digit)."""
    if x is None or x is pd.NA:
        return ""
    if isinstance(x, float):
        if math.isnan(x):
            return ""
        if x.is_integer():
            return str(int(x))
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    s = str(x).strip()
    s = re.sub(r"\.0+$", "", s)
    if re.fullmatch(r"\d+(\.\d+)?[eE]\+?\d+", s):          # notasi ilmiah dari Excel
        try:
            s = str(int(float(s)))
        except ValueError:
            pass
    return re.sub(r"\D", "", s)


def find_col(columns: Iterable, patterns, exclude=()) -> Optional[str]:
    """Cari nama kolom pertama yang cocok dengan salah satu regex (case-insensitive)."""
    if isinstance(patterns, str):
        patterns = [patterns]
    cols = list(columns)
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for c in cols:
            if c in exclude:
                continue
            if rx.search(re.sub(r"\s+", " ", str(c)).strip()):
                return c
    return None


# --------------------------------------------------------------------------- bulan & periode
_ALIAS_TO_MONTH = {a: m for m, aliases in config.MONTH_ALIASES.items() for a in aliases}


def month_from_token(tok) -> Optional[int]:
    t = norm_text(tok).replace(".", "")
    if not t:
        return None
    if t in _ALIAS_TO_MONTH:
        return _ALIAS_TO_MONTH[t]
    if len(t) >= 3:
        hits = {m for a, m in _ALIAS_TO_MONTH.items() if a.startswith(t) or t.startswith(a)}
        if len(hits) == 1:
            return hits.pop()
    return None


def year_from_token(tok: str) -> Optional[int]:
    t = str(tok).strip()
    if re.fullmatch(r"\d{4}", t):
        return int(t)
    if re.fullmatch(r"\d{2}", t):
        return config.YEAR_2DIGIT_BASE + int(t)
    return None


_PERIOD_COL_RX = re.compile(r"^\s*(KWH|SD)\s*[_\-\s]*\s*([A-Za-z]+)\s*[_\-\s]*(\d{4}|\d{2})\s*$", re.I)


def parse_period_col(name) -> Optional[tuple]:
    """'KWH_AUG2026' / 'KWH_JUNI25' / 'sd JUL2026' / 'sdJUl26' → ('KWH'|'SD', tahun, bulan)."""
    if name is None:
        return None
    m = _PERIOD_COL_RX.match(str(name))
    if not m:
        return None
    kind = m.group(1).upper()
    month = month_from_token(m.group(2))
    year = year_from_token(m.group(3))
    if month is None or year is None:
        return None
    return kind, year, month


def canon_col(kind: str, year: int, month: int) -> str:
    prefix = config.CANON_KWH_PREFIX if kind.upper() == "KWH" else config.CANON_SD_PREFIX
    return f"{prefix}{config.CANON_MONTH_ABBR[int(month)]}{int(year)}"


def parse_period_text(text: str) -> Optional[tuple]:
    """Cari 'BULAN : <NamaBulan> <Tahun>' dalam teks → (tahun, bulan)."""
    if not text:
        return None
    for m in re.finditer(config.PERIOD_TEXT_PATTERN, str(text), re.I):
        month = month_from_token(m.group(1))
        if month:
            return int(m.group(2)), month
    return None


def period_label(year, month) -> str:
    return f"{int(year)}-{int(month):02d}"


def period_name(year, month) -> str:
    return f"{config.MONTH_NAME_ID[int(month)]} {int(year)}"


def to_period(year, month) -> pd.Period:
    return pd.Period(year=int(year), month=int(month), freq="M")


def fmt_id(x, dec: int = 0) -> str:
    """Format angka gaya Indonesia (1.234.567,8). NaN → '–'."""
    v = to_num(x)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    s = f"{v:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_pct(x, dec: int = 2) -> str:
    v = to_num(x)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    return fmt_id(v, dec) + "%"
