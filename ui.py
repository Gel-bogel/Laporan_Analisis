"""Komponen antarmuka (UI) & CSS kustom: tema korporat PLN yang modern, bersih, dan santai.

Isi:
- inject_css()            : CSS global (tipografi, warna, kartu, tombol, dropzone, metrik, tab, sidebar)
- sidebar_brand()         : header branding di sidebar
- nav(menus)              : navigasi sidebar berbentuk pill button (ikon Material + efek hover)
- sidebar_status(items)   : status "Data tersimpan" dengan badge berwarna
- page_header(menu)       : banner header tiap menu
- section(title, hint)    : judul seksi dengan ikon
- card_header(...)        : kepala kartu unggah (ikon, judul, keterangan, chip format file)
- file_row(...), badge(...), checklist(...), stat_grid(...) : potongan HTML kecil

Semua warna/teks branding ada di config.py (UI_*). Selector CSS memakai data-testid Streamlit yang
stabil (stSidebar, stFileUploaderDropzone, stMetric, stBaseButton-*, stTabs, stExpander) dan kelas
st-key-<key> dari st.container(key=...).
"""
from __future__ import annotations

import base64
import html
import inspect
from typing import Iterable, List, Optional, Sequence

import streamlit as st

import config

# Nilai cadangan bila config.py yang terpasang masih versi lama (belum punya bagian 11 "Antarmuka").
# Sumber utama tetap config.py; nilai di sini hanya dipakai untuk atribut UI_* yang tidak ditemukan,
# supaya aplikasi tetap terbuka dan menampilkan peringatan (lihat MISSING_CONFIG).
_FALLBACK = {
    'UI_APP_NAME': 'PLN UP3 Medan Utara',
    'UI_APP_TAGLINE': 'Analitik Penjualan Tenaga Listrik',
    'UI_COLORS': {'blue': '#0072bc',
 'cyan': '#00a2e8',
 'blue_dark': '#0b4f86',
 'navy': '#0e2742',
 'navy2': '#14334f',
 'navy3': '#1b4166',
 'ink': '#1b2b41',
 'slate': '#5b6b7f',
 'muted': '#8a97a8',
 'line': '#e3e8ef',
 'bg': '#f8f9fa',
 'surface': '#ffffff',
 'tint': '#eaf5fc',
 'ok': '#1e9e6a',
 'ok_bg': '#e6f6ee',
 'bad': '#d14343',
 'bad_bg': '#fdecec',
 'warn': '#b7791f',
 'warn_bg': '#fff4e0',
 'off': '#5b6b7f',
 'off_bg': '#eef1f5',
 'side_ink': '#dce6f2',
 'side_muted': '#8fa3bb'},
    'UI_FILENAME_MAX_CHARS': 28,
    'UI_FONT_BODY': 'Inter, "Segoe UI", Roboto, system-ui, -apple-system, sans-serif',
    'UI_FONT_HEAD': '"Plus Jakarta Sans", Inter, "Segoe UI", Roboto, system-ui, sans-serif',
    'UI_FONT_URL': 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap',
    'UI_MENU_META': {'1. Upload & ETL': ('cloud_upload',
                     'upload',
                     'Unggah sumber data sekali, lalu jalankan ETL AP2T ke database klaster DB I & '
                     'DB B.'),
 '2. Analitik Pertumbuhan': ('trending_up',
                             'trend',
                             'Pertumbuhan MoM, YoY kumulatif, capaian target, dan rincian per '
                             'golongan & jenis tarif.'),
 '3. Klaster Industri & Bisnis': ('factory',
                                  'layers',
                                  'Perbandingan sd per cluster KBLI, kontribusi pertumbuhan, dan '
                                  'rekonsiliasi file.'),
 '4. Forecasting (ML)': ('insights',
                         'chart',
                         'Perkiraan penjualan kWh beberapa bulan ke depan dari pola historis.'),
 '5. Deteksi Anomali (ML)': ('troubleshoot',
                             'alert',
                             'Pelanggan dengan pola konsumsi janggal sebagai daftar prioritas '
                             'pengecekan.')},
    'UI_RADIUS_CARD': '14px',
    'UI_RADIUS_PILL': '10px',
    'UI_UNIT_LABEL': 'PT PLN (Persero)',
}
MISSING_CONFIG = [k for k in _FALLBACK if not hasattr(config, k)]
for _k in MISSING_CONFIG:
    setattr(config, _k, _FALLBACK[_k])

