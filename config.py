"""
config.py — SATU-SATUNYA tempat parameter teknis & pola teks.

Aturan proyek:
- TIDAK ada angka bisnis (kWh, IDPEL, target, tahun data, posisi kolom/baris) di sini
  maupun di modul lain. Semua angka bisnis berasal dari file yang diunggah/input user.
- Yang ada di sini hanya: pola teks untuk mengenali header/label, pengaturan awal (default)
  widget UI, dan parameter teknis model. Semua boleh diedit tanpa menyentuh kode lain.
"""

# ---------------------------------------------------------------------------
# 1. Master rekap "DATA USAHA AGA & PP UP3 MDU REKAP ..."
# ---------------------------------------------------------------------------
MASTER_SHEET_NAME = "KWH-MDU"            # dicocokkan tanpa peduli huruf besar/kecil & spasi
MASTER_BLOCK_PATTERN = r"^\s*gabungan\s+(\d{4})\s*$"   # sel kolom A pembuka blok
MASTER_START_YEAR = 2024                 # blok Gabungan sebelum tahun ini diabaikan
MASTER_HEADER_LABEL = "TARIF"            # sel kolom A baris header bulan
MASTER_HEADER_SEARCH_ROWS = 5            # berapa baris di bawah "Gabungan" dicari header TARIF
MASTER_SCAN_MAX_COLS = 200               # batas teknis kolom yang dibaca (sheet KWH-MDU lebar sekali)

# ---------------------------------------------------------------------------
# 2. Label tarif & golongan (dipakai laporan CR_LAP_309 dan master)
# ---------------------------------------------------------------------------
GOLONGAN = ["S", "R", "B", "I", "P", "L"]
GOLONGAN_LABEL = {
    "S": "Sosial", "R": "Rumah Tangga", "B": "Bisnis", "I": "Industri",
    "P": "Pemerintah", "L": "Lainnya (C/L/T)", "TT": "Tegangan Tinggi (I.4)",
    "TOTAL": "JUMLAH",
}
# Golongan L tidak punya baris "JUMLAH L": dijumlah dari baris berawalan huruf ini
L_GROUP_PREFIXES = ("C", "L", "T")
# TT = baris tarif I.4 (pola regex atas kunci tarif = label huruf besar tanpa spasi)
TT_TARIF_PATTERN = r"^I\.4(/|$)"
# Label tarif yang sah: 1-2 huruf, opsional ".<angka><huruf>", lalu "/" atau akhir label
TARIF_LABEL_PATTERN = r"^[A-Z]{1,2}(\.\d+[A-Z]*)?\s*(/|$)"
SUBROW_LABELS = ("II", "III")            # sub-baris yang diabaikan
TRAILING_MARK_PATTERN = r"\s+I$"         # penanda " I" di akhir label tarif
JUMLAH_LABEL = "JUMLAH"

# ---------------------------------------------------------------------------
# 3. Laporan bulanan CR_LAP_309_PUSATNEW
# ---------------------------------------------------------------------------
REPORT_CODE_KWH = "4=5+6"                # kode kolom JUMLAH pemakaian kWh
REPORT_CODE_TARIF = "1"
REPORT_CODE_PELANGGAN = "2"
REPORT_CODE_DAYA = "3"
REPORT_TARIF_HEADER = "TARIF"
REPORT_SHEET_HINT = "TOTAL"              # sheet yang namanya mengandung teks ini dipilih otomatis
REPORT_THOUSANDS_SEP = ","               # pemisah ribuan pada angka berbentuk teks (PDF)
REPORT_DECIMAL_SEP = "."
PERIOD_TEXT_PATTERN = r"BULAN\s*:?\s*([A-Za-z]+)\s+(\d{4})"
TOTAL_TOLERANCE_KWH = 1.0
                                         # ↑ toleransi selisih validasi S+R+B+I+P+L = JUMLAH
NON_NUMERIC_AS_ZERO = True               # sel angka yang berisi selain angka ('-', teks, #VALUE!) dibaca 0

