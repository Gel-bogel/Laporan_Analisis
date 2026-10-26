"""Deteksi anomali pelanggan (DB I / DB B).

- Isolation Forest atas fitur pertumbuhan MoM tiap pelanggan (N bulan terakhir).
- K-Means atas pola konsumsi yang dinormalisasi z-score per pelanggan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

import config
from modules.column_utils import normalize_idpel, period_label, to_num
from modules.etl_merge import EtlSheetResult


def consumption_matrix(s: EtlSheetResult, window: int, end: Tuple[int, int]) -> pd.DataFrame:
    """Baris = pelanggan (IDPEL unik), kolom = `window` bulan terakhir s.d. `end` (kWh)."""
    periods = [p for p in sorted(s.kwh_cols) if p <= tuple(end)][-window:]
    cols = [s.kwh_cols[p] for p in periods]
    ids = s.df[s.idpel_col].map(normalize_idpel)
    mat = to_num(s.df[cols]).fillna(0.0)
    mat.columns = [period_label(*p) for p in periods]
    mat.index = ids
    mat = mat[~mat.index.duplicated(keep="first")]
    return mat


def _mom_features(mat: pd.DataFrame) -> pd.DataFrame:
    prev = mat.shift(1, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        g = (mat - prev) / prev.abs()
    g = g.where(prev != 0, np.where(mat > 0, config.ANOMALY_GROWTH_CLIP, 0.0))
    g = g.iloc[:, 1:].clip(-config.ANOMALY_GROWTH_CLIP, config.ANOMALY_GROWTH_CLIP).fillna(0.0)
    return g


def _zscore_rows(mat: pd.DataFrame) -> pd.DataFrame:
    mu = mat.mean(axis=1)
    sd = mat.std(axis=1, ddof=0).replace(0, np.nan)
    return mat.sub(mu, axis=0).div(sd, axis=0).fillna(0.0)


def _describe_pattern(centroid: np.ndarray) -> str:
    x = np.arange(len(centroid))
    slope = float(np.polyfit(x, centroid, 1)[0]) if len(centroid) > 1 else 0.0
    last, first = centroid[-max(1, len(centroid) // config.PATTERN_EDGE_FRACTION_DIV):].mean(), centroid[:max(1, len(centroid) // config.PATTERN_EDGE_FRACTION_DIV)].mean()
    resid = centroid - np.polyval(np.polyfit(x, centroid, 1), x) if len(centroid) > 1 else centroid
    vol = float(np.std(resid))
    parts = []
    if slope > config.PATTERN_SLOPE_THRESHOLD:
        parts.append("tren naik")
    elif slope < -config.PATTERN_SLOPE_THRESHOLD:
        parts.append("tren turun")
    else:
        parts.append("relatif stabil")
    if vol > config.PATTERN_VOLATILITY_THRESHOLD:
        parts.append("berfluktuasi / ada lonjakan")
    if abs(last - first) > config.PATTERN_SHIFT_THRESHOLD:
        parts.append("akhir periode " + ("jauh lebih tinggi" if last > first else "jauh lebih rendah"))
    return ", ".join(parts)


@dataclass
class AnomalyResult:
    table: pd.DataFrame           # per pelanggan: skor, flag, kelompok, info
    growth: pd.DataFrame          # fitur MoM
    zmat: pd.DataFrame            # pola z-score
    centroids: pd.DataFrame       # pusat kelompok K-Means
    pattern_names: Dict[int, str]
    months: List[str]
    warnings: List[str] = field(default_factory=list)


def run_anomaly(s: EtlSheetResult, window: int, end: Tuple[int, int], contamination: float,
                k: int) -> AnomalyResult:
    from sklearn.cluster import KMeans
    from sklearn.ensemble import IsolationForest

    warns = []
    mat = consumption_matrix(s, window, end)
    if mat.shape[1] < 3:
        raise ValueError("Minimal 3 bulan data diperlukan untuk deteksi anomali.")
    active = mat.sum(axis=1) > 0
    if (~active).any():
        warns.append(f"{int((~active).sum())} pelanggan tanpa konsumsi di jendela waktu diabaikan.")
    mat = mat[active]
    growth = _mom_features(mat)
    iso = IsolationForest(contamination=contamination, random_state=config.RANDOM_STATE,
                          n_estimators=config.ISOFOREST_N_ESTIMATORS)
    iso.fit(growth.values)
    score = -iso.score_samples(growth.values)            # makin besar makin janggal
    flag = iso.predict(growth.values) == -1
    z = _zscore_rows(mat)
    k_eff = int(min(k, max(1, len(z))))
    if k_eff < k:
        warns.append(f"Jumlah kelompok diturunkan ke {k_eff} (pelanggan terlalu sedikit).")
    km = KMeans(n_clusters=k_eff, n_init=config.KMEANS_N_INIT, random_state=config.RANDOM_STATE)
    lab = km.fit_predict(z.values)
    cent = pd.DataFrame(km.cluster_centers_, columns=mat.columns)
    names = {i: _describe_pattern(cent.iloc[i].values) for i in range(k_eff)}
    info_cols = [c for c in [s.nama_col, s.cluster_col] if c]
    ids = s.df[s.idpel_col].map(normalize_idpel)
    info = s.df.assign(_id=ids).drop_duplicates("_id").set_index("_id")[info_cols]
    last_growth = growth.iloc[:, -1] * 100
    maxabs = growth.abs().max(axis=1) * 100
    bulan_maks = growth.abs().idxmax(axis=1)
    tbl = pd.DataFrame({
        "IDPEL": mat.index, "Skor anomali": score, "Anomali?": np.where(flag, "Ya", "Tidak"),
        "Kelompok pola": lab, "Pola": [names[i] for i in lab],
        "kWh bulan terakhir": mat.iloc[:, -1].values, "Rata-rata kWh": mat.mean(axis=1).values,
        "MoM terakhir (%)": last_growth.values, "Perubahan MoM terbesar (%)": maxabs.values,
        "Bulan perubahan terbesar": bulan_maks.values,
    })
    tbl = tbl.join(info, on="IDPEL")
    tbl = tbl.sort_values("Skor anomali", ascending=False).reset_index(drop=True)
    return AnomalyResult(tbl, growth, z, cent, names, list(mat.columns), warns)