C = config.UI_COLORS

# --------------------------------------------------------------------------- ikon SVG (garis, 24×24)
_ICON_PATHS = {
    "bolt": ['<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>'],
    "upload": ['<path d="M4 14.9A7 7 0 1 1 15.7 8h1.8a4.5 4.5 0 0 1 2.5 8.2"/>', '<path d="M12 12v9"/>',
               '<path d="m16 16-4-4-4 4"/>'],
    "file": ['<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>',
             '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>', '<path d="M10 9H8"/>', '<path d="M16 13H8"/>',
             '<path d="M16 17H8"/>'],
    "sheet": ['<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>',
              '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>', '<path d="M8 13h2"/>', '<path d="M14 13h2"/>',
              '<path d="M8 17h2"/>', '<path d="M14 17h2"/>'],
    "database": ['<ellipse cx="12" cy="5" rx="9" ry="3"/>', '<path d="M3 5v14a9 3 0 0 0 18 0V5"/>',
                 '<path d="M3 12a9 3 0 0 0 18 0"/>'],
    "receipt": ['<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/>',
                '<path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/>', '<path d="M12 17.5v-11"/>'],
    "sync": ['<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>', '<path d="M3 3v5h5"/>',
             '<path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/>', '<path d="M16 16h5v5"/>'],
    "trend": ['<path d="M22 7 13.5 15.5 8.5 10.5 2 17"/>', '<path d="M16 7h6v6"/>'],
    "layers": ['<path d="m12 2 10 5-10 5L2 7Z"/>', '<path d="m2 17 10 5 10-5"/>', '<path d="m2 12 10 5 10-5"/>'],
    "chart": ['<path d="M3 3v18h18"/>', '<path d="m19 9-5 5-4-4-3 3"/>'],
    "alert": ['<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>',
              '<path d="M12 9v4"/>', '<path d="M12 17h.01"/>'],
    "info": ['<circle cx="12" cy="12" r="10"/>', '<path d="M12 16v-4"/>', '<path d="M12 8h.01"/>'],
    "check": ['<path d="M20 6 9 17l-5-5"/>'],
    "circle": ['<circle cx="12" cy="12" r="9"/>'],
    "search": ['<circle cx="11" cy="11" r="8"/>', '<path d="m21 21-4.3-4.3"/>'],
    "folder": ['<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4'
               'a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'],
}


_SVG_NS = "http://www.w3.org/2000/svg"            # namespace standar SVG (bukan angka bisnis)


