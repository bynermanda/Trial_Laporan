"""
App.py — Laporan Produksi Dept. Press PT Indosafety Sentosa
Versi: Supabase (PostgreSQL)

PERBAIKAN dari versi sebelumnya:
  1. Semua .get() dibungkus helper safe_get() — tidak akan crash walau None
  2. Nama kolom Supabase diseragamkan (tanpa spasi, tanpa tanda -)
     "Total Istirahat" → "Total_Istirahat"
     "Check-In"        → "Check_In"
     "Check-Out"       → "Check_Out"
  3. Parsing Waktu_Mulai/Check_In robust terhadap format timezone suffix
  4. load_proses_aktif_nik tidak di-.clear() berulang — pakai query langsung
  5. Guard None di semua titik yang akses data dari Supabase
"""

import streamlit as st
import streamlit.components.v1 as components
from streamlit_qrcode_scanner import qrcode_scanner
from supabase import create_client, Client
import pandas as pd
import pytz
from datetime import datetime, timedelta, date
import time
import random

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG — wajib baris pertama
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Laporan Produksi Press PT. ISI", layout="wide")


# ─────────────────────────────────────────────────────────────
# KONEKSI SUPABASE
# .streamlit/secrets.toml:
#   [supabase]
#   url = "https://xxx.supabase.co"
#   key = "eyJ..."
# ─────────────────────────────────────────────────────────────
@st.cache_resource
def get_supabase() -> Client:
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["key"]
    )

supabase = get_supabase()


# ─────────────────────────────────────────────────────────────
# NAMA KOLOM SUPABASE
# Semua kolom tanpa spasi dan tanpa tanda "-" agar aman di
# Python Supabase client. Sesuaikan DDL tabel Supabase dengan
# nama-nama ini.
#
# DDL yang benar (jalankan di Supabase SQL Editor):
#
# CREATE TABLE proses (
#   id               BIGSERIAL PRIMARY KEY,
#   created_at       TIMESTAMPTZ DEFAULT NOW(),
#   "Tanggal"        DATE,
#   "Nama"           TEXT,
#   "NIK"            TEXT,
#   "Part_No"        TEXT,
#   "Part_Name"      TEXT,
#   "Model"          TEXT,
#   "Line"           TEXT,
#   "Waktu_Mulai"    TEXT,
#   "Waktu_Selesai"  TEXT,
#   "ACT"            INTEGER DEFAULT 0,
#   "NG"             INTEGER DEFAULT 0,
#   "Status"         TEXT DEFAULT 'START',
#   "Urutan_Proses"  TEXT,
#   "Pct_Prod"       TEXT,
#   "Rasio_NG"       TEXT,
#   "Total_Jam"      NUMERIC(6,2),
#   "Total_Istirahat" INTEGER DEFAULT 0,
#   "Actual_Line"    TEXT,
#   "Sec_Pcs"        NUMERIC(8,2) DEFAULT 0
# );
#
# CREATE TABLE waktu_kerja (
#   id          BIGSERIAL PRIMARY KEY,
#   created_at  TIMESTAMPTZ DEFAULT NOW(),
#   "Tanggal"   DATE,
#   "Nama"      TEXT,
#   "NIK"       TEXT,
#   "Check_In"  TEXT,
#   "Check_Out" TEXT,
#   "Total_Jam" NUMERIC(6,2) DEFAULT 0,
#   "Aktivitas" TEXT DEFAULT 'Mulai Shift'
# );
#
# CREATE TABLE abnormal (
#   id                BIGSERIAL PRIMARY KEY,
#   created_at        TIMESTAMPTZ DEFAULT NOW(),
#   "Tanggal"         DATE,
#   "Mesin"           TEXT,
#   "Part_No"         TEXT,
#   "Model"           TEXT,
#   "Part_Name"       TEXT,
#   "Urutan_Proses"   TEXT,
#   "Operator"        TEXT,
#   "Kode_Abnormal"   TEXT,
#   "Uraian_Abnormal" TEXT,
#   "Total_Waktu"     INTEGER DEFAULT 0,
#   "Keterangan"      TEXT
# );
#
# CREATE TABLE master_karyawan (
#   id      BIGSERIAL PRIMARY KEY,
#   "NIK"   TEXT UNIQUE NOT NULL,
#   "Nama"  TEXT NOT NULL,
#   "Aktif" BOOLEAN DEFAULT TRUE
# );
#
# CREATE TABLE main_data (
#   id          BIGSERIAL PRIMARY KEY,
#   "Part_No"   TEXT UNIQUE NOT NULL,
#   "Part_Name" TEXT,
#   "MODEL"     TEXT,
#   "LINE"      TEXT,
#   "URUTAN"    TEXT,
#   "SEC_PCS"   NUMERIC(8,2) DEFAULT 0
# );
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
# HELPER AMAN — tidak crash walau value None atau bukan dict
# ─────────────────────────────────────────────────────────────
def safe_get(obj, key: str, default=None):
    """
    Ambil nilai dari dict dengan aman.
    Menggantikan obj.get(key, default) yang crash kalau obj adalah None.
    """
    if obj is None or not isinstance(obj, dict):
        return default
    return obj.get(key, default)


def safe_float(val, default=0.0) -> float:
    """Konversi ke float dengan aman."""
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0) -> int:
    """Konversi ke int dengan aman."""
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def parse_waktu(waktu_str) -> str:
    """
    Normalisasi string waktu dari Supabase menjadi HH:MM:SS.
    Supabase bisa return "08:00:00", "08:00:00+07", "2024-01-01T08:00:00", dll.
    """
    if not waktu_str:
        return "00:00:00"
    s = str(waktu_str).strip()
    # Hapus timezone suffix "+07", "+07:00", "Z"
    for sep in ['+', 'Z']:
        if sep in s:
            s = s.split(sep)[0]
    # Kalau ada T (ISO format), ambil bagian waktu saja
    if 'T' in s:
        s = s.split('T')[1]
    # Hapus microsecond
    if '.' in s:
        s = s.split('.')[0]
    return s.strip()


def parse_datetime_dari_row(tgl_str, waktu_str, fallback=None):
    """
    Bangun datetime dari kolom Tanggal + Waktu_Mulai / Check_In.
    Return fallback (default: waktu sekarang WIB) jika gagal.
    """
    if fallback is None:
        fallback = get_waktu_wib()
    try:
        tgl = str(tgl_str).split('T')[0].strip() if tgl_str else date.today().isoformat()
        jam = parse_waktu(waktu_str)
        return datetime.strptime(f"{tgl} {jam}", "%Y-%m-%d %H:%M:%S")
    except Exception:
        return fallback


