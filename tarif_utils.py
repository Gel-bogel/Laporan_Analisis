"""Aturan label tarif & golongan (dipakai parser laporan dan master)."""
from __future__ import annotations

import re
from typing import Optional

import config
from modules.column_utils import norm_text, nospace_key

_TARIF_RX = re.compile(config.TARIF_LABEL_PATTERN)
_TT_RX = re.compile(config.TT_TARIF_PATTERN)
_TRAIL_RX = re.compile(config.TRAILING_MARK_PATTERN)


def clean_tarif_label(label) -> str:
    """Spasi tunggal + buang penanda ' I' di akhir ('S.1 / 450 VA I' → 'S.1 / 450 VA')."""
    s = re.sub(r"\s+", " ", str(label or "")).strip()
    return _TRAIL_RX.sub("", s).strip()


def tarif_key(label) -> str:
    """Kunci pencocokan tarif antar sumber: huruf besar tanpa spasi."""
    return nospace_key(clean_tarif_label(label))


def is_subrow(label) -> bool:
    return norm_text(label) in config.SUBROW_LABELS


def is_tarif_label(label) -> bool:
    s = norm_text(clean_tarif_label(label))
    if not s or s.startswith(config.JUMLAH_LABEL) or is_subrow(s):
        return False
    return bool(_TARIF_RX.match(s))


def jumlah_kind(label) -> Optional[str]:
    """'JUMLAH S' → 'S'; 'JUMLAH' → 'TOTAL'; selain itu None."""
    s = norm_text(label)
    if not s.startswith(config.JUMLAH_LABEL):
        return None
    rest = s[len(config.JUMLAH_LABEL):].strip()
    if rest == "":
        return "TOTAL"
    return rest if rest in config.GOLONGAN else f"?{rest}"


def tarif_prefix(label) -> str:
    """Huruf awal tarif sebelum '.' atau '/': 'R.1M / 900 VA' → 'R', 'C / TR' → 'C'."""
    k = tarif_key(label)
    m = re.match(r"^([A-Z]+)", k)
    return m.group(1) if m else ""


def golongan_of(label) -> str:
    p = tarif_prefix(label)
    if p in config.L_GROUP_PREFIXES:
        return "L"
    return p


def is_tt(label) -> bool:
    return bool(_TT_RX.search(tarif_key(label)))