# ---------------------------------------------------------------------------
# 4. Transaksi AP2T "LAPORAN DETIL TARIF I3 I4 DAN B3"
# ---------------------------------------------------------------------------
AP2T_HEADER_PATTERNS = {                 # regex atas teks header (huruf besar, spasi tunggal)
    "THBLLAP": r"^THBL(LAP)?$",
    "IDPEL": r"^IDPEL$",
    "NAMA PELANGGAN": r"^NAMA\s*PELANGGAN",
    "KODE KEPERLUAN": r"^KODE\s*KEPERLU",
    "KEPERLUAN": r"^KEPERLUAN$",
    "TARIF": r"^TARIF$",
}
AP2T_KWH_GROUP_PATTERN = r"^PEMA\w*\s*KWH$"     # "PEMAKAIAN KWH" (juga salah ketik "PEMAKIAN KWH")
AP2T_KWH_SUBHEADER_PATTERN = r"^JUMLAH$"
AP2T_TOTAL_PATTERN = r"^TOTAL$"
AP2T_HEADER_SEARCH_ROWS = 40             # baris teratas yang dipindai untuk mencari header
IDPEL_MIN_DIGITS = 10                    # "angka panjang" = IDPEL
THBL_PATTERN = r"^(\d{4})(\d{2})$"

# Routing tarif AP2T → sheet database klaster (berdasarkan awalan TARIF)
DB_SHEETS = {
    "DB I": {"sheet_pattern": r"^DB\s*I$", "tarif_prefix": "I", "label": "Industri"},
    "DB B": {"sheet_pattern": r"^DB\s*B$", "tarif_prefix": "B", "label": "Bisnis"},
}
DB_IDPEL_PATTERN = r"^ID\s*PEL$"
DB_NAMA_PATTERN = r"^NAMA[\s_]*PELANGGAN$"
DB_CLUSTER_PATTERNS = [r"cluster.*usulan.*kbli", r"cluster.*kbli", r"cluster", r"klaster"]
DB_HEADER_SEARCH_ROWS = 15
DEDUP_IDPEL_IN_CLUSTER = True            # IDPEL ganda dihitung sekali pada analisis cluster
CLUSTER_EMPTY_AS_ZERO = True             # Menu 3: nilai kosong / "-" ditampilkan & diekspor sebagai 0

# Pivot di file I3I2B2 (untuk rekonsiliasi)
PIVOT_ROW_LABEL_PATTERNS = [r"^row labels$", r"^label baris$"]
PIVOT_VALUE_PREFIX_PATTERN = r"^(sum of|jumlah dari|sum dari)\s*"
PIVOT_GRAND_TOTAL_PATTERNS = [r"^grand total$", r"^total keseluruhan$"]

# ---------------------------------------------------------------------------
# 5. Nama bulan (Indonesia & Inggris; variasi penulisan kolom)
# ---------------------------------------------------------------------------
MONTH_ALIASES = {
    1: ["JAN", "JANUARI", "JANUARY"],
    2: ["FEB", "PEB", "FEBRUARI", "FEBRUARY"],
    3: ["MAR", "MRT", "MARET", "MARCH"],
    4: ["APR", "APRIL"],
    5: ["MEI", "MAY"],
    6: ["JUN", "JUNI", "JUNE"],
    7: ["JUL", "JULI", "JULY"],
    8: ["AGT", "AGU", "AGS", "AGUS", "AGUSTUS", "AUG", "AUGUST"],
    9: ["SEP", "SEPT", "SEPTEMBER"],
    10: ["OKT", "OCT", "OKTOBER", "OCTOBER"],
    11: ["NOV", "NOP", "NOVEMBER", "NOPEMBER"],
    12: ["DES", "DEC", "DESEMBER", "DECEMBER"],
}
CANON_MONTH_ABBR = {1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MEI", 6: "JUN",
                    7: "JUL", 8: "AGT", 9: "SEP", 10: "OKT", 11: "NOV", 12: "DES"}
MONTH_NAME_ID = {1: "Januari", 2: "Februari", 3: "Maret", 4: "April", 5: "Mei", 6: "Juni",
                 7: "Juli", 8: "Agustus", 9: "September", 10: "Oktober", 11: "November",
                 12: "Desember"}
YEAR_2DIGIT_BASE = 2000                  # KWH_AUG26 → 2000 + 26
CANON_KWH_PREFIX = "KWH_"
CANON_SD_PREFIX = "sd "

# ---------------------------------------------------------------------------
# 6. Menu 2 — input target
# ---------------------------------------------------------------------------
TARGET_STEP_KWH = 100_000                # langkah number_input target (nilai awal selalu 0)

