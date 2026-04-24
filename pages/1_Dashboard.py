"""
dashboard_produksi.py
─────────────────────────────────────────────────────────────
Dashboard Monitoring Produksi Real-Time — Trial Version
Baca data dari GSheet yang sama dengan app_produksi_final_v3.py
Tidak ada write/update ke sheet — read-only.

Worksheet yang dibaca:
  • Proses      → status kerja operator (KOLOM_PROSES)
  • Waktu Kerja → check-in/out shift   (KOLOM_WAKTU_KERJA)
  • ABNORMAL    → laporan abnormal     (KOLOM_ABNORMAL)
  • MainData    → master part          (Part_No, Part_Name, LINE, SEC /PCS)

Cara jalankan:
  streamlit run dashboard_produksi.py --server.port 8502
"""

import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime, date
import pytz
import random
import time

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG — harus baris pertama
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Monitoring Produksi | PT ISI",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────────────────────
# CSS — Selaraskan dengan app utama (biru #261ad6) tapi
#        tambah elemen dashboard (card, badge, tabel)
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');

/* ── Base ── */
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background-color: #0f0f2e; color: #e8e8f0; }
.block-container { padding: 1.2rem 2rem 2rem !important; }
header { visibility: hidden; }

/* ── Metric Cards ── */
[data-testid="stMetric"] {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    padding: 1rem 1.2rem;
    backdrop-filter: blur(8px);
}
[data-testid="stMetricValue"] {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #00FF88 !important;
    font-size: 2rem !important;
}
[data-testid="stMetricLabel"] { color: rgba(255,255,255,0.55) !important; font-size: 0.78rem !important; }
[data-testid="stMetricDelta"] { font-size: 0.78rem !important; }