# ─────────────────────────────────────────────────────────────
# FUNGSI WAKTU
# ─────────────────────────────────────────────────────────────
def get_waktu_wib() -> datetime:
    return datetime.now(pytz.timezone('Asia/Jakarta')).replace(tzinfo=None)


def get_checkin_datetime(checkin_row: dict, waktu_out: datetime) -> datetime:
    """Parse Check_In datetime, handle cross-midnight."""
    dt_in = parse_datetime_dari_row(
        safe_get(checkin_row, 'Tanggal'),
        safe_get(checkin_row, 'Check_In'),
        fallback=waktu_out - timedelta(hours=8)
    )
    if dt_in > waktu_out:
        dt_in -= timedelta(days=1)
    return dt_in


# ─────────────────────────────────────────────────────────────
# HELPER NIK
# ─────────────────────────────────────────────────────────────
def bersihkan_nik(nik_raw) -> str:
    return str(nik_raw).replace("'", "").replace(".", "").strip()


# ─────────────────────────────────────────────────────────────
# SAFE SUPABASE WRAPPER — retry pada network error
# ─────────────────────────────────────────────────────────────
def safe_sb(func, max_retries=3, op="operasi"):
    """
    Jalankan query Supabase dengan retry otomatis.
    Return response object, atau raise exception setelah max_retries.
    """
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            err = str(e).lower()
            retryable = any(c in err for c in ["timeout", "connection", "network", "503", "502"])
            if retryable and attempt < max_retries - 1:
                wait = round((2 ** (attempt + 1)) + random.uniform(0, 1), 1)
                st.warning(f"⏳ {op} — retry dalam {wait}s... ({attempt+1}/{max_retries-1})")
                time.sleep(wait)
            else:
                raise e


# ─────────────────────────────────────────────────────────────
# CACHED READERS
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_master_karyawan():
    res = safe_sb(
        lambda: supabase.table("master_karyawan")
            .select("NIK, Nama").eq("Aktif", True).execute(),
        op="Load master karyawan"
    )
    return pd.DataFrame(res.data) if (res and res.data) else pd.DataFrame()


@st.cache_data(ttl=3600)
def load_main_data():
    res = safe_sb(
        lambda: supabase.table("main_data").select("*").execute(),
        op="Load main data"
    )
    return pd.DataFrame(res.data) if (res and res.data) else pd.DataFrame()


def query_proses_aktif(nik_clean: str):
    """
    Query langsung (tanpa cache) — dipakai saat butuh data fresh:
    login operator, konfirmasi START, fallback row_id.
    Return: dict baris | None
    """
    try:
        res = safe_sb(
            lambda: supabase.table("proses")
                .select("*")
                .eq("NIK", nik_clean)
                .eq("Status", "START")
                .order("id", desc=True)
                .limit(1)
                .execute(),
            op="Query proses aktif"
        )
        return res.data[0] if (res and res.data) else None
    except Exception as e:
        st.error(f"Gagal query proses aktif: {e}")
        return None


@st.cache_data(ttl=10)
def load_proses_aktif_nik_cached(nik_clean: str):
    """Versi cache TTL=10s — dipakai untuk cek checkout dan kanban board."""
    try:
        res = safe_sb(
            lambda: supabase.table("proses")
                .select("*")
                .eq("NIK", nik_clean)
                .eq("Status", "START")
                .order("id", desc=True)
                .limit(1)
                .execute(),
            op="Load proses aktif cached"
        )
        return res.data[0] if (res and res.data) else None
    except Exception:
        return None


def query_waktu_kerja_aktif(nik_clean: str):
    """
    Query langsung check-in aktif (Check_Out IS NULL) untuk NIK hari ini.
    Return: dict baris | None
    """
    try:
        hari_ini = date.today().isoformat()
        res = safe_sb(
            lambda: supabase.table("waktu_kerja")
                .select("*")
                .eq("NIK", nik_clean)
                .eq("Tanggal", hari_ini)
                .is_("Check_Out", "null")
                .order("id", desc=True)
                .limit(1)
                .execute(),
            op="Query waktu kerja aktif"
        )
        return res.data[0] if (res and res.data) else None
    except Exception as e:
        st.error(f"Gagal query waktu kerja aktif: {e}")
        return None


def cek_sudah_checkin(nik: str) -> bool:
    return query_waktu_kerja_aktif(bersihkan_nik(nik)) is not None


# ─────────────────────────────────────────────────────────────
# JAVASCRIPT
# ─────────────────────────────────────────────────────────────
components.html("""
<script>
window.parent.addEventListener('beforeunload', function(e) {
    var msg = 'Data sedang diproses. Jika refresh, sesi scan akan hilang!';
    (e || window.event).returnValue = msg; return msg;
});
(function() {
    var m = window.parent.document.querySelector('meta[name="viewport"]');
    if (m) m.setAttribute('content',
        'width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no');
})();
function fixCam() {
    window.parent.document.querySelectorAll('iframe').forEach(function(f) {
        var a = f.getAttribute('allow') || '';
        if (!a.includes('camera')) f.setAttribute('allow', a + ' camera; microphone');
    });
}
fixCam(); setInterval(fixCam, 2000);
</script>
""", height=0)


# ─────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
.block-container { padding-top: 1.5rem !important; }
header { visibility: hidden; }
h1 { margin-top:-10px !important; padding-top:0 !important;
     margin-bottom:5px !important; line-height:1.1 !important; }