# ---------------------------------------------------------------------------
# 7. Menu 4 — Forecasting
# ---------------------------------------------------------------------------
FORECAST_HORIZON_DEFAULT = 6
FORECAST_HORIZON_MAX = 24
FORECAST_HOLDOUT_DEFAULT = 6
FORECAST_MIN_TRAIN_POINTS = 12           # minimal titik data latih setelah hold-out
FORECAST_LAGS = [1, 2, 3, 12]            # lag yang lebih panjang dari data otomatis dibuang
FORECAST_ROLLING_WINDOWS = [3, 6]
FORECAST_INTERVAL_Z = 1.96               # interval ±z·σ residual (≈95%)
PROPHET_INTERVAL_WIDTH = 0.95
XGB_PARAMS = {"n_estimators": 400, "max_depth": 3, "learning_rate": 0.05,
              "subsample": 0.9, "colsample_bytree": 0.9}
GBR_PARAMS = {"n_estimators": 400, "max_depth": 3, "learning_rate": 0.05, "subsample": 0.9}
RANDOM_STATE = 42
# File opsional (CSV kolom: tanggal, jenis) berisi tanggal Idul Fitri/awal Ramadhan resmi.
# Bila diisi & ada, file ini dipakai; bila kosong, tanggal dihitung dengan library kalender.
HOLIDAY_OVERRIDE_CSV = ""

# ---------------------------------------------------------------------------
# 8. Menu 5 — Deteksi anomali
# ---------------------------------------------------------------------------
ANOMALY_WINDOW_DEFAULT = 12              # jumlah bulan terakhir yang dipakai
ANOMALY_CONTAMINATION_DEFAULT = 0.05
ANOMALY_CONTAMINATION_MAX = 0.3
KMEANS_K_DEFAULT = 4
KMEANS_K_MAX = 10
ANOMALY_GROWTH_CLIP = 5.0                # pertumbuhan MoM dipotong ke ±500% agar stabil
PATTERN_SLOPE_THRESHOLD = 0.08           # kemiringan z-score/bulan untuk label "naik"/"turun"
PATTERN_VOLATILITY_THRESHOLD = 0.55      # simpangan sisa-tren z-score untuk label "berfluktuasi"
PATTERN_SHIFT_THRESHOLD = 1.0            # beda rata-rata z awal vs akhir untuk label "jauh lebih ..."
PATTERN_EDGE_FRACTION_DIV = 4            # "awal"/"akhir" = 1/4 jendela pertama/terakhir
ISOFOREST_N_ESTIMATORS = 300
KMEANS_N_INIT = 10