/* ── Kanban Card ── */
.kcard {
    background: rgba(255,255,255,0.07);
    border-radius: 10px;
    padding: 12px 14px;
    margin-bottom: 10px;
    border-left: 4px solid #00FF88;
    font-size: 0.85rem;
    line-height: 1.65;
}
.kcard.done   { border-left-color: #a0a0c0; }
.kcard.warn   { border-left-color: #FFB547; }
.kcard b      { color: #ffffff; }
.kcard .small { color: rgba(255,255,255,0.45); font-size: 0.75rem; }

/* ── Badge ── */
.badge {
    display: inline-block;
    font-size: 0.68rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 99px;
    font-family: 'IBM Plex Mono', monospace;
    letter-spacing: 0.04em;
}
.badge-green  { background: rgba(0,255,136,0.15); color: #00FF88; border: 1px solid rgba(0,255,136,0.3); }
.badge-amber  { background: rgba(255,181,71,0.15); color: #FFB547;  border: 1px solid rgba(255,181,71,0.3); }
.badge-gray   { background: rgba(160,160,192,0.15); color: #a0a0c0; border: 1px solid rgba(160,160,192,0.3); }
.badge-red    { background: rgba(255,80,80,0.15); color: #FF5050;   border: 1px solid rgba(255,80,80,0.3); }

/* ── Section header ── */
.sec-head {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    color: rgba(255,255,255,0.35);
    text-transform: uppercase;
    margin: 1.2rem 0 0.6rem;
}

/* ── Divider ── */
hr { border-color: rgba(255,255,255,0.08) !important; margin: 0.8rem 0 !important; }

/* ── Tabel edit (data editor) ── */
[data-testid="stDataEditor"] { border-radius: 10px; overflow: hidden; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0a0a20 !important;
    border-right: 1px solid rgba(255,255,255,0.06);
}
[data-testid="stSidebar"] * { color: #d0d0e8 !important; }

/* ── Button ── */
div.stButton > button {
    background: #00FF88 !important;
    color: #0a0a20 !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.82rem !important;
    padding: 0.45rem 1rem !important;
}
div.stButton > button:hover { background: #00e07a !important; }

/* ── Selectbox / Input ── */
div[data-testid="stSelectbox"] > div,
div[data-testid="stTextInput"] input {
    background: rgba(255,255,255,0.06) !important;
    color: #e8e8f0 !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 99px; }

/* ── Timestamp live ── */
.live-dot {
    display: inline-block; width: 7px; height: 7px;
    background: #00FF88; border-radius: 50%;
    margin-right: 6px; animation: pulse 1.4s infinite;
}
@keyframes pulse {
    0%,100% { opacity: 1; transform: scale(1); }
    50%      { opacity: 0.4; transform: scale(0.7); }
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# KONEKSI & KONSTANTA
# ─────────────────────────────────────────────────────────────
URL_KITA = "https://docs.google.com/spreadsheets/d/1uDmbbLhFsMdGSnozbRBMwEDPP2T20HqpEnJGYd2P390/edit"

conn = st.connection("gsheets", type=GSheetsConnection)

def get_wib():
    return datetime.now(pytz.timezone('Asia/Jakarta')).replace(tzinfo=None)

def fmt_time(dt):
    return dt.strftime("%H:%M:%S")

def fmt_pct(val, default="—"):
    try:
        return f"{float(str(val).replace('%','')):.1f}%"
    except Exception:
        return default


# ─────────────────────────────────────────────────────────────
# CACHED READERS — TTL diselaraskan dengan app utama
# Semua READ ONLY — tidak ada write ke sheet dari dashboard ini
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=15)
def load_proses(url):
    """
    Worksheet: Proses
    Kolom: Tanggal, Nama, NIK, Part_No, Part_Name, Model, Line,
           Urutan_Proses, Actual_Line, Sec_Pcs, Waktu_Mulai,
           Waktu_Selesai, ACT, NG, %_Prod, Total Istirahat,
           Rasio_NG, Total_Jam, Status
    """
    df = conn.read(spreadsheet=url, worksheet="Proses", ttl=15)
    df.columns = df.columns.str.strip()
    # Normalisasi kolom angka
    for col in ['ACT', 'NG', 'Total_Jam', 'Sec_Pcs']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    if 'Tanggal' in df.columns:
        df['Tanggal'] = pd.to_datetime(df['Tanggal'], errors='coerce').dt.date
    return df

@st.cache_data(ttl=20)
def load_waktu_kerja(url):
    """
    Worksheet: Waktu Kerja
    Kolom: Tanggal, Nama, NIK, Check-In, Check-Out, Total_Jam, Aktivitas
    """
    df = conn.read(spreadsheet=url, worksheet="Waktu Kerja", ttl=20)
    df.columns = df.columns.str.strip()
    if 'Tanggal' in df.columns:
        df['Tanggal'] = pd.to_datetime(df['Tanggal'], errors='coerce').dt.date
    if 'Total_Jam' in df.columns:
        df['Total_Jam'] = pd.to_numeric(df['Total_Jam'], errors='coerce').fillna(0)
    return df

@st.cache_data(ttl=20)
def load_abnormal(url):
    """
    Worksheet: ABNORMAL
    Kolom: Tanggal, Mesin, Part_No, Model, Part_Name,
           Urutan_Proses, Operator, Kode_Abnormal,
           Uraian_Abnormal, Total_Waktu, Keterangan
    """
    df = conn.read(spreadsheet=url, worksheet="ABNORMAL", ttl=20)
    df.columns = df.columns.str.strip()
    if 'Tanggal' in df.columns:
        df['Tanggal'] = pd.to_datetime(df['Tanggal'], errors='coerce').dt.date
    if 'Total_Waktu' in df.columns:
        df['Total_Waktu'] = pd.to_numeric(df['Total_Waktu'], errors='coerce').fillna(0)
    return df

@st.cache_data(ttl=3600)
def load_main_data(url):
    """Worksheet: MainData — Part_No, Part_Name, LINE, URUTAN, SEC /PCS"""
    df = conn.read(spreadsheet=url, worksheet="MainData", ttl=3600)
    df.columns = df.columns.str.strip()
    return df


# ─────────────────────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────────────────────
try:
    df_proses   = load_proses(URL_KITA)
    df_waktu    = load_waktu_kerja(URL_KITA)
    df_abnormal = load_abnormal(URL_KITA)
    df_main     = load_main_data(URL_KITA)
    data_ok     = True
except Exception as e:
    st.error(f"❌ Gagal memuat data: {e}")
    df_proses = df_waktu = df_abnormal = df_main = pd.DataFrame()
    data_ok   = False

hari_ini = date.today()

# Filter hanya data hari ini
df_proses_hari  = df_proses[df_proses['Tanggal'] == hari_ini] if not df_proses.empty and 'Tanggal' in df_proses.columns else pd.DataFrame()
df_waktu_hari   = df_waktu[df_waktu['Tanggal']   == hari_ini] if not df_waktu.empty  and 'Tanggal' in df_waktu.columns  else pd.DataFrame()
df_abnormal_hari = df_abnormal[df_abnormal['Tanggal'] == hari_ini] if not df_abnormal.empty and 'Tanggal' in df_abnormal.columns else pd.DataFrame()

# Derived data
df_running  = df_proses_hari[df_proses_hari['Status'] == 'START'] if not df_proses_hari.empty else pd.DataFrame()
df_finish   = df_proses_hari[df_proses_hari['Status'] == 'FINISH'] if not df_proses_hari.empty else pd.DataFrame()
df_checkin  = df_waktu_hari[df_waktu_hari['Check-Out'].isna() | (df_waktu_hari['Check-Out'].astype(str).str.strip() == "")] if not df_waktu_hari.empty else pd.DataFrame()


# ─────────────────────────────────────────────────────────────
# SIDEBAR — filter & kontrol
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Dashboard Control")
    st.markdown("---")

    # Auto-refresh
    auto_refresh = st.toggle("🔄 Auto Refresh", value=True)
    refresh_interval = st.select_slider(
        "Interval (detik)", options=[15, 30, 60, 120], value=30
    )

    st.markdown("---")

    # Filter Line
    all_lines = ["Semua Line"]
    if not df_proses_hari.empty and 'Actual_Line' in df_proses_hari.columns:
        lines = df_proses_hari['Actual_Line'].dropna().unique().tolist()
        all_lines += sorted([str(l) for l in lines if str(l).strip()])
    filter_line = st.selectbox("🏭 Filter Line", options=all_lines)

    # Filter Status
    filter_status = st.selectbox("📊 Filter Status", options=["Semua", "RUNNING", "FINISH"])

    st.markdown("---")

    # Navigasi kembali ke app utama
    if st.button("⬅️ Kembali ke Scan App"):
        st.switch_page("app_produksi_final_v3.py")

    st.markdown("---")
    # Tombol clear cache manual
    if st.button("🗑️ Clear Cache & Refresh"):
        load_proses.clear()
        load_waktu_kerja.clear()
        load_abnormal.clear()
        st.rerun()

    st.markdown(
        f"<div class='small' style='color:rgba(255,255,255,0.3);font-size:0.72rem'>"
        f"Data hari ini: {hari_ini.strftime('%d %b %Y')}<br>"
        f"Cache refresh setiap {refresh_interval}s</div>",
        unsafe_allow_html=True
    )


# ─────────────────────────────────────────────────────────────
# APPLY FILTER ke df_running & df_finish
# ─────────────────────────────────────────────────────────────
def apply_filter(df):
    if df.empty:
        return df
    result = df.copy()
    if filter_line != "Semua Line" and 'Actual_Line' in result.columns:
        result = result[result['Actual_Line'].astype(str).str.strip() == filter_line]
    return result

df_running_f = apply_filter(df_running)
df_finish_f  = apply_filter(df_finish)


# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────
now_str = fmt_time(get_wib())
st.markdown(
    f"""
    <div style='display:flex;align-items:center;justify-content:space-between;
                margin-bottom:0.5rem;'>
      <div>
        <div style='font-size:1.5rem;font-weight:700;color:#ffffff;
                    font-family:"IBM Plex Mono",monospace;'>
          📊 Monitoring Produksi
        </div>
        <div style='font-size:0.78rem;color:rgba(255,255,255,0.4);margin-top:2px;'>
          PT Indosafety Sentosa — Dept. Press
        </div>
      </div>
      <div style='text-align:right;'>
        <div style='font-size:0.72rem;color:rgba(255,255,255,0.35);'>LAST UPDATED</div>
        <div style='font-family:"IBM Plex Mono",monospace;font-size:1.1rem;
                    color:#00FF88;font-weight:600;'>
          <span class='live-dot'></span>{now_str} WIB
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)
st.markdown("<hr>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# ROW 1 — KPI METRICS
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec-head'>📈 Ringkasan Shift Hari Ini</div>", unsafe_allow_html=True)

m1, m2, m3, m4, m5 = st.columns(5)

# Operator aktif (check-in, belum checkout)
op_aktif = len(df_checkin) if not df_checkin.empty else 0
m1.metric("👷 Operator Aktif", op_aktif,
          delta=f"dari {len(df_waktu_hari)} total checkin")

# Proses running
proses_running = len(df_running)
m2.metric("⚡ Proses Running", proses_running,
          delta="saat ini" if proses_running > 0 else "idle")

# Total output hari ini (ACT dari FINISH)
total_act = int(df_finish['ACT'].sum()) if not df_finish.empty else 0
m3.metric("📦 Total Output", f"{total_act:,} Pcs",
          delta=f"{len(df_finish)} job selesai")

# Total NG
total_ng = int(df_finish['NG'].sum()) if not df_finish.empty else 0
rasio_ng = round((total_ng / total_act * 100), 2) if total_act > 0 else 0
m4.metric("❌ Total NG", f"{total_ng:,} Pcs",
          delta=f"{rasio_ng}% ratio",
          delta_color="inverse")

# Total waktu abnormal hari ini
total_abnormal_menit = int(df_abnormal_hari['Total_Waktu'].sum()) if not df_abnormal_hari.empty else 0
m5.metric("⚠️ Downtime (menit)", total_abnormal_menit,
          delta=f"{len(df_abnormal_hari)} kejadian",
          delta_color="inverse")

st.markdown("<hr>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# ROW 2 — KANBAN BOARD (RUNNING vs FINISH)
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec-head'>📋 Status Kerja Real-Time</div>", unsafe_allow_html=True)

col_run, col_done = st.columns(2, gap="medium")

with col_run:
    badge_run = f"<span class='badge badge-green'>{len(df_running_f)} AKTIF</span>"
    st.markdown(f"### ⚡ In Progress &nbsp;{badge_run}", unsafe_allow_html=True)

    if df_running_f.empty:
        st.markdown(
            "<div class='kcard' style='border-left-color:#a0a0c0;opacity:0.5;'>"
            "Tidak ada proses aktif saat ini.</div>",
            unsafe_allow_html=True
        )
    else:
        for _, row in df_running_f.iterrows():
            nama       = row.get('Nama', '—')
            part_no    = str(row.get('Part_No', '—')).replace('.0','')
            part_name  = row.get('Part_Name', '—')
            urutan     = row.get('Urutan_Proses', '—')
            actual_line = row.get('Actual_Line', '—')
            mulai      = row.get('Waktu_Mulai', '—')
            sec_pcs    = row.get('Sec_Pcs', 0)

            # Hitung durasi live
            try:
                dt_mulai = datetime.strptime(
                    f"{hari_ini} {str(mulai).split(' ')[-1]}", "%Y-%m-%d %H:%M:%S"
                )
                menit_berjalan = int((get_wib() - dt_mulai).total_seconds() / 60)
                durasi_str = f"{menit_berjalan} mnt"
            except Exception:
                durasi_str = "—"

            st.markdown(
                f"""<div class='kcard'>
                <b>{part_name}</b> &nbsp;
                <span class='badge badge-green'>RUNNING</span><br>
                <span class='small'>Part No: {part_no} &nbsp;|&nbsp; {urutan} &nbsp;|&nbsp; Line: {actual_line}</span><br>
                👷 {nama}<br>
                <span class='small'>⏱ Mulai: {str(mulai).split(' ')[-1]} &nbsp;|&nbsp;
                Berjalan: {durasi_str} &nbsp;|&nbsp; Std: {sec_pcs} s/pcs</span>
                </div>""",
                unsafe_allow_html=True
            )

with col_done:
    badge_done = f"<span class='badge badge-gray'>{len(df_finish_f)} SELESAI</span>"
    st.markdown(f"### ✅ Done (Hari Ini) &nbsp;{badge_done}", unsafe_allow_html=True)

    if df_finish_f.empty:
        st.markdown(
            "<div class='kcard done' style='opacity:0.5;'>"
            "Belum ada proses yang selesai hari ini.</div>",
            unsafe_allow_html=True
        )
    else:
        # Tampilkan 8 terakhir, terbaru di atas
        for _, row in df_finish_f.iloc[::-1].head(8).iterrows():
            nama      = row.get('Nama', '—')
            part_name = row.get('Part_Name', '—')
            part_no   = str(row.get('Part_No', '—')).replace('.0','')
            act       = int(row.get('ACT', 0))
            ng        = int(row.get('NG', 0))
            pct       = row.get('%_Prod', '—')
            selesai   = row.get('Waktu_Selesai', '—')
            line      = row.get('Actual_Line', '—')

            # Badge %Prod
            try:
                pct_val = float(str(pct).replace('%', ''))
                pct_badge = (
                    f"<span class='badge badge-green'>{pct_val:.0f}%</span>" if pct_val >= 85
                    else f"<span class='badge badge-amber'>{pct_val:.0f}%</span>" if pct_val >= 60
                    else f"<span class='badge badge-red'>{pct_val:.0f}%</span>"
                )
            except Exception:
                pct_badge = f"<span class='badge badge-gray'>{pct}</span>"

            st.markdown(
                f"""<div class='kcard done'>
                <b>{part_name}</b> &nbsp;{pct_badge}<br>
                <span class='small'>Part No: {part_no} &nbsp;|&nbsp; Line: {line}</span><br>
                👷 {nama}<br>
                <span class='small'>✅ Selesai: {str(selesai).split(' ')[-1]} &nbsp;|&nbsp;
                ACT: {act:,} pcs &nbsp;|&nbsp; NG: {ng} pcs</span>
                </div>""",
                unsafe_allow_html=True
            )

st.markdown("<hr>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# ROW 3 — TABEL DATA LENGKAP (read + edit untuk perbaikan data)
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec-head'>🗂 Data Detail & Perbaikan Data</div>", unsafe_allow_html=True)

tab_proses, tab_waktu, tab_abnormal = st.tabs([
    "📋 Data Proses", "⏰ Waktu Kerja", "⚠️ Abnormal"
])

# ── Tab Proses ──
with tab_proses:
    st.markdown(
        "Tabel di bawah bisa diedit langsung. "
        "**Tekan Enter / klik di luar sel** untuk konfirmasi. "
        "Klik **Simpan Perbaikan** untuk menyimpan ke GSheet.",
        unsafe_allow_html=False
    )

    if df_proses_hari.empty:
        st.info("Tidak ada data proses hari ini.")
    else:
        # Kolom yang ditampilkan & bisa diedit
        KOLOM_TAMPIL_PROSES = [
            'Nama', 'Part_No', 'Part_Name', 'Urutan_Proses', 'Actual_Line',
            'Waktu_Mulai', 'Waktu_Selesai', 'ACT', 'NG', '%_Prod',
            'Total Istirahat', 'Rasio_NG', 'Total_Jam', 'Status'
        ]
        # Filter kolom yang benar-benar ada
        kolom_ada = [c for c in KOLOM_TAMPIL_PROSES if c in df_proses_hari.columns]
        df_tampil = df_proses_hari[kolom_ada].copy()

        # Kolom yang boleh diedit (hanya untuk koreksi data, bukan Status)
        KOLOM_EDIT = ['ACT', 'NG', 'Waktu_Selesai', 'Total Istirahat']
        kolom_disabled = [c for c in kolom_ada if c not in KOLOM_EDIT]

        edited_proses = st.data_editor(
            df_tampil,
            disabled=kolom_disabled,
            use_container_width=True,
            key="editor_proses",
            column_config={
                "ACT": st.column_config.NumberColumn("ACT", min_value=0),
                "NG":  st.column_config.NumberColumn("NG",  min_value=0),
                "Status": st.column_config.SelectboxColumn(
                    "Status", options=["START", "FINISH"]
                ),
            }
        )

        col_save, col_info = st.columns([1, 3])
        with col_save:
            if st.button("💾 Simpan Perbaikan Proses", use_container_width=True):
                try:
                    # Gabung kembali dengan baris yang tidak ditampilkan (data hari lain)
                    df_lain  = df_proses[df_proses['Tanggal'] != hari_ini].copy()
                    df_hari_updated = df_proses_hari.copy()
                    df_hari_updated[kolom_ada] = edited_proses[kolom_ada].values

                    df_final = pd.concat([df_lain, df_hari_updated], ignore_index=True)
                    conn.update(spreadsheet=URL_KITA, worksheet="Proses", data=df_final)
                    load_proses.clear()
                    st.success("✅ Data proses berhasil diperbaiki!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Gagal simpan: {e}")
        with col_info:
            st.caption(
                "⚠️ Hanya kolom **ACT, NG, Waktu_Selesai, Total Istirahat** yang bisa diubah. "
                "Kolom lain terkunci untuk mencegah perubahan tidak sengaja."
            )

# ── Tab Waktu Kerja ──
with tab_waktu:
    st.markdown("Data check-in/check-out operator hari ini. Edit untuk koreksi jika ada data salah.")

    if df_waktu_hari.empty:
        st.info("Tidak ada data check-in hari ini.")
    else:
        KOLOM_TAMPIL_WAKTU = ['Nama', 'NIK', 'Check-In', 'Check-Out', 'Total_Jam', 'Aktivitas']
        kolom_ada_waktu    = [c for c in KOLOM_TAMPIL_WAKTU if c in df_waktu_hari.columns]
        df_tampil_waktu    = df_waktu_hari[kolom_ada_waktu].copy()

        KOLOM_EDIT_WAKTU   = ['Check-In', 'Check-Out', 'Total_Jam', 'Aktivitas']
        kolom_dis_waktu    = [c for c in kolom_ada_waktu if c not in KOLOM_EDIT_WAKTU]

        edited_waktu = st.data_editor(
            df_tampil_waktu,
            disabled=kolom_dis_waktu,
            use_container_width=True,
            key="editor_waktu",
            column_config={
                "Total_Jam": st.column_config.NumberColumn("Total Jam", min_value=0, format="%.2f"),
                "Aktivitas": st.column_config.SelectboxColumn(
                    "Aktivitas", options=["Mulai Shift", "Shift Complete", "Lainnya"]
                ),
            }
        )

        col_sv2, col_inf2 = st.columns([1, 3])
        with col_sv2:
            if st.button("💾 Simpan Perbaikan Waktu Kerja", use_container_width=True):
                try:
                    df_lain_waktu    = df_waktu[df_waktu['Tanggal'] != hari_ini].copy()
                    df_hari_wk_upd   = df_waktu_hari.copy()
                    df_hari_wk_upd[kolom_ada_waktu] = edited_waktu[kolom_ada_waktu].values
                    df_final_waktu   = pd.concat([df_lain_waktu, df_hari_wk_upd], ignore_index=True)
                    conn.update(spreadsheet=URL_KITA, worksheet="Waktu Kerja", data=df_final_waktu)
                    load_waktu_kerja.clear()
                    st.success("✅ Data waktu kerja berhasil diperbaiki!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Gagal simpan: {e}")
        with col_inf2:
            st.caption(
                "⚠️ Hanya kolom **Check-In, Check-Out, Total_Jam, Aktivitas** yang bisa diubah."
            )

# ── Tab Abnormal ──
with tab_abnormal:
    st.markdown("Laporan abnormal/downtime hari ini.")

    if df_abnormal_hari.empty:
        st.success("✅ Tidak ada laporan abnormal hari ini.")
    else:
        KOLOM_TAMPIL_AB = [
            'Mesin', 'Part_No', 'Part_Name', 'Operator',
            'Kode_Abnormal', 'Uraian_Abnormal', 'Total_Waktu', 'Keterangan'
        ]
        kolom_ada_ab  = [c for c in KOLOM_TAMPIL_AB if c in df_abnormal_hari.columns]
        df_tampil_ab  = df_abnormal_hari[kolom_ada_ab].copy()

        KOLOM_EDIT_AB = ['Keterangan', 'Total_Waktu']
        kolom_dis_ab  = [c for c in kolom_ada_ab if c not in KOLOM_EDIT_AB]

        edited_ab = st.data_editor(
            df_tampil_ab,
            disabled=kolom_dis_ab,
            use_container_width=True,
            key="editor_abnormal",
            column_config={
                "Total_Waktu": st.column_config.NumberColumn("Total Waktu (mnt)", min_value=0),
            }
        )

        col_sv3, col_inf3 = st.columns([1, 3])
        with col_sv3:
            if st.button("💾 Simpan Perbaikan Abnormal", use_container_width=True):
                try:
                    df_lain_ab   = df_abnormal[df_abnormal['Tanggal'] != hari_ini].copy()
                    df_hari_ab_upd = df_abnormal_hari.copy()
                    df_hari_ab_upd[kolom_ada_ab] = edited_ab[kolom_ada_ab].values
                    df_final_ab  = pd.concat([df_lain_ab, df_hari_ab_upd], ignore_index=True)
                    conn.update(spreadsheet=URL_KITA, worksheet="ABNORMAL", data=df_final_ab)
                    load_abnormal.clear()
                    st.success("✅ Data abnormal berhasil diperbaiki!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Gagal simpan: {e}")
        with col_inf3:
            st.caption("⚠️ Hanya kolom **Keterangan** dan **Total_Waktu** yang bisa diubah.")

st.markdown("<hr>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# ROW 4 — CHART PERFORMA
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec-head'>📊 Analisis Performa</div>", unsafe_allow_html=True)

col_ch1, col_ch2 = st.columns(2, gap="medium")

with col_ch1:
    st.markdown("**Output per Operator (Hari Ini)**")
    if not df_finish.empty and 'Nama' in df_finish.columns and 'ACT' in df_finish.columns:
        df_per_op = (
            df_finish.groupby('Nama')['ACT']
            .sum().reset_index()
            .rename(columns={'Nama': 'Operator', 'ACT': 'Total Output'})
            .sort_values('Total Output', ascending=False)
        )
        st.bar_chart(df_per_op.set_index('Operator'), color="#00FF88", height=260)
    else:
        st.info("Belum ada data output hari ini.")

with col_ch2:
    st.markdown("**Distribusi Kode Abnormal**")
    if not df_abnormal_hari.empty and 'Kode_Abnormal' in df_abnormal_hari.columns:
        df_ab_dist = (
            df_abnormal_hari.groupby('Kode_Abnormal')['Total_Waktu']
            .sum().reset_index()
            .rename(columns={'Kode_Abnormal': 'Kode', 'Total_Waktu': 'Total Menit'})
            .sort_values('Total Menit', ascending=False)
        )
        st.bar_chart(df_ab_dist.set_index('Kode'), color="#FFB547", height=260)
    else:
        st.success("✅ Tidak ada downtime hari ini.")

st.markdown("<hr>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# ROW 5 — TRIAL INFO PANEL (khusus mode trial sebelum deploy)
# ─────────────────────────────────────────────────────────────
with st.expander("🧪 TRIAL MODE — Checklist Sebelum Deploy", expanded=False):
    st.markdown("""
    Gunakan checklist ini untuk verifikasi sebelum deploy ke production:

    **Data Integrity**
    - [ ] Kolom `Tanggal` terbaca sebagai date (bukan string)
    - [ ] Kolom `ACT`, `NG`, `Total_Jam` terbaca sebagai angka
    - [ ] Filter hari ini menghasilkan data yang benar
    - [ ] Kanban RUNNING hanya tampilkan status `START`
    - [ ] Kanban DONE hanya tampilkan status `FINISH`

    **Koneksi & Performa**
    - [ ] Tidak ada error saat load pertama
    - [ ] Auto-refresh bekerja tanpa error 429
    - [ ] Simpan perbaikan data berhasil tanpa overwrite data lain
    - [ ] Cache di-clear setelah simpan

    **Tampilan**
    - [ ] Metric terbaca jelas di layar HP
    - [ ] Kanban card tidak terpotong di mobile
    - [ ] Tabel editor bisa di-scroll horizontal

    **Edge Case**
    - [ ] Tampilan saat data kosong (hari ini belum ada produksi)
    - [ ] Tampilan saat API gagal (error message muncul)
    - [ ] Filter Line bekerja dengan benar
    """)

    st.markdown("**Statistik Data Saat Ini:**")
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Total baris Proses",   len(df_proses) if data_ok else "ERR")
    col_s2.metric("Total baris WK",       len(df_waktu)  if data_ok else "ERR")
    col_s3.metric("Total baris Abnormal", len(df_abnormal) if data_ok else "ERR")

    if data_ok and not df_proses.empty:
        st.markdown("**Sample kolom Proses:**")
        st.code(", ".join(df_proses.columns.tolist()))
    if data_ok and not df_waktu.empty:
        st.markdown("**Sample kolom Waktu Kerja:**")
        st.code(", ".join(df_waktu.columns.tolist()))


# ─────────────────────────────────────────────────────────────
# AUTO REFRESH
# ─────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(refresh_interval)
    load_proses.clear()
    load_waktu_kerja.clear()
    load_abnormal.clear()
    st.rerun()