.stApp { background-color: #261ad6; }
[data-testid="stSidebar"] { background-color: #b30000; }
h1,h2,h3,p,span,label,.stMarkdown { color: #ffffff !important; }
div.stButton > button {
    background-color: #00FF00 !important; color: black !important;
    border-radius: 10px; font-weight: bold !important;
}
div.stButton > button p {
    font-size: 18px !important; font-weight: bold !important; color: black !important;
}
div.stMarkdown p {
    font-size: 16px !important; font-weight: normal !important;
    line-height: 1.5 !important; font-family: sans-serif !important;
}
hr { margin-top: .5rem !important; margin-bottom: .5rem !important;
     border-bottom: 1px solid rgba(255,255,255,.3) !important; }
div[data-testid="stTextInput"] input {
    background-color: #000 !important; color: #fff !important;
    -webkit-text-fill-color: #fff !important; font-size: 16px !important;
}
div[data-testid="stNumberInput"] input {
    background-color: #000 !important; color: #fff !important; font-size: 16px !important;
}
div[data-testid="stSelectbox"] div[data-baseweb="select"] {
    background-color: #000 !important; color: #fff !important;
}
div[data-testid="stTextInput"] input:focus {
    border-color: #fff !important; box-shadow: none !important;
}
iframe { width: 100% !important; max-width: 100% !important; }
video  { width: 100% !important; height: auto !important; object-fit: cover !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# JUDUL & SIDEBAR
# ─────────────────────────────────────────────────────────────
st.markdown("""
<h1 style='text-align:center;font-size:28px;margin-top:-20px;margin-bottom:0;line-height:1.2;'>
  📟 Laporan Produksi Dept. Press <br> PT Indosafety Sentosa
</h1>
""", unsafe_allow_html=True)

with st.sidebar:
    if st.button("🔄 Update Data Master"):
        st.cache_data.clear()
        st.success("Cache dibersihkan!")
        st.rerun()


# ─────────────────────────────────────────────────────────────
# LOAD DATA MASTER — sekali per session
# ─────────────────────────────────────────────────────────────
if 'list_nik_terdaftar' not in st.session_state:
    try:
        df_master = load_master_karyawan()
        st.session_state.list_nik_terdaftar = (
            df_master['NIK'].astype(str).str.strip().tolist()
            if not df_master.empty else []
        )
    except Exception:
        st.session_state.list_nik_terdaftar = []

try:
    main_df = load_main_data()
    if not main_df.empty and 'Part_No' in main_df.columns:
        main_df['Part_No'] = (
            main_df['Part_No'].astype(str)
            .str.replace(r'\.0$', '', regex=True).str.strip()
        )
except Exception as e:
    st.error(f"Gagal memuat MainData: {e}")
    main_df = pd.DataFrame()

for _k, _v in [('nama_terpilih',""), ('nik_karyawan',""),
               ('waktu_end', None), ('waktu_start', None)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v if _v is not None else get_waktu_wib()


# ─────────────────────────────────────────────────────────────
# SIMPAN KE SUPABASE
# ─────────────────────────────────────────────────────────────
def simpan_proses_start(data_dict: dict) -> bool:
    """
    INSERT baris baru status START.
    Kolom: Tanggal, Nama, NIK, Part_No, Part_Name, Model, Line,
           Waktu_Mulai, ACT, NG, Status, Urutan_Proses,
           Actual_Line, Sec_Pcs
    """
    try:
        nik_clean = bersihkan_nik(safe_get(data_dict, 'NIK', ''))

        # Cek duplikat
        res_cek = safe_sb(
            lambda: supabase.table("proses")
                .select("id")
                .eq("NIK", nik_clean)
                .eq("Status", "START")
                .execute(),
            op="Cek duplikat START"
        )
        if res_cek and res_cek.data:
            st.error("⚠️ Data START sudah ada. Klik Reset Scanner lalu scan ulang.")
            return False

        payload = {
            "Tanggal":         safe_get(data_dict, 'Tanggal', date.today().isoformat()),
            "Nama":            safe_get(data_dict, 'Nama', ''),
            "NIK":             nik_clean,
            "Part_No":         safe_get(data_dict, 'Part_No', ''),
            "Part_Name":       safe_get(data_dict, 'Part_Name', ''),
            "Model":           safe_get(data_dict, 'Model', ''),
            "Line":            safe_get(data_dict, 'Line', ''),
            "Waktu_Mulai":     safe_get(data_dict, 'Waktu_Mulai', '00:00:00'),
            "Waktu_Selesai":   None,
            "ACT":             0,
            "NG":              0,
            "Status":          "START",
            "Urutan_Proses":   safe_get(data_dict, 'Urutan_Proses', ''),
            "Pct_Prod":        None,   # kolom "%_Prod" di Supabase jadi "Pct_Prod"
            "Rasio_NG":        None,
            "Total_Jam":       None,
            "Total_Istirahat": None,   # kolom "Total Istirahat" jadi "Total_Istirahat"
            "Actual_Line":     safe_get(data_dict, 'Actual_Line', ''),
            "Sec_Pcs":         safe_float(safe_get(data_dict, 'Sec_Pcs', 0)),
        }

        res = safe_sb(
            lambda: supabase.table("proses").insert(payload).execute(),
            op="Simpan START"
        )
        return bool(res and res.data)

    except Exception as e:
        st.error(f"Gagal simpan START: {e}")
        return False


def simpan_proses_finish(row_id: int, data_dict: dict) -> bool:
    """UPDATE baris proses by primary key id."""
    try:
        if not row_id:
            st.error("❌ row_id tidak valid. Hubungi Admin.")
            return False

        payload = {
            "Waktu_Selesai":   safe_get(data_dict, 'Waktu_Selesai', ''),
            "ACT":             safe_int(safe_get(data_dict, 'ACT', 0)),
            "NG":              safe_int(safe_get(data_dict, 'NG', 0)),
            "Pct_Prod":        safe_get(data_dict, 'Pct_Prod', 'N/A'),
            "Total_Istirahat": safe_int(safe_get(data_dict, 'Total_Istirahat', 0)),
            "Rasio_NG":        safe_get(data_dict, 'Rasio_NG', 'N/A'),
            "Total_Jam":       safe_float(safe_get(data_dict, 'Total_Jam', 0)),
            "Status":          "FINISH",
        }

        res = safe_sb(
            lambda: supabase.table("proses")
                .update(payload).eq("id", row_id).execute(),
            op="Simpan FINISH"
        )
        if res and res.data:
            return True
        st.error("❌ Update FINISH tidak berhasil. Coba lagi.")
        return False

    except Exception as e:
        st.error(f"Gagal simpan FINISH: {e}")
        return False


def simpan_checkin(nama: str, nik: str, waktu_now: datetime) -> bool:
    """INSERT check-in baru. Kolom: Tanggal, Nama, NIK, Check_In, Check_Out, Total_Jam, Aktivitas"""
    try:
        nik_clean = bersihkan_nik(nik)
        # Cek duplikat
        if cek_sudah_checkin(nik_clean):
            st.warning("⚠️ Anda sudah tercatat Check-In sebelumnya!")
            st.session_state.is_sudah_checkin = True
            return False

        payload = {
            "Tanggal":    waktu_now.strftime("%Y-%m-%d"),
            "Nama":       nama,
            "NIK":        nik_clean,
            "Check_In":   waktu_now.strftime("%H:%M:%S"),
            "Check_Out":  None,
            "Total_Jam":  0,
            "Aktivitas":  "Mulai Shift",
        }
        res = safe_sb(
            lambda: supabase.table("waktu_kerja").insert(payload).execute(),
            op="Simpan Check-In"
        )
        return bool(res and res.data)

    except Exception as e:
        err = str(e)
        if "duplicate" in err.lower() or "unique" in err.lower():
            st.warning("⚠️ Sudah tercatat Check-In sebelumnya!")
            st.session_state.is_sudah_checkin = True
            return False
        st.error(f"Gagal simpan Check-In: {e}")
        return False


def simpan_checkout(row_id: int, waktu_out: datetime, total_jam: float) -> bool:
    """UPDATE Check_Out by id."""
    try:
        if not row_id:
            st.error("❌ row_id check-in tidak valid.")
            return False
        payload = {
            "Check_Out": waktu_out.strftime("%H:%M:%S"),
            "Total_Jam": round(total_jam, 2),
            "Aktivitas": "Shift Complete",
        }
        res = safe_sb(
            lambda: supabase.table("waktu_kerja")
                .update(payload).eq("id", row_id).execute(),
            op="Simpan Check-Out"
        )
        return bool(res and res.data)

    except Exception as e:
        st.error(f"Gagal simpan Check-Out: {e}")
        return False


def simpan_abnormal(data_dict: dict) -> bool:
    """INSERT ke tabel abnormal."""
    try:
        payload = {
            "Tanggal":          safe_get(data_dict, 'Tanggal', date.today().isoformat()),
            "Mesin":            safe_get(data_dict, 'Mesin', ''),
            "Part_No":          safe_get(data_dict, 'Part_No', ''),
            "Model":            safe_get(data_dict, 'Model', ''),
            "Part_Name":        safe_get(data_dict, 'Part_Name', ''),
            "Urutan_Proses":    safe_get(data_dict, 'Urutan_Proses', ''),
            "Operator":         safe_get(data_dict, 'Operator', ''),
            "Kode_Abnormal":    safe_get(data_dict, 'Kode_Abnormal', ''),
            "Uraian_Abnormal":  safe_get(data_dict, 'Uraian_Abnormal', ''),
            "Total_Waktu":      safe_int(safe_get(data_dict, 'Total_Waktu', 0)),
            "Keterangan":       safe_get(data_dict, 'Keterangan', ''),
        }
        res = safe_sb(
            lambda: supabase.table("abnormal").insert(payload).execute(),
            op="Simpan Abnormal"
        )
        return bool(res and res.data)

    except Exception as e:
        st.error(f"Gagal simpan Abnormal: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# HANDLE SCAN KANBAN
# ─────────────────────────────────────────────────────────────
def handle_scan():
    raw = st.session_state.get('barcode_input', '')
    raw = raw.replace('\n','').replace('\r','').replace('\t','').strip()
    if not raw:
        return

    # Debounce 2 detik
    now = time.time()
    if (raw == st.session_state.get('last_kanban_scan', '') and
            now - st.session_state.get('last_kanban_time', 0) < 2.0):
        st.session_state.barcode_input = ""
        return
    st.session_state.last_kanban_scan = raw
    st.session_state.last_kanban_time = now

    pno    = raw.split(';')[0].strip()
    status = st.session_state.get('status_kerja', 'IDLE')
    nik    = st.session_state.get('nik_karyawan', '')

    # Cari Part_No di main_df
    match = pd.DataFrame()
    if not main_df.empty and 'Part_No' in main_df.columns:
        match = main_df[main_df['Part_No'] == pno]

    if status == "IDLE":
        # Cek proses aktif fresh (tanpa cache — hindari stale data)
        proses_aktif = query_proses_aktif(bersihkan_nik(nik))

        if proses_aktif:
            # Ada proses START yang belum selesai — restore ke RUNNING
            p_no = str(safe_get(proses_aktif, 'Part_No', '')).replace('.0','').strip()
            mm   = main_df[main_df['Part_No'] == p_no] if not main_df.empty else pd.DataFrame()

            st.session_state.current_part = {
                'row_id':        safe_get(proses_aktif, 'id'),
                'part_no':       p_no,
                'part_name':     safe_get(proses_aktif, 'Part_Name', ''),
                'model':         safe_get(proses_aktif, 'Model', ''),
                'urutan_proses': safe_get(proses_aktif, 'Urutan_Proses', ''),
                'Actual_Line':   safe_get(proses_aktif, 'Actual_Line', 'N/A'),
                'line':          safe_get(proses_aktif, 'Line', ''),
                'sec_pcs':       safe_float(safe_get(proses_aktif, 'Sec_Pcs', 0)),
            }
            st.session_state.waktu_start = parse_datetime_dari_row(
                safe_get(proses_aktif, 'Tanggal'),
                safe_get(proses_aktif, 'Waktu_Mulai'),
                fallback=get_waktu_wib()
            )
            st.session_state.status_kerja       = "RUNNING"
            st.session_state.sudah_start_diklik = True
            st.session_state.barcode_input      = ""
            st.success(f"🔄 Sesi {p_no} dipulihkan!")
            st.rerun()

        elif not match.empty:
            st.session_state.available_processes = match.to_dict('records')
            st.session_state.status_kerja        = "SELECTING_PROCESS"
            st.session_state.barcode_input        = ""
            st.rerun()
        else:
            st.error(f"❌ Part No '{pno}' tidak terdaftar di Main Data!")
            st.session_state.barcode_input = ""

    elif status == "RUNNING":
        cp  = st.session_state.get('current_part') or {}
        cur = str(safe_get(cp, 'part_no', '')).strip()
        if pno == cur:
            st.session_state.status_kerja  = "FINISHING"
            st.session_state.waktu_end     = get_waktu_wib()
            st.session_state.barcode_input = ""
            st.toast("🏁 Scan Finish Berhasil!")
            st.rerun()
        else:
            st.error(f"❌ Barcode ({pno}) berbeda dengan Part aktif: {cur}")
            st.session_state.barcode_input = ""


# ─────────────────────────────────────────────────────────────
# ROUTING UTAMA
# ─────────────────────────────────────────────────────────────
nama_karyawan = st.session_state.get('nama_terpilih', "")
nik_karyawan  = st.session_state.get('nik_karyawan',  "")

if 'is_sudah_checkin' not in st.session_state:
    st.session_state.is_sudah_checkin = False

# Fallback verifikasi check-in — HANYA update ke True, tidak pernah paksa False
if nama_karyawan and not st.session_state.is_sudah_checkin:
    try:
        if cek_sudah_checkin(nik_karyawan):
            st.session_state.is_sudah_checkin = True
    except Exception:
        pass

is_sudah_checkin = st.session_state.is_sudah_checkin


# ─────────────────────────────────────────────────────────────
# LAYAR 1: SCAN ID OPERATOR
# ─────────────────────────────────────────────────────────────
if not nama_karyawan:
    st.subheader("👋 Selamat Datang! Silakan Scan ID Operator")

    if st.session_state.get('sedang_proses_scan_id', False):
        st.info("⏳ Memproses data operator, harap tunggu...")
        st.stop()

    barcode_id = qrcode_scanner(key='scanner_id_operator')

    if barcode_id:
    # 1. Pastikan data adalah string dan bersihkan karakter whitespace
        if not isinstance(barcode_id, str):
            barcode_id = str(barcode_id)
    
        barcode_id = barcode_id.replace('\n','').replace('\r','').replace('\t','').strip()

        # 2. Debounce Logic (Cegah scan ganda)
        now = time.time()
        if (barcode_id == st.session_state.get('last_id_scan_value', '') and
                now - st.session_state.get('last_id_scan_time', 0) < 3.0):
            st.stop()

        st.session_state.last_id_scan_value = barcode_id
        st.session_state.last_id_scan_time  = now

        # 3. Validasi Format "NIK;Nama"
        if ";" not in barcode_id:
            st.error(f"❌ Format ID tidak valid: '{barcode_id}'. Gunakan format NIK;Nama")
            st.stop()

        parts = barcode_id.split(';')
        raw_nik = parts[0].strip()
        raw_nama = parts[1].strip() if len(parts) > 1 else ""

        if not raw_nik or not raw_nama:
            st.error("❌ NIK atau Nama kosong di barcode. Coba scan ulang.")
            st.stop()

        # 4. Verifikasi NIK ke Master Data (Supabase/Session State)
        nik_scan_clean   = bersihkan_nik(raw_nik)
        # Pastikan list_nik_terdaftar sudah ada isinya
        nik_master_clean = [bersihkan_nik(str(n)) for n in st.session_state.get('list_nik_terdaftar', [])]

        if nik_scan_clean not in nik_master_clean:
            st.error(f"🚫 Akses Ditolak! NIK {raw_nik} tidak terdaftar di sistem.")
        time.sleep(2)
        st.rerun()
    
        # JIKA LOLOS, LANJUTKAN PROSES...
        st.success(f"Selamat bekerja, {raw_nama}!")

        # Guard + set identity SEBELUM API call
        st.session_state.sedang_proses_scan_id = True
        st.session_state.nik_karyawan          = raw_nik
        st.session_state.nama_terpilih         = raw_nama
        for k in ['proses_data','current_part','sudah_start_diklik',
                  'available_processes','ab_counter','data_sph_terkirim']:
            st.session_state.pop(k, None)

        # STEP 1: Verifikasi check-in (fresh query, bukan cache)
        with st.spinner("Memverifikasi Check-In..."):
            try:
                is_ci = cek_sudah_checkin(raw_nik)
                st.session_state.is_sudah_checkin = is_ci
            except Exception as e:
                st.warning(f"⚠️ Tidak bisa verifikasi check-in: {e}")
                st.session_state.is_sudah_checkin = False

        # STEP 2: Cek proses aktif (fresh query)
        data_aktif = None
        with st.spinner("Mengecek proses aktif..."):
            try:
                data_aktif = query_proses_aktif(nik_scan_clean)
            except Exception as e:
                st.warning(f"⚠️ Cek proses gagal: {e}. Lanjut sebagai IDLE.")

        # STEP 3: Set status kerja berdasarkan data
        if data_aktif:
            st.session_state.status_kerja       = "RUNNING"
            st.session_state.sudah_start_diklik = True
            st.session_state.current_part = {
                'row_id':        safe_get(data_aktif, 'id'),
                'part_no':       str(safe_get(data_aktif,'Part_No','')).replace('.0','').strip(),
                'part_name':     safe_get(data_aktif, 'Part_Name', ''),
                'model':         safe_get(data_aktif, 'Model', ''),
                'line':          safe_get(data_aktif, 'Line', ''),
                'urutan_proses': safe_get(data_aktif, 'Urutan_Proses', ''),
                'sec_pcs':       safe_float(safe_get(data_aktif, 'Sec_Pcs', 0)),
                'Actual_Line':   safe_get(data_aktif, 'Actual_Line', ''),
            }
            st.session_state.waktu_start = parse_datetime_dari_row(
                safe_get(data_aktif, 'Tanggal'),
                safe_get(data_aktif, 'Waktu_Mulai'),
                fallback=get_waktu_wib()
            )
            st.success(f"🔄 Melanjutkan: {safe_get(data_aktif, 'Part_Name', '-')}")
        else:
            st.session_state.status_kerja = "IDLE"
            st.success(f"✅ Terverifikasi: {raw_nama}")

        st.session_state.sedang_proses_scan_id = False
        time.sleep(1); st.rerun()


# ─────────────────────────────────────────────────────────────
# LAYAR 2: BELUM CHECK-IN
# ─────────────────────────────────────────────────────────────
elif not is_sudah_checkin:
    st.warning(f"⚠️ Halo **{nama_karyawan}** | {nik_karyawan} — Anda belum Check-In.")

    if st.session_state.get('checkin_sedang_proses', False):
        st.warning("⏳ Check-In sedang diproses, harap tunggu...")
        st.stop()

    if st.button("🟢 KLIK UNTUK CHECK-IN SEKARANG", use_container_width=True):
        st.session_state.checkin_sedang_proses = True
        try:
            waktu_skrg = get_waktu_wib()
            with st.spinner("Menyimpan Check-In..."):
                ok = simpan_checkin(nama_karyawan, nik_karyawan, waktu_skrg)

            if ok:
                st.session_state.is_sudah_checkin      = True
                st.session_state.status_kerja          = "IDLE"
                st.session_state.checkin_sedang_proses = False
                st.success("✅ Berhasil Check-In! Scanner Part siap digunakan.")
                time.sleep(1); st.rerun()
            else:
                st.session_state.checkin_sedang_proses = False

        except Exception as e:
            st.session_state.checkin_sedang_proses = False
            err = str(e)
            if "timeout" in err.lower() or "network" in err.lower():
                st.error("❌ Koneksi bermasalah. Coba lagi.")
            else:
                st.error(f"❌ Gagal Check-In: {err}")
            st.info("📋 Jika terus bermasalah, lapor ke Admin.")

    st.divider()
    if st.button("⬅️ Kembali / Scan Ulang ID Operator", type="secondary", use_container_width=True):
        for k in ['nama_terpilih','nik_karyawan','is_sudah_checkin',
                  'checkin_sedang_proses','sedang_proses_scan_id',
                  'last_id_scan_value','last_id_scan_time']:
            st.session_state.pop(k, None)
        st.rerun()


# ─────────────────────────────────────────────────────────────
# LAYAR 3 & 4: AREA PRODUKSI
# ─────────────────────────────────────────────────────────────
else:
    st.success(f"👷 Operator: **{nama_karyawan}** | **{nik_karyawan}** | Sesi Aktif")
    status_kerja = st.session_state.get('status_kerja', 'IDLE')

    # ── IDLE ──────────────────────────────────────────────────
    if status_kerja == "IDLE":
        st.write("<span style='font-size:18px;font-weight:bold;'>📸 Opsi 1: Scan KANBAN untuk mulai proses</span>", unsafe_allow_html=True)
        bp = qrcode_scanner(key='scanner_part_prod')
        if bp and isinstance(bp, str):
            st.session_state.barcode_input = bp
            handle_scan()

        st.divider()
        st.write("<span style='font-size:18px;font-weight:bold;'>⌨️ Opsi 2: Input Part No. Manual</span>", unsafe_allow_html=True)
        mi = st.text_input("Ketik Part No.", key="manual_part_input").strip().upper()
        if st.button("✅ Konfirmasi Input Manual", use_container_width=True):
            if mi:
                st.session_state.barcode_input = mi
                handle_scan()

        st.divider()
        st.write("Jika sudah selesai semua pekerjaan shift ini:")

        with st.popover("🔴 SELESAI SHIFT (CHECK-OUT)", use_container_width=True):
            st.write("### Konfirmasi Check-Out")
            st.warning("Apakah Anda yakin ingin mengakhiri shift sekarang?")

            proses_aktif_co = load_proses_aktif_nik_cached(bersihkan_nik(nik_karyawan))
            if proses_aktif_co:
                pno_aktif = safe_get(proses_aktif_co, 'Part_No', '?')
                st.error(f"❌ Tidak bisa Check-Out! Masih ada pekerjaan aktif: **{pno_aktif}**. Selesaikan dulu.")
            else:
                st.success("✅ Semua pekerjaan sudah selesai.")
                if st.button("YA, SAYA YAKIN CHECK-OUT", type="primary", use_container_width=True):
                    with st.spinner("Memproses Check-Out..."):
                        try:
                            waktu_out = get_waktu_wib()
                            ci_row    = query_waktu_kerja_aktif(bersihkan_nik(nik_karyawan))

                            if ci_row and isinstance(ci_row, dict):
                                dt_in     = get_checkin_datetime(ci_row, waktu_out)
                                total_jam = round((waktu_out - dt_in).total_seconds() / 3600, 2)
                                ci_id     = safe_get(ci_row, 'id')

                                if ci_id and isinstance(ci_id, int):
                                    ok = simpan_checkout(ci_id, waktu_out, total_jam)
                                    if ok:
                                        for k in ['is_sudah_checkin','nama_terpilih','nik_karyawan',
                                                  'status_kerja','current_part','sudah_start_diklik']:
                                            st.session_state.pop(k, None)
                                        st.session_state.is_sudah_checkin = False
                                        st.success(f"✅ Check-Out Berhasil! Total: {total_jam} jam")
                                        time.sleep(3); st.rerun()
                                else:
                                    st.error("❌ ID check-in tidak valid.")
                            else:
                                st.error("❌ Data Check-In aktif tidak ditemukan!")

                        except Exception as e:
                            st.error(f"❌ Gagal Check-Out: {e}")
                            st.info("📋 Data BELUM tersimpan.")

            st.divider()
            if st.button("⬅️ Ganti Operator / Salah Scan Nama", use_container_width=True):
                for k in ['nama_terpilih','nik_karyawan','is_sudah_checkin','status_kerja',
                          'checkin_sedang_proses','sedang_proses_scan_id',
                          'last_id_scan_value','last_id_scan_time']:
                    st.session_state.pop(k, None)
                st.rerun()

    # ── SELECTING_PROCESS ─────────────────────────────────────
    elif status_kerja == "SELECTING_PROCESS":
        st.subheader("🔍 Pilih Urutan Proses")
        data_pilihan = st.session_state.get('available_processes', [])
        list_line    = list(dict.fromkeys(
            (main_df['LINE'].unique().tolist() if 'LINE' in main_df.columns else []) +
            ["BM","CM","DM","ERM","NRM","IRM","KRM"]
        ))

        if not any(safe_get(p,'URUTAN') == 'DPMR' for p in data_pilihan):
            s = data_pilihan[0] if data_pilihan else {}
            data_pilihan.append({
                'URUTAN':    'DPMR',
                'Part_Name': safe_get(s,'Part_Name','REPAIR'),
                'Part_No':   safe_get(s,'Part_No','REPAIR'),
                'MODEL':     safe_get(s,'MODEL','REPAIR'),
                'LINE':      safe_get(s,'LINE','-'),
                'SEC_PCS':   0,
            })

        actual_line  = st.selectbox("Pilih Line Produksi (Actual Line)", options=list_line)
        opsi_display = {f"{safe_get(p,'URUTAN','-')} | {safe_get(p,'Part_Name','-')}": p
                        for p in data_pilihan}
        pilihan_user = st.selectbox("Pilih Urutan Proses Produksi", options=list(opsi_display.keys()))

        if st.button("Konfirmasi & Mulai Kerja"):
            d = opsi_display[pilihan_user]
            # Cek nama kolom SEC_PCS — main_data bisa pakai "SEC_PCS" atau "SEC /PCS"
            sec_val = safe_float(safe_get(d,'SEC_PCS', safe_get(d,'SEC /PCS', 0)))
            st.session_state.current_part = {
                'row_id':        None,
                'part_no':       safe_get(d,'Part_No','N/A'),
                'part_name':     safe_get(d,'Part_Name','N/A'),
                'model':         safe_get(d,'MODEL','N/A'),
                'sec_pcs':       sec_val,
                'line':          safe_get(d,'LINE','N/A'),
                'Actual_Line':   actual_line,
                'urutan_proses': safe_get(d,'URUTAN','DPMR'),
            }
            st.session_state.status_kerja = "RUNNING"
            st.session_state.waktu_start  = get_waktu_wib()
            st.rerun()

    # ── RUNNING ───────────────────────────────────────────────
    elif status_kerja == "RUNNING":
        dp = st.session_state.get('current_part') or {}
        if dp:
            ws_dt = st.session_state.get('waktu_start') or get_waktu_wib()
            dl    = get_waktu_wib() - ws_dt.replace(tzinfo=None)
            ml    = int(dl.total_seconds() / 60)
            jl    = round(dl.total_seconds() / 3600, 2)

            part_name    = safe_get(dp, 'part_name', '-')
            part_no      = safe_get(dp, 'part_no', '-')
            urutan       = safe_get(dp, 'urutan_proses', '-')
            sec_pcs      = safe_float(safe_get(dp, 'sec_pcs', 0))
            actual_line  = safe_get(dp, 'Actual_Line', '-')

            st.info(f"⚡ **Proses Berjalan:** {part_name} | {part_no}")
            st.write("Konfirmasi Mulai Kerja")

            if not st.session_state.get('sudah_start_diklik'):
                st.warning("⚠️ Klik tombol di bawah untuk mulai menghitung waktu produksi.")
                if st.button("🚀 Konfirmasi Start Proses", use_container_width=True):
                    data_start = {
                        "Tanggal":       get_waktu_wib().strftime("%Y-%m-%d"),
                        "Nama":          nama_karyawan,
                        "NIK":           nik_karyawan,
                        "Part_No":       part_no,
                        "Part_Name":     part_name,
                        "Model":         safe_get(dp, 'model', ''),
                        "Line":          safe_get(dp, 'line', ''),
                        "Waktu_Mulai":   ws_dt.strftime("%H:%M:%S"),
                        "Urutan_Proses": urutan,
                        "Actual_Line":   actual_line,
                        "Sec_Pcs":       sec_pcs,
                    }
                    with st.spinner("Menyimpan START..."):
                        ok = simpan_proses_start(data_start)

                    if ok:
                        # Ambil row_id yang baru dibuat
                        try:
                            row_baru = query_proses_aktif(bersihkan_nik(nik_karyawan))
                            if row_baru:
                                st.session_state.current_part['row_id'] = safe_get(row_baru, 'id')
                        except Exception:
                            pass
                        st.session_state.sudah_start_diklik = True
                        st.balloons(); time.sleep(2)
                        st.success("✅ Produksi Dimulai!"); st.rerun()
            else:
                st.success("✅ Proses Sudah Dimulai")
                st.info("JIKA DPMR: Masukkan jumlah Part OK dan NG di INPUT ABNORMAL!")

            c1, c2, c3, c4, c5 = st.columns(5, gap="small")
            c1.metric("Urutan",         urutan)
            c2.metric("Target Sec/Pcs", sec_pcs)
            c3.metric("Mulai",          ws_dt.strftime('%H:%M:%S'))
            c4.metric("Sudah Berjalan", f"{ml} Menit", delta=f"{jl:.1f} Jam")
            c5.metric("Actual Line",    actual_line)
            st.divider()

            with st.expander("⚠️ INPUT ABNORMAL", expanded=False):
                st.write("Input langsung tersimpan. Jika DPMR, tulis OK dan NG total di Keterangan.")
                LIST_KODE = [
                    "A [Ganti Proses]","B [Ganti/Tambah Coil]","C [Periksa ATA]",
                    "D [Trial]","E [2S]","F [Briefing Rutin]",
                    "G1 [Material NG dan Tukar Proses]","G2 [Kualitas NG dan Tukar Proses]",
                    "H [Tooling]","I [Mesin Abnormal]","K1 [Penanganan Kualitas NG]",
                    "K2 [Penanganan Dies NG]","L [Kekurangan Material]",
                    "M [Lain-Lain]","N [No KANBAN Plan]","O [DPMR]"
                ]
                if "ab_counter" not in st.session_state:
                    st.session_state.ab_counter = 0
                ab = st.session_state.ab_counter
                ck, cm, ckt = st.columns([1,1,2])
                ks  = ck.selectbox("Kode", LIST_KODE, key=f"ab_kode_{ab}")
                mv  = cm.number_input("Menit", min_value=0, step=1, key=f"ab_menit_{ab}")
                ktv = ckt.text_input("Keterangan", placeholder="Contoh: Mesin Down",
                                     key=f"ab_ket_{ab}").upper()

                if st.button("🚀 Kirim Data Abnormal", use_container_width=True, key=f"btn_ab_{ab}"):
                    if not st.session_state.get('sudah_start_diklik'):
                        st.error("⚠️ Klik START PROSES dulu!")
                    elif ks and mv > 0:
                        pts = ks.split(" [")
                        row_ab = {
                            "Tanggal":         get_waktu_wib().strftime("%Y-%m-%d"),
                            "Mesin":           actual_line,
                            "Part_No":         part_no,
                            "Model":           safe_get(dp,'model',''),
                            "Part_Name":       part_name,
                            "Urutan_Proses":   urutan,
                            "Operator":        nama_karyawan,
                            "Kode_Abnormal":   pts[0],
                            "Uraian_Abnormal": pts[1].replace("]","") if len(pts)>1 else "",
                            "Total_Waktu":     mv,
                            "Keterangan":      ktv,
                        }
                        if simpan_abnormal(row_ab):
                            st.toast(f"✅ {ks} tersimpan!")
                            st.session_state.ab_counter += 1
                            time.sleep(1)
                    else:
                        st.error("Pilih Kode & isi Menit!")

            st.divider()
            st.write("<span style='font-size:18px;font-weight:bold;'>📸 SCAN KANBAN untuk FINISH</span>", unsafe_allow_html=True)
            bd = qrcode_scanner(key='scanner_finish_part')
            if bd and isinstance(bd, str):
                st.session_state.barcode_input = bd
                handle_scan()

            st.divider()
            st.write("<span style='font-size:18px;font-weight:bold;'>⌨️ Input KANBAN Manual</span>", unsafe_allow_html=True)
            mf = st.text_input("Ketik Part No", key="manual_part_finish_input").strip().upper()
            if st.button("✅ Konfirmasi Input Manual Finish", use_container_width=True):
                if mf:
                    st.session_state.barcode_input = mf
                    handle_scan()

    # ── FINISHING ─────────────────────────────────────────────
    elif status_kerja == "FINISHING":
        dp = st.session_state.get('current_part') or {}
        if dp:
            part_name   = safe_get(dp, 'part_name', '-')
            part_no     = safe_get(dp, 'part_no', '-')
            urutan      = safe_get(dp, 'urutan_proses', '-')
            sec_pcs     = safe_float(safe_get(dp, 'sec_pcs', 0))

            st.subheader(f"📝 Laporan Akhir: {part_name}")

            ws  = st.session_state.get('waktu_start') or get_waktu_wib()
            we  = st.session_state.get('waktu_end')   or get_waktu_wib()
            dur = we.replace(tzinfo=None) - ws.replace(tzinfo=None)
            jt  = dur.total_seconds() / 60
            jb  = jt % 1440

            c1, c2, c3, c4 = st.columns(4)
            ar = c1.text_input("Jumlah ACT", value="0")
            nr = c2.text_input("Jumlah NG",  value="0")
            try:
                act = int(ar); ng = int(nr)
            except Exception:
                act = 0; ng = 0

            c3.metric("Durasi",      f"{round(jt,2)} Menit", delta=f"{round(jt/60,2)} Jam")
            c4.metric("Waktu Start", ws.strftime("%H:%M:%S"))

            st.write("### ☕ Potongan Waktu Istirahat")
            DB = {
                "Break 1 (10m)":10,"Break 2 (10m)":10,"Istirahat (40m)":40,
                "Extra Break (15m)":15,"2S (15m)":15,"Istirahat Jumat (70m)":70
            }
            pb = st.multiselect("Pilih:", options=list(DB.keys()))
            ec = st.number_input("Lainnya (Menit)", min_value=0, step=1, value=0)
            tp = sum(DB[i] for i in pb) + ec
            db = max(0, jb - tp)
            st.info(f"⏱️ Durasi Bersih: {db:.1f} Menit")

            ir  = (urutan == "DPMR")
            si  = (sec_pcs * act) / 60 if (act > 0 and not ir) else 0
            pp  = round((si / db) * 100, 2) if (db > 0 and not ir) else 0.0

            if st.button("🚀 Kirim Data SPH", use_container_width=True):
                if act > 0 :
                    row_id = safe_get(dp, 'row_id')

                    # Fallback cari row_id kalau None
                    if not row_id:
                        with st.spinner("Mencari ID proses..."):
                            try:
                                row_aktif = query_proses_aktif(bersihkan_nik(nik_karyawan))
                                if row_aktif and isinstance(row_aktif, dict):
                                    row_id = safe_get(row_aktif, 'id')
                                    st.session_state.current_part['row_id'] = row_id
                            except Exception:
                                pass

                    if not row_id:
                        st.error("❌ Tidak bisa menemukan ID proses. Hubungi Admin.")
                    else:
                        data_finish = {
                            "Waktu_Selesai":   we.strftime("%H:%M:%S"),
                            "ACT":             act,
                            "NG":              ng,
                            "Pct_Prod":        "N/A" if ir else f"{pp:.2f}%",
                            "Total_Istirahat": tp,
                            "Rasio_NG":        "N/A" if ir else
                                               (f"{(ng/act*100):.2f}%" if act > 0 else "0%"),
                            "Total_Jam":       round(db / 60, 2),
                        }
                        if row_id is not None and isinstance(row_id, str) and row_id.isdigit():
                            # Lakukan casting ke int untuk memastikan tipe data benar
                            row_id_int = int(row_id)

                            with st.spinner("Menyimpan SPH..."):
                                ok = simpan_proses_finish(row_id_int, data_finish)
                            if ok:
                                st.session_state.data_sph_terkirim = True
                                st.success("✅ SPH Terkirim!")
                else:
                    st.error("⚠️ Jumlah ACT harus diisi dan lebih dari 0!")

            if st.session_state.get('data_sph_terkirim'):
                st.divider()
                st.subheader("📊 Ringkasan Hasil Produksi")
                c1, c2, c3 = st.columns(3, gap="medium")
                c1.metric("Persentase Produksi", f"{pp:.2f} %")
                c2.metric("Total Jam Kerja",      f"{round(db/60,2)} Jam")
                c3.metric("Rasio NG",              f"{(ng/act*100) if act>0 else 0:.2f} %")
                st.info("✅ Data SPH sudah tercatat di database.")
                st.divider()

                if st.button("🏁 SELESAI & SCAN PART BARU", type="primary", use_container_width=True):
                    for k in ['status_kerja','current_part','waktu_start','waktu_end',
                              'data_sph_terkirim','available_processes','sudah_start_diklik',
                              'barcode_input','proses_data','ab_counter',
                              'last_kanban_scan','last_kanban_time']:
                        st.session_state.pop(k, None)
                    st.session_state.status_kerja = "IDLE"
                    st.balloons()
                    st.success("✅ Laporan selesai! Siap scan part baru.")
                    time.sleep(2); st.rerun()

    # ── Tombol Reset ──────────────────────────────────────────
    if st.session_state.get('status_kerja') == "RUNNING":
        cr, cs = st.columns(2)
        with cr:
            if st.button("🔄 Perbarui Waktu"): st.rerun()
        with cs:
            if st.button("🚫 Reset Scanner", type="secondary"):
                for k in ['status_kerja','current_part','waktu_start','waktu_end',
                          'sudah_start_diklik','last_kanban_scan','last_kanban_time']:
                    st.session_state.pop(k, None)
                st.rerun()
    else:
        if st.button("❌ Reset Scanner", type="secondary"):
            for k in ['status_kerja','current_part',
                      'last_kanban_scan','last_kanban_time']:
                st.session_state.pop(k, None)
            st.rerun()