# ---------------------------------------------------------------------------
# 9. Lain-lain
# ---------------------------------------------------------------------------
SOFFICE_CANDIDATES = ["soffice", "libreoffice",
                      r"C:\Program Files\LibreOffice\program\soffice.exe",
                      r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                      "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
SOFFICE_TIMEOUT_SEC = 180

# ---------------------------------------------------------------------------
# 10. Tampilan
# ---------------------------------------------------------------------------
# Penafsiran MAPE untuk penjelasan hasil forecast (batas atas %, label)
MAPE_BANDS = [(5, "sangat akurat"), (10, "akurat"), (20, "cukup layak"), (float("inf"), "kurang akurat")]
COLOR_UP = "#1e9e6a"                     # batang selisih positif (hijau lembut)
COLOR_DOWN = "#d14343"                   # batang selisih negatif (merah lembut)
COLOR_BASE = "#9fb3c8"                   # pembanding (slate muda)
COLOR_COMP = "#0072bc"                   # yang dibandingkan (biru PLN)
CHART_ROW_HEIGHT = 26                    # tinggi px per baris pada grafik batang horizontal

# Grafik gaya "YOY PENJUALAN" (Menu 2) — lihat modules/charts.py
# Bentuk mengikuti referensi user; warna mengikuti tema aplikasi (terang/gelap), latar transparan.
# Pasangan biru/hijau-toska lolos uji palet (beda warna aman untuk buta warna) di kedua mode.
YOY_THEME = {
    "light": {
        "prev": "#0072bc", "cur": "#1baf7a",            # pembanding (biru PLN), realisasi (hijau-toska)
        "up": "#1e9e6a", "down": "#d14343",             # panah naik / turun (warna status)
        "ink": "#1b2b41", "ink2": "#5b6b7f", "muted": "#8a97a8",
        "grid": "#e3e8ef", "axis": "#c9d3df", "gap": "#f8f9fa",
    },
    "dark": {
        "prev": "#3987e5", "cur": "#199e70",
        "up": "#0ca30c", "down": "#e66767",
        "ink": "#fafafa", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "gap": "#0e1117",
    },
}
YOY_FONT_FAMILY = 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
YOY_BAR_RADIUS = 4                       # sudut batang membulat (piksel)
YOY_CHART_HEIGHT = 560
YOY_TOP_PX = 60
YOY_LEFT_PX = 150                        # ruang label baris tabel di kiri
YOY_TABLE_HEADER_PX = 30                 # jarak sumbu x → baris tabel pertama
YOY_TABLE_ROW_PX = 24
YOY_TICK_WRAP_CHARS = 14                 # label sumbu x lebih panjang dari ini dipecah ke baris baru
YOY_TICK_LINE_PX = 15                    # tambahan jarak per baris ekstra label sumbu x
YOY_TABLE_FONT = 12
YOY_TABLE_FONT_COMPACT = 11
YOY_LEGEND_PX = 40
YOY_TABLE_MAX_FULL_COLS = 8              # lebih dari ini → angka tabel diringkas (juta)
YOY_TABLE_COMPACT_UNIT = 1_000_000
YOY_TABLE_COMPACT_SUFFIX = " jt"
YOY_ARROW_GAP_PX = 6                     # jarak panah dari puncak batang tertinggi (piksel)
YOY_ARROW_LEN_PX = 22                    # panjang panah (piksel)
YOY_ARROW_WIDTH = 4
YOY_HEADROOM = 1.25                      # ruang atas sumbu y untuk panah + label
YOY_BARGAP = 0.35
YOY_PANEL_SPACING = 0.04


# ---------------------------------------------------------------------------
# 11. Antarmuka (UI) — modules/ui.py
# ---------------------------------------------------------------------------
# Tema "Modern Professional": area utama terang (off-white), sidebar navy lembut (semi-dark),
# aksen biru/cyan PLN. Warna yang sama juga ditulis di .streamlit/config.toml (warna widget bawaan).
UI_APP_NAME = "PLN UP3 Medan Utara"
UI_APP_TAGLINE = "Analitik Penjualan Tenaga Listrik"
UI_UNIT_LABEL = "PT PLN (Persero)"
UI_FONT_URL = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
               "&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap")
UI_FONT_BODY = 'Inter, "Segoe UI", Roboto, system-ui, -apple-system, sans-serif'
UI_FONT_HEAD = '"Plus Jakarta Sans", Inter, "Segoe UI", Roboto, system-ui, sans-serif'
UI_COLORS = {
    "blue": "#0072bc", "cyan": "#00a2e8", "blue_dark": "#0b4f86",
    "navy": "#0e2742", "navy2": "#14334f", "navy3": "#1b4166",
    "ink": "#1b2b41", "slate": "#5b6b7f", "muted": "#8a97a8",
    "line": "#e3e8ef", "bg": "#f8f9fa", "surface": "#ffffff", "tint": "#eaf5fc",
    "ok": "#1e9e6a", "ok_bg": "#e6f6ee", "bad": "#d14343", "bad_bg": "#fdecec",
    "warn": "#b7791f", "warn_bg": "#fff4e0", "off": "#5b6b7f", "off_bg": "#eef1f5",
    "side_ink": "#dce6f2", "side_muted": "#8fa3bb",
}
UI_RADIUS_CARD = "14px"
UI_RADIUS_PILL = "10px"
UI_FILENAME_MAX_CHARS = 28               # nama file lebih panjang dipotong "…" (nama lengkap di tooltip)

# Menu: (judul, ikon Material untuk tombol navigasi, ikon SVG banner, deskripsi singkat banner)
UI_MENU_META = {
    "1. Upload & ETL": ("cloud_upload", "upload",
                        "Unggah sumber data sekali, lalu jalankan ETL AP2T ke database klaster DB I & DB B."),
    "2. Analitik Pertumbuhan": ("trending_up", "trend",
                                "Pertumbuhan MoM, YoY kumulatif, capaian target, dan rincian per golongan & jenis tarif."),
    "3. Klaster Industri & Bisnis": ("factory", "layers",
                                     "Perbandingan sd per cluster KBLI, kontribusi pertumbuhan, dan rekonsiliasi file."),
    "4. Forecasting (ML)": ("insights", "chart",
                            "Perkiraan penjualan kWh beberapa bulan ke depan dari pola historis."),
    "5. Deteksi Anomali (ML)": ("troubleshoot", "alert",
                                "Pelanggan dengan pola konsumsi janggal sebagai daftar prioritas pengecekan."),
}