def icon(name: str, size: int = 20, stroke: float = 2.0, cls: str = "") -> str:
    """Ikon garis sebagai <span> ber-mask CSS (warna mengikuti `color` elemen induk).

    st.html membersihkan HTML dengan DOMPurify profil HTML saja, sehingga tag <svg> langsung DIHAPUS.
    Karena itu SVG disimpan sebagai data URI di variabel CSS --pln-i dan dipakai sebagai mask;
    atribut style tidak dibuang oleh DOMPurify.
    """
    paths = "".join(_ICON_PATHS.get(name, _ICON_PATHS["info"]))
    svg = (f'<svg xmlns="{_SVG_NS}" viewBox="0 0 24 24" fill="none" stroke="black" '
           f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return (f'<span class="pln-ico {cls}" aria-hidden="true" '
            f"style=\"width:{size}px;height:{size}px;--pln-i:url('{uri}')\"></span>")


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def short_name(name: str, max_chars: Optional[int] = None) -> str:
    """Potong nama file panjang di tengah: 'CR_LAP_309_PUS…AGT2026.pdf' (nama lengkap ada di tooltip)."""
    n = max_chars or config.UI_FILENAME_MAX_CHARS
    s = str(name)
    if len(s) <= n:
        return s
    head = (n - 1) * 3 // 5
    tail = n - 1 - head
    return s[:head] + "…" + s[-tail:]


def _html(markup: str, where=None):
    """Tulis HTML apa adanya (tanpa diproses Markdown)."""
    (where or st).html(markup)


# --------------------------------------------------------------------------- CSS global
def _css() -> str:
    c = C
    return f"""
<style>
@import url('{config.UI_FONT_URL}');
:root {{
  --pln-blue:{c['blue']}; --pln-cyan:{c['cyan']}; --pln-blue-dark:{c['blue_dark']};
  --pln-navy:{c['navy']}; --pln-navy2:{c['navy2']}; --pln-navy3:{c['navy3']};
  --pln-ink:{c['ink']}; --pln-slate:{c['slate']}; --pln-muted:{c['muted']};
  --pln-line:{c['line']}; --pln-bg:{c['bg']}; --pln-surface:{c['surface']}; --pln-tint:{c['tint']};
  --pln-ok:{c['ok']}; --pln-ok-bg:{c['ok_bg']}; --pln-bad:{c['bad']}; --pln-bad-bg:{c['bad_bg']};
  --pln-warn:{c['warn']}; --pln-warn-bg:{c['warn_bg']}; --pln-off:{c['off']}; --pln-off-bg:{c['off_bg']};
  --pln-side-ink:{c['side_ink']}; --pln-side-muted:{c['side_muted']};
  --pln-font:{config.UI_FONT_BODY}; --pln-font-head:{config.UI_FONT_HEAD};
  --pln-r:{config.UI_RADIUS_CARD}; --pln-r-pill:{config.UI_RADIUS_PILL};
  --pln-shadow:0 1px 2px rgba(16,40,70,.04), 0 4px 18px rgba(16,40,70,.06);
  --pln-shadow-hover:0 2px 4px rgba(16,40,70,.05), 0 10px 28px rgba(0,114,188,.10);
}}

/* ---------- ikon (mask SVG, warna = currentColor) */
.pln-ico {{ display: inline-block; flex: 0 0 auto; vertical-align: middle; background-color: currentColor;
  -webkit-mask: var(--pln-i) center / contain no-repeat; mask: var(--pln-i) center / contain no-repeat; }}

/* ---------- dasar */
html, body, .stApp, [data-testid="stAppViewContainer"] {{ background: var(--pln-bg); }}
.stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp button,
[data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"] {{ font-family: var(--pln-font); }}
.stApp {{ color: var(--pln-ink); }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container, [data-testid="stMainBlockContainer"] {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1440px; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: var(--pln-slate); }}
.stApp a {{ color: var(--pln-blue); }}

/* ---------- judul */
.stHeading h1, .stHeading h2, .stHeading h3, .stHeading h4,
[data-testid="stHeading"] h1, [data-testid="stHeading"] h2, [data-testid="stHeading"] h3 {{
  font-family: var(--pln-font-head); color: var(--pln-ink); letter-spacing: -0.01em; }}
[data-testid="stHeading"] h3, .stHeading h3 {{
  font-size: 1.15rem; font-weight: 700; padding: .1rem 0 .1rem .7rem; margin-top: .6rem;
  border-left: 4px solid var(--pln-cyan); border-radius: 2px; }}
[data-testid="stHeading"] h2, .stHeading h2 {{ font-size: 1.4rem; font-weight: 700; }}

/* ---------- banner header */
.pln-hero {{ position: relative; overflow: hidden; border-radius: 18px; padding: 26px 30px 24px;
  background: radial-gradient(1200px 300px at 100% 0%, rgba(0,162,232,.55), transparent 60%),
              linear-gradient(120deg, #0b3d6e 0%, var(--pln-blue) 58%, var(--pln-cyan) 100%);
  color: #fff; box-shadow: 0 10px 30px rgba(0,114,188,.18); margin-bottom: 6px; }}
.pln-hero::before {{ content: ""; position: absolute; right: -60px; top: -80px; width: 280px; height: 280px;
  border-radius: 50%; border: 36px solid rgba(255,255,255,.07); }}
.pln-hero::after {{ content: ""; position: absolute; right: 120px; bottom: -110px; width: 200px; height: 200px;
  border-radius: 50%; background: rgba(255,255,255,.05); }}
.pln-hero-top {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; position: relative; z-index: 1; }}
.pln-eyebrow {{ display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600;
  letter-spacing: .08em; text-transform: uppercase; padding: 4px 10px; border-radius: 999px;
  background: rgba(255,255,255,.16); color: #fff; backdrop-filter: blur(4px); }}
.pln-hero-row {{ display: flex; align-items: center; gap: 16px; position: relative; z-index: 1; }}
.pln-hero-ico {{ flex: 0 0 auto; width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center;
  background: rgba(255,255,255,.15); border: 1px solid rgba(255,255,255,.22); color: #fff; }}
.pln-hero h1 {{ font-family: var(--pln-font-head); font-size: 28px; line-height: 1.2; font-weight: 800;
  color: #fff; margin: 0; padding: 0; letter-spacing: -0.02em; }}
.pln-hero p {{ margin: 4px 0 0; font-size: 14.5px; line-height: 1.5; color: rgba(255,255,255,.86);
  max-width: 760px; background: transparent; }}
.pln-hero-meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; position: relative; z-index: 1; }}
.pln-hero-meta span {{ font-size: 12px; color: rgba(255,255,255,.9); background: rgba(14,39,66,.22);
  border: 1px solid rgba(255,255,255,.16); padding: 3px 10px; border-radius: 999px; }}

/* ---------- judul seksi */
.pln-sec {{ display: flex; align-items: center; gap: 12px; margin: 18px 0 4px; }}
.pln-sec-ico {{ width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center;
  background: var(--pln-tint); color: var(--pln-blue); flex: 0 0 auto; }}
.pln-sec h2 {{ font-family: var(--pln-font-head); font-size: 18px; font-weight: 700; color: var(--pln-ink);
  margin: 0; padding: 0; letter-spacing: -0.01em; }}
.pln-sec p {{ margin: 1px 0 0; font-size: 13px; color: var(--pln-slate); }}

/* ---------- kartu (st.container(key="card_...")) */
div[class*="st-key-card_"] {{ background: var(--pln-surface); border: 1px solid var(--pln-line);
  border-radius: var(--pln-r); padding: 18px 18px 16px; box-shadow: var(--pln-shadow);
  transition: box-shadow .2s ease, border-color .2s ease, transform .2s ease; }}
div[class*="st-key-card_"]:hover {{ box-shadow: var(--pln-shadow-hover); border-color: #cfe3f3; }}
div[class*="st-key-cardrow1_"] {{ min-height: 100%; }}
.pln-card-h {{ display: flex; gap: 12px; align-items: flex-start; }}
.pln-card-ico {{ width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center; flex: 0 0 auto; }}
.pln-card-ico.blue {{ background: #e7f3fc; color: var(--pln-blue); }}
.pln-card-ico.teal {{ background: #e3f6f1; color: #12876a; }}
.pln-card-ico.indigo {{ background: #eceffd; color: #4757c9; }}
.pln-card-ico.amber {{ background: #fff3df; color: #b56d0d; }}
.pln-card-ico.cyan {{ background: #e2f6fd; color: #0a89c2; }}
.pln-card-t {{ min-width: 0; }}
.pln-card-t h4 {{ font-family: var(--pln-font-head); font-size: 15.5px; font-weight: 700; color: var(--pln-ink);
  margin: 0; padding: 0; line-height: 1.3; }}
.pln-card-t p {{ margin: 2px 0 0; font-size: 12.5px; line-height: 1.45; color: var(--pln-slate); }}
.pln-chips {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }}
.pln-chip {{ font-size: 10.5px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase;
  padding: 2px 7px; border-radius: 6px; background: var(--pln-off-bg); color: var(--pln-slate);
  border: 1px solid var(--pln-line); }}
.pln-chip.pdf {{ background: #fdeeee; color: #b4232a; border-color: #f8d7d7; }}
.pln-chip.xlsx, .pln-chip.xls {{ background: #e8f6ee; color: #177a4b; border-color: #cdebd9; }}

/* ---------- baris file tersimpan */
.pln-file {{ display: flex; align-items: center; gap: 10px; padding: 9px 11px; border-radius: 10px;
  background: #f6f9fc; border: 1px solid var(--pln-line); min-width: 0; }}
.pln-file .pln-ico {{ color: var(--pln-blue); flex: 0 0 auto; }}
.pln-file-t {{ min-width: 0; flex: 1 1 auto; }}
.pln-file-n {{ font-size: 13px; font-weight: 600; color: var(--pln-ink); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; cursor: default; }}
.pln-file-s {{ display: flex; align-items: center; gap: 8px; margin-top: 3px; min-width: 0; }}
.pln-file-m {{ font-size: 11.5px; color: var(--pln-slate); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  min-width: 0; cursor: default; }}
.pln-empty {{ font-size: 12.5px; color: var(--pln-muted); display: flex; gap: 8px; align-items: center;
  padding: 8px 2px 0; }}

/* ---------- badge / status tag */
.pln-badge {{ display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600;
  padding: 2px 9px 2px 7px; border-radius: 999px; white-space: nowrap; line-height: 1.6; }}
.pln-badge::before {{ content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }}
.pln-badge.ok {{ background: var(--pln-ok-bg); color: var(--pln-ok); }}
.pln-badge.bad {{ background: var(--pln-bad-bg); color: var(--pln-bad); }}
.pln-badge.warn {{ background: var(--pln-warn-bg); color: var(--pln-warn); }}
.pln-badge.off {{ background: var(--pln-off-bg); color: var(--pln-off); }}
.pln-badge.info {{ background: var(--pln-tint); color: var(--pln-blue); }}

/* ---------- checklist & statistik mini (kartu ETL) */
.pln-checks {{ display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 12px 0 4px; }}
.pln-check {{ display: inline-flex; align-items: center; gap: 7px; font-size: 13px; color: var(--pln-ink); }}
.pln-check-i {{ width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; flex: 0 0 auto; }}
.pln-check.ok .pln-check-i {{ background: var(--pln-ok-bg); color: var(--pln-ok); }}
.pln-check.off {{ color: var(--pln-muted); }}
.pln-check.off .pln-check-i {{ background: var(--pln-off-bg); color: var(--pln-muted); }}
.pln-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 6px 0 2px; }}
.pln-stat {{ background: #f6f9fc; border: 1px solid var(--pln-line); border-radius: 12px; padding: 10px 12px; }}
.pln-stat b {{ display: block; font-family: var(--pln-font-head); font-size: 18px; color: var(--pln-ink); }}
.pln-stat span {{ font-size: 11.5px; color: var(--pln-slate); }}

/* ---------- widget bawaan */
[data-testid="stFileUploaderDropzone"] {{ border: 1.5px dashed #a9cfea; background: #f5fafe;
  border-radius: 12px; transition: background .2s ease, border-color .2s ease; }}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color: var(--pln-blue); background: var(--pln-tint); }}
[data-testid="stFileUploaderDropzoneInstructions"] {{ color: var(--pln-slate); }}
[data-testid="stFileUploaderDropzoneInstructions"] small {{ color: var(--pln-muted); }}

[data-testid="stBaseButton-primary"] {{ background: linear-gradient(120deg, var(--pln-blue), var(--pln-cyan));
  border: none; color: #fff; font-weight: 600; box-shadow: 0 4px 14px rgba(0,114,188,.25);
  transition: transform .15s ease, box-shadow .2s ease, filter .2s ease; }}
[data-testid="stBaseButton-primary"]:hover {{ filter: brightness(1.05); transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(0,114,188,.30); color: #fff; }}
[data-testid="stBaseButton-secondary"] {{ background: var(--pln-surface); border: 1px solid var(--pln-line);
  color: var(--pln-ink); font-weight: 500; transition: border-color .2s ease, color .2s ease, background .2s ease; }}
[data-testid="stBaseButton-secondary"]:hover {{ border-color: var(--pln-blue); color: var(--pln-blue); background: #f5fafe; }}
[data-testid="stBaseButton-tertiary"] {{ color: var(--pln-slate); }}
[data-testid="stBaseButton-tertiary"]:hover {{ color: var(--pln-bad); }}

[data-testid="stMetric"] {{ background: var(--pln-surface); border: 1px solid var(--pln-line); border-radius: 12px;
  padding: 12px 16px; box-shadow: 0 1px 2px rgba(16,40,70,.04); }}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {{ color: var(--pln-slate); font-size: 12.5px; font-weight: 500; }}
[data-testid="stMetricValue"] {{ font-family: var(--pln-font-head); color: var(--pln-ink); font-weight: 700; font-size: 1.55rem; }}

[data-testid="stExpander"] details, .stExpander details {{ border: 1px solid var(--pln-line); border-radius: 12px;
  background: var(--pln-surface); box-shadow: 0 1px 2px rgba(16,40,70,.03); }}
[data-testid="stExpander"] summary:hover, .stExpander summary:hover {{ color: var(--pln-blue); }}

.stTabs [role="tablist"] {{ gap: 4px; border-bottom: 1px solid var(--pln-line); }}
.stTabs [role="tab"] {{ font-weight: 500; color: var(--pln-slate); padding-left: 12px; padding-right: 12px;
  border-radius: 8px 8px 0 0; transition: color .2s ease, background .2s ease; }}
.stTabs [role="tab"]:hover {{ color: var(--pln-blue); background: #f2f8fd; }}
.stTabs [role="tab"][aria-selected="true"] {{ color: var(--pln-blue); font-weight: 600; }}

[data-testid="stDataFrame"], [data-testid="stTable"] {{ border-radius: 12px; overflow: hidden;
  border: 1px solid var(--pln-line); background: var(--pln-surface); }}
[data-testid="stPlotlyChart"] {{ background: var(--pln-surface); border: 1px solid var(--pln-line);
  border-radius: var(--pln-r); padding: 10px 8px 4px; box-shadow: 0 1px 2px rgba(16,40,70,.04); }}
[data-testid="stAlertContainer"], [data-testid="stAlert"] > div {{ border-radius: 12px; }}

/* ---------- sidebar */
[data-testid="stSidebar"] {{ background: linear-gradient(180deg, var(--pln-navy) 0%, #0b2138 100%);
  border-right: 1px solid rgba(255,255,255,.04); }}
[data-testid="stSidebar"] > div, [data-testid="stSidebarContent"] {{ background: transparent; }}
[data-testid="stSidebarUserContent"] {{ padding-top: .5rem; }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"], [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
  color: var(--pln-side-muted); }}
.pln-brand {{ display: flex; align-items: center; gap: 12px; padding: 4px 4px 18px; margin-bottom: 8px;
  border-bottom: 1px solid rgba(255,255,255,.08); }}
.pln-logo {{ width: 44px; height: 44px; border-radius: 13px; display: grid; place-items: center; flex: 0 0 auto;
  background: linear-gradient(135deg, var(--pln-cyan), var(--pln-blue)); color: #fff;
  box-shadow: 0 6px 16px rgba(0,162,232,.35); }}
.pln-brand small {{ display: block; font-size: 10px; font-weight: 600; letter-spacing: .12em; text-transform: uppercase;
  color: var(--pln-cyan); }}
.pln-brand b {{ display: block; font-family: var(--pln-font-head); font-size: 16px; font-weight: 800; color: #fff;
  line-height: 1.2; letter-spacing: -0.01em; }}
.pln-brand span {{ display: block; font-size: 11.5px; color: var(--pln-side-muted); margin-top: 1px; }}
.pln-side-label {{ font-size: 10.5px; font-weight: 600; letter-spacing: .12em; text-transform: uppercase;
  color: var(--pln-side-muted); margin: 6px 6px 2px; }}

.st-key-pln_nav {{ gap: 4px; }}
.st-key-pln_nav button {{ justify-content: flex-start; text-align: left; width: 100%; min-height: 42px;
  padding: 8px 12px; border-radius: var(--pln-r-pill); border: 1px solid transparent; box-shadow: none;
  font-weight: 500; transition: background .18s ease, color .18s ease, transform .18s ease, border-color .18s ease; }}
.st-key-pln_nav button > div {{ justify-content: flex-start; }}
.st-key-pln_nav button p {{ font-size: 14px; }}
.st-key-pln_nav [data-testid="stBaseButton-secondary"] {{ background: transparent; color: var(--pln-side-ink); }}
.st-key-pln_nav [data-testid="stBaseButton-secondary"]:hover {{ background: rgba(255,255,255,.07); color: #fff;
  border-color: rgba(255,255,255,.08); transform: translateX(2px); }}
.st-key-pln_nav [data-testid="stBaseButton-primary"] {{ color: #fff; border-color: rgba(0,162,232,.35);
  background: linear-gradient(90deg, rgba(0,162,232,.30), rgba(0,114,188,.18));
  box-shadow: inset 3px 0 0 var(--pln-cyan); }}
.st-key-pln_nav [data-testid="stBaseButton-primary"]:hover {{ transform: none; filter: brightness(1.08); }}

.pln-status {{ margin-top: 14px; padding: 12px 12px 6px; border-radius: 14px; background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.07); }}
.pln-status-h {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }}
.pln-status-row {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 2px;
  border-top: 1px solid rgba(255,255,255,.06); }}
.pln-status-row:first-of-type {{ border-top: none; }}
.pln-status-t {{ min-width: 0; flex: 1 1 auto; }}
.pln-status-t b {{ display: block; font-size: 12.5px; font-weight: 600; color: var(--pln-side-ink); }}
.pln-status-t span {{ display: block; font-size: 11px; color: var(--pln-side-muted); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; max-width: 100%; cursor: default; }}
.pln-side .pln-badge.ok {{ background: rgba(46,204,138,.16); color: #6fe3b0; }}
.pln-side .pln-badge.off {{ background: rgba(255,255,255,.07); color: #a9b8ca; }}
.pln-side .pln-badge.warn {{ background: rgba(245,166,35,.16); color: #f6c26b; }}
.pln-side .pln-badge.bad {{ background: rgba(209,67,67,.18); color: #f19a9a; }}
.pln-side-foot {{ font-size: 11px; color: var(--pln-side-muted); margin: 10px 6px 0; line-height: 1.5; }}

@media (max-width: 640px) {{
  .pln-hero {{ padding: 20px 18px; }}
  .pln-hero h1 {{ font-size: 22px; }}
  .pln-hero-ico {{ width: 42px; height: 42px; }}
}}
</style>
"""


def inject_css():
    _html(_css())


# --------------------------------------------------------------------------- potongan HTML
def badge(text: str, kind: str = "off") -> str:
    return f'<span class="pln-badge {esc(kind)}">{esc(text)}</span>'


def chips(formats: Iterable[str]) -> str:
    return '<div class="pln-chips">' + "".join(
        f'<span class="pln-chip {esc(str(f).lower().lstrip("."))}">.{esc(str(f).upper().lstrip("."))}</span>'
        for f in formats) + "</div>"


def card_header(icon_name: str, title: str, subtitle: str, formats: Sequence[str] = (), tone: str = "blue",
                right: str = "", where=None):
    _html(f'<div class="pln-card-h"><div class="pln-card-ico {esc(tone)}">{icon(icon_name, 22)}</div>'
          f'<div class="pln-card-t" style="flex:1 1 auto"><h4>{esc(title)}</h4><p>{esc(subtitle)}</p>'
          f'{chips(formats) if formats else ""}</div>{right}</div>', where)


def file_row(name: str, meta: str = "", status: str = "", kind: str = "ok", where=None, icon_name: str = "file"):
    """Baris file tersimpan: nama (dipotong, nama lengkap di tooltip) + badge status + keterangan singkat."""
    b = badge(status, kind) if status else ""
    m = f'<span class="pln-file-m" title="{esc(meta)}">{esc(meta)}</span>' if meta else ""
    _html(f'<div class="pln-file">{icon(icon_name, 18)}<div class="pln-file-t">'
          f'<div class="pln-file-n" title="{esc(name)}">{esc(short_name(name))}</div>'
          f'<div class="pln-file-s">{b}{m}</div></div></div>', where)


def empty_hint(text: str, where=None):
    _html(f'<div class="pln-empty">{icon("info", 15)}<span>{esc(text)}</span></div>', where)


def checklist(items: Sequence[tuple], where=None):
    """items: [(teks, terpenuhi: bool), ...]"""
    _html('<div class="pln-checks">' + "".join(
        f'<span class="pln-check {"ok" if ok else "off"}"><span class="pln-check-i">'
        f'{icon("check" if ok else "circle", 14, 2.6)}</span>'
        f'{esc(t)}</span>' for t, ok in items) + "</div>", where)


def stat_grid(items: Sequence[tuple], where=None):
    """items: [(nilai, keterangan), ...] → kotak statistik kecil."""
    _html('<div class="pln-stats">' + "".join(
        f'<div class="pln-stat"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for v, k in items) + "</div>", where)


# --------------------------------------------------------------------------- struktur halaman
def page_header(menu: str, menus: Sequence[str], title: Optional[str] = None, desc: Optional[str] = None,
                meta: Sequence[str] = ()):
    """Banner header modern. menu = label menu (kunci config.UI_MENU_META)."""
    _, ico, d = config.UI_MENU_META.get(menu, ("", "info", ""))
    idx = list(menus).index(menu) + 1 if menu in menus else None
    t = title or menu.split(". ", 1)[-1]
    eyebrow = f"Menu {idx} dari {len(menus)}" if idx else config.UI_APP_NAME
    meta_html = ('<div class="pln-hero-meta">' + "".join(f"<span>{esc(m)}</span>" for m in meta) + "</div>"
                 if meta else "")
    _html(f'<div class="pln-hero"><div class="pln-hero-top"><span class="pln-eyebrow">{icon("bolt", 12, 2.4)}'
          f'{esc(eyebrow)}</span></div><div class="pln-hero-row"><div class="pln-hero-ico">{icon(ico, 26)}</div>'
          f'<div><h1>{esc(t)}</h1><p>{esc(desc or d)}</p></div></div>{meta_html}</div>')


def section(title: str, hint: str = "", icon_name: str = "folder", where=None):
    _html(f'<div class="pln-sec"><div class="pln-sec-ico">{icon(icon_name, 18)}</div><div>'
          f'<h2>{esc(title)}</h2>{f"<p>{esc(hint)}</p>" if hint else ""}</div></div>', where)


# --------------------------------------------------------------------------- sidebar
def sidebar_brand():
    _html(f'<div class="pln-brand"><div class="pln-logo">{icon("bolt", 24, 2.2)}</div><div>'
          f'<small>{esc(config.UI_UNIT_LABEL)}</small><b>{esc(config.UI_APP_NAME)}</b>'
          f'<span>{esc(config.UI_APP_TAGLINE)}</span></div></div>'
          f'<div class="pln-side-label">Navigasi</div>', st.sidebar)


def _stretch_kw(fn) -> dict:
    try:
        p = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    if "width" in p and isinstance(p["width"].default, str):
        return {"width": "stretch"}
    return {"use_container_width": True} if "use_container_width" in p else {}


def _go(menu: str):
    st.session_state["menu"] = menu


def nav(menus: Sequence[str]) -> str:
    """Navigasi sidebar berupa pill button. Menu aktif = tombol 'primary'. Kunci tombol: nav_<i>."""
    ss = st.session_state
    if ss.get("menu") not in menus:
        ss["menu"] = menus[0]
    kw = _stretch_kw(st.button)
    with st.sidebar.container(key="pln_nav"):
        for i, m in enumerate(menus):
            mat = config.UI_MENU_META.get(m, ("dashboard",))[0]
            st.button(m.split(". ", 1)[-1], key=f"nav_{i}", icon=f":material/{mat}:",
                      type="primary" if ss["menu"] == m else "secondary", on_click=_go, args=(m,), **kw)
    return ss["menu"]


def sidebar_status(items: List[dict], footer: str = ""):
    """items: dict(label, detail, tip, badge, kind). Ditampilkan sebagai kartu status di sidebar."""
    rows = "".join(
        f'<div class="pln-status-row"><div class="pln-status-t"><b>{esc(it["label"])}</b>'
        f'<span title="{esc(it.get("tip") or it.get("detail") or "")}">{esc(it.get("detail") or "–")}</span></div>'
        f'{badge(it["badge"], it.get("kind", "off"))}</div>' for it in items)
    n_ok = sum(1 for it in items if it.get("kind") == "ok")
    head = (f'<div class="pln-status-h"><span class="pln-side-label" style="margin:0">Data tersimpan</span>'
            f'{badge(f"{n_ok}/{len(items)} siap", "ok" if n_ok == len(items) else "off")}</div>')
    foot = f'<div class="pln-side-foot">{esc(footer)}</div>' if footer else ""
    _html(f'<div class="pln-side"><div class="pln-status">{head}{rows}</div>{foot}</div>', st.sidebar)
