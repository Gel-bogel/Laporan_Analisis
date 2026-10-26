"""Forecasting kWh bulanan: XGBoost (fallback GradientBoosting scikit-learn) dan Prophet.

Fitur XGBoost: lag, rolling mean, musiman (sin/cos bulan), porsi hari Ramadhan dalam bulan,
penanda bulan Idul Fitri, dan tren (indeks waktu). Tanggal Ramadhan/Idul Fitri dihitung dengan
library kalender Hijriah (hijridate / hijri-converter / convertdate) atau dibaca dari CSV di
config.HOLIDAY_OVERRIDE_CSV — tidak ada tabel tahun di kode.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config


# =========================================================================== kalender Hijriah
def _hijri_year_of(d: dt.date) -> Optional[int]:
    try:
        from hijridate import Gregorian
        return Gregorian(d.year, d.month, d.day).to_hijri().year
    except Exception:
        pass
    try:
        from hijri_converter import Gregorian
        return Gregorian(d.year, d.month, d.day).to_hijri().year
    except Exception:
        pass
    try:
        from convertdate import islamic
        return islamic.from_gregorian(d.year, d.month, d.day)[0]
    except Exception:
        return None


def _hijri_to_greg(h_year: int, h_month: int, h_day: int) -> Optional[dt.date]:
    try:
        from hijridate import Hijri
        g = Hijri(h_year, h_month, h_day).to_gregorian()
        return dt.date(g.year, g.month, g.day)
    except Exception:
        pass
    try:
        from hijri_converter import Hijri
        g = Hijri(h_year, h_month, h_day).to_gregorian()
        return dt.date(g.year, g.month, g.day)
    except Exception:
        pass
    try:
        from convertdate import islamic
        y, m, d = islamic.to_gregorian(h_year, h_month, h_day)
        return dt.date(y, m, d)
    except Exception:
        return None


# Bulan Hijriah (konstanta kalender, bukan angka bisnis)
_RAMADHAN, _SYAWAL = 9, 10


def _override_dates() -> Optional[pd.DataFrame]:
    path = config.HOLIDAY_OVERRIDE_CSV
    if path and os.path.isfile(path):
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        df["tanggal"] = pd.to_datetime(df["tanggal"]).dt.date
        df["jenis"] = df["jenis"].str.strip().str.lower()
        return df
    return None


@lru_cache(maxsize=None)
def ramadhan_periods(greg_year: int) -> Tuple[Tuple[dt.date, dt.date], ...]:
    """Daftar (awal Ramadhan, Idul Fitri) yang menyentuh tahun Masehi `greg_year`."""
    ov = _override_dates()
    out = []
    if ov is not None:
        starts = sorted(ov.loc[ov["jenis"].str.contains("ramadhan|ramadan"), "tanggal"])
        eids = sorted(ov.loc[ov["jenis"].str.contains("fitri"), "tanggal"])
        for s in starts:
            e = next((x for x in eids if x > s), None)
            if e and (s.year == greg_year or e.year == greg_year):
                out.append((s, e))
        if out:
            return tuple(out)
    h = _hijri_year_of(dt.date(greg_year, 1, 1))
    if h is None:
        return tuple()
    for hy in (h, h + 1):
        s = _hijri_to_greg(hy, _RAMADHAN, 1)
        e = _hijri_to_greg(hy, _SYAWAL, 1)
        if s and e and (s.year == greg_year or e.year == greg_year):
            out.append((s, e))
    return tuple(out)


def calendar_available() -> bool:
    return len(ramadhan_periods(dt.date.today().year)) > 0


def islamic_features(p: pd.Period) -> Tuple[float, float]:
    """(porsi hari Ramadhan dalam bulan, 1 bila Idul Fitri jatuh di bulan itu)."""
    start = dt.date(p.year, p.month, 1)
    end = (p + 1).to_timestamp().date()
    ndays = (end - start).days
    frac, eid = 0.0, 0.0
    for s, e in ramadhan_periods(p.year):
        overlap = (min(e, end) - max(s, start)).days
        if overlap > 0:
            frac += overlap / ndays
        if start <= e < end:
            eid = 1.0
    return frac, eid


# =========================================================================== fitur & model
def _usable_lags(n: int) -> List[int]:
    return [l for l in config.FORECAST_LAGS if l <= max(1, n // 2)]


def _features(hist: pd.Series, p: pd.Period, t: int, lags: List[int]) -> Dict[str, float]:
    f = {"t": float(t), "sin": np.sin(2 * np.pi * p.month / 12), "cos": np.cos(2 * np.pi * p.month / 12)}
    f["ramadhan"], f["idulfitri"] = islamic_features(p)
    for l in lags:
        f[f"lag{l}"] = hist.iloc[-l] if len(hist) >= l else np.nan
    for w in config.FORECAST_ROLLING_WINDOWS:
        f[f"roll{w}"] = hist.iloc[-w:].mean() if len(hist) >= w else np.nan
    return f


def _design(series: pd.Series, lags: List[int]) -> pd.DataFrame:
    rows = []
    for i in range(len(series)):
        hist = series.iloc[:i]
        f = _features(hist, series.index[i], i, lags)
        f["y"] = series.iloc[i]
        rows.append(f)
    return pd.DataFrame(rows, index=series.index)


def _make_regressor():
    try:
        from xgboost import XGBRegressor
        return XGBRegressor(random_state=config.RANDOM_STATE, **config.XGB_PARAMS), "XGBoost"
    except Exception:
        from sklearn.ensemble import GradientBoostingRegressor
        return (GradientBoostingRegressor(random_state=config.RANDOM_STATE, **config.GBR_PARAMS),
                "GradientBoosting (scikit-learn, fallback karena xgboost tidak terpasang)")


def _fit_predict_tree(train: pd.Series, horizon: int, lags: List[int]):
    X = _design(train, lags).dropna()
    if len(X) < 3:
        raise ValueError("Data latih terlalu sedikit setelah pembentukan fitur lag.")
    model, name = _make_regressor()
    feats = [c for c in X.columns if c != "y"]
    model.fit(X[feats].values, X["y"].values)
    fitted = pd.Series(model.predict(X[feats].values), index=X.index)
    hist = train.copy()
    preds = []
    for h in range(horizon):
        p = hist.index[-1] + 1
        f = _features(hist, p, len(hist), lags)
        yhat = float(model.predict(np.array([[f[c] for c in feats]]))[0])
        preds.append((p, yhat))
        hist = pd.concat([hist, pd.Series([yhat], index=[p])])
    return pd.Series(dict(preds)), fitted, name


def _metrics(actual: pd.Series, pred: pd.Series) -> Dict[str, float]:
    a, p = actual.align(pred, join="inner")
    mask = a != 0
    mape = float(np.mean(np.abs((a[mask] - p[mask]) / a[mask])) * 100) if mask.any() else np.nan
    rmse = float(np.sqrt(np.mean((a - p) ** 2))) if len(a) else np.nan
    return {"MAPE (%)": mape, "RMSE (kWh)": rmse}


@dataclass
class ForecastResult:
    model: str
    history: pd.Series
    test_pred: pd.Series
    metrics: Dict[str, float]
    forecast: pd.DataFrame          # index Period; kolom yhat, lower, upper
    warnings: List[str] = field(default_factory=list)


def check_series(series: pd.Series, holdout: int) -> Optional[str]:
    s = series.dropna()
    need = config.FORECAST_MIN_TRAIN_POINTS + holdout
    if len(s) < need:
        return (f"Data hanya {len(s)} bulan; dibutuhkan minimal {need} bulan "
                f"({config.FORECAST_MIN_TRAIN_POINTS} latih + {holdout} hold-out).")
    full = pd.period_range(s.index.min(), s.index.max(), freq="M")
    if len(full) != len(s):
        return "Deret waktu memiliki bulan yang bolong; lengkapi data dulu."
    return None


def run_tree_forecast(series: pd.Series, horizon: int, holdout: int) -> ForecastResult:
    s = series.dropna().astype(float)
    warns = []
    if not calendar_available():
        warns.append("Library kalender Hijriah tidak tersedia; fitur Ramadhan/Idul Fitri bernilai 0.")
    lags = _usable_lags(len(s) - holdout)
    dropped = sorted(set(config.FORECAST_LAGS) - set(lags))
    if dropped:
        warns.append(f"Lag {dropped} tidak dipakai karena data historis belum cukup panjang.")
    train, test = s.iloc[:-holdout], s.iloc[-holdout:]
    test_pred, _, name = _fit_predict_tree(train, holdout, lags)
    metrics = _metrics(test, test_pred)
    resid = (test - test_pred).to_numpy()
    sigma = float(np.std(resid, ddof=1)) if len(resid) > 1 else float(np.abs(resid).mean())
    fut, _, _ = _fit_predict_tree(s, horizon, lags)
    steps = np.sqrt(np.arange(1, horizon + 1))
    fc = pd.DataFrame({"yhat": fut.values,
                       "lower": fut.values - config.FORECAST_INTERVAL_Z * sigma * steps,
                       "upper": fut.values + config.FORECAST_INTERVAL_Z * sigma * steps}, index=fut.index)
    return ForecastResult(name, s, test_pred, metrics, fc, warns)


def prophet_available() -> bool:
    try:
        import prophet  # noqa: F401
        return True
    except Exception:
        return False


def run_prophet_forecast(series: pd.Series, horizon: int, holdout: int) -> ForecastResult:
    from prophet import Prophet
    s = series.dropna().astype(float)

    def frame(idx):
        d = pd.DataFrame({"ds": [p.to_timestamp() for p in idx]})
        d["ramadhan"] = [islamic_features(p)[0] for p in idx]
        return d

    def fit(train):
        m = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False,
                    interval_width=config.PROPHET_INTERVAL_WIDTH)
        m.add_regressor("ramadhan")
        d = frame(train.index)
        d["y"] = train.values
        m.fit(d)
        return m

    train, test = s.iloc[:-holdout], s.iloc[-holdout:]
    m = fit(train)
    p_test = m.predict(frame(test.index))
    test_pred = pd.Series(p_test["yhat"].values, index=test.index)
    metrics = _metrics(test, test_pred)
    m2 = fit(s)
    fut_idx = pd.period_range(s.index[-1] + 1, periods=horizon, freq="M")
    pf = m2.predict(frame(fut_idx))
    fc = pd.DataFrame({"yhat": pf["yhat"].values, "lower": pf["yhat_lower"].values,
                       "upper": pf["yhat_upper"].values}, index=fut_idx)
    return ForecastResult("Prophet", s, test_pred, metrics, fc, [])
