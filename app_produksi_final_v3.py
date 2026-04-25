import streamlit as st
import streamlit.components.v1 as components
from streamlit_qrcode_scanner import qrcode_scanner
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import pytz
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, date
import time
import random

# ============================================================
# set_page_config WAJIB baris pertama sebelum apapun
# ============================================================
st.set_page_config(page_title="Laporan Produksi Press PT. ISI", layout="wide")

# ============================================================
# SAFE API WRAPPERS
# ============================================================

def safe_gsheet_update(conn, spreadsheet, worksheet, data, max_retries=4):
    """Wrapper conn.update — HANYA untuk FINISH dan CHECK-OUT (edit baris existing)."""
    for attempt in range(max_retries):
        try:
            conn.update(spreadsheet=spreadsheet, worksheet=worksheet, data=data)
            return True
        except Exception as e:
            error_str = str(e).lower()
            is_429 = "429" in error_str or "quota" in error_str or "rate" in error_str
            is_5xx = "500" in error_str or "503" in error_str or "internal" in error_str
            if (is_429 or is_5xx) and attempt < max_retries - 1:
                wait_time = round((2 ** (attempt + 1)) + 2 + random.uniform(0, 2), 1)
                st.warning(f"⏳ Server sibuk, mencoba ulang dalam {wait_time} detik... ({attempt+1}/{max_retries-1})")
                time.sleep(wait_time)
                continue
            else:
                raise e
    return False


def safe_gsheet_read(conn, spreadsheet, worksheet, ttl=10, max_retries=4):
    """Wrapper conn.read dengan exponential backoff + jitter."""
    for attempt in range(max_retries):
        try:
            return conn.read(spreadsheet=spreadsheet, worksheet=worksheet, ttl=ttl)
        except Exception as e:
            error_str = str(e).lower()
            is_retryable = any(
                c in error_str for c in ["429", "500", "503", "quota", "rate", "internal"]
            )
            if is_retryable and attempt < max_retries - 1:
                wait_time = round((2 ** (attempt + 1)) + 2 + random.uniform(0, 2), 1)
                st.warning(f"⏳ Membaca data, mencoba ulang dalam {wait_time} detik... ({attempt+1}/{max_retries-1})")
                time.sleep(wait_time)
                continue
            else:
                raise e
    return pd.DataFrame()


def safe_append_row(worksheet_obj, row_values, max_retries=4):
    """Wrapper gspread append_row — untuk START, CHECK-IN, ABNORMAL (atomic, tanpa race condition)."""
    for attempt in range(max_retries):
        try:
            worksheet_obj.append_row(row_values, value_input_option="USER_ENTERED")
            return True
        except Exception as e:
            error_str = str(e).lower()
            is_429 = "429" in error_str or "quota" in error_str or "rate" in error_str
            is_5xx = "500" in error_str or "503" in error_str or "internal" in error_str
            if (is_429 or is_5xx) and attempt < max_retries - 1:
                wait_time = round((2 ** (attempt + 1)) + 2 + random.uniform(0, 2), 1)
                st.warning(f"⏳ Server sibuk, mencoba ulang dalam {wait_time} detik... ({attempt+1}/{max_retries-1})")
                time.sleep(wait_time)
                continue
            else:
                raise e
    return False


# ============================================================
# JAVASCRIPT — cegah refresh + iOS camera fix
# ============================================================
components.html(
    """
    <script>
    window.parent.addEventListener('beforeunload', function(e) {
        var msg = 'Data sedang diproses. Jika refresh, sesi scan akan hilang!';
        (e || window.event).returnValue = msg;
        return msg;
    });
    (function() {
        var meta = window.parent.document.querySelector('meta[name="viewport"]');
        if (meta) {
            meta.setAttribute('content',
                'width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no');
        }
    })();
    function fixIframeCameraPermission() {
        var iframes = window.parent.document.querySelectorAll('iframe');
        iframes.forEach(function(iframe) {
            var allow = iframe.getAttribute('allow') || '';
            if (!allow.includes('camera')) {
                iframe.setAttribute('allow', allow + ' camera; microphone');
            }
        });
    }
    fixIframeCameraPermission();
    setInterval(fixIframeCameraPermission, 2000);
    </script>
    """,
    height=0,
)

# ============================================================
# CSS STYLING
# ============================================================
st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem !important; }
    header { visibility: hidden; }
    h1 {
        margin-top: -10px !important; padding-top: 0px !important;
        margin-bottom: 5px !important; line-height: 1.1 !important;
    }
    .stApp { background-color: #261ad6; }
    [data-testid="stSidebar"] { background-color: #b30000; }
    h1, h2, h3, p, span, label, .stMarkdown { color: #ffffff !important; }
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
    hr {
        margin-top: 0.5rem !important; margin-bottom: 0.5rem !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.3) !important;
    }
    div[data-testid="stTextInput"] input {
        background-color: #000000 !important; color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
        font-size: 16px !important;
    }
    div[data-testid="stNumberInput"] input {
        background-color: #000000 !important; color: #ffffff !important;
        font-size: 16px !important;
    }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] {
        background-color: #000000 !important; color: #ffffff !important;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #ffffff !important; box-shadow: none !important;
    }
    iframe { width: 100% !important; max-width: 100% !important; }
    video { width: 100% !important; height: auto !important; object-fit: cover !important; }
    </style>
    """, unsafe_allow_html=True)

# ============================================================
# JUDUL & SIDEBAR
# ============================================================
st.markdown(
    """
    <h1 style='text-align: center; font-size: 28px; margin-top: -20px;
               margin-bottom: 0px; line-height: 1.2;'>
        📟 Laporan Produksi Dept. Press <br> PT Indosafety Sentosa
    </h1>
    """, unsafe_allow_html=True
)

if st.sidebar.button("🔄 Update Data Master"):
    st.cache_data.clear()
    st.success("Data berhasil diperbarui!")
    st.rerun()

# ============================================================
# FUNGSI WAKTU
# ============================================================
def get_waktu_wib():
    return datetime.now(pytz.timezone('Asia/Jakarta')).replace(tzinfo=None)

def get_checkin_datetime(checkin_row, waktu_out):
    """Parse Check-In datetime, handle cross-midnight. Kolom: 'Tanggal', 'Check-In'"""
    try:
        dt_in = datetime.strptime(
            f"{checkin_row['Tanggal']} {checkin_row['Check-In']}", "%Y-%m-%d %H:%M:%S"
        )
        if dt_in > waktu_out:
            dt_in -= timedelta(days=1)
        return dt_in
    except Exception:
        return waktu_out - timedelta(hours=8)

# ============================================================
# KONFIGURASI
# ============================================================
URL_KITA = "https://docs.google.com/spreadsheets/d/1uDmbbLhFsMdGSnozbRBMwEDPP2T20HqpEnJGYd2P390/edit"
SCOPES   = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

if 'waktu_end'   not in st.session_state: st.session_state.waktu_end   = get_waktu_wib()
if 'waktu_start' not in st.session_state: st.session_state.waktu_start = get_waktu_wib()

conn = st.connection("gsheets", type=GSheetsConnection)

# ============================================================
# GSPREAD CLIENT — untuk append_row (START, CHECK-IN, ABNORMAL)
# ============================================================
def get_gspread_client():
    if 'gs_client' not in st.session_state:
        try:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["connections"]["gsheets"]), scopes=SCOPES
            )
            st.session_state.gs_client = gspread.authorize(creds)
        except Exception as e:
            st.error(f"Gagal inisialisasi gspread client: {e}")
            return None
    return st.session_state.gs_client

def get_worksheet(worksheet_name):
    gc = get_gspread_client()
    if gc is None:
        return None
    try:
        if 'gs_spreadsheet' not in st.session_state:
            st.session_state.gs_spreadsheet = gc.open_by_url(URL_KITA)
        return st.session_state.gs_spreadsheet.worksheet(worksheet_name)
    except Exception:
        if 'gs_spreadsheet' in st.session_state:
            del st.session_state.gs_spreadsheet
        try:
            st.session_state.gs_spreadsheet = get_gspread_client().open_by_url(URL_KITA)
            return st.session_state.gs_spreadsheet.worksheet(worksheet_name)
        except Exception as e2:
            st.error(f"Gagal buka worksheet '{worksheet_name}': {e2}")
            return None

# ============================================================
# LOAD MASTER KARYAWAN — sekali per session (kolom: NIK)
# ============================================================
if 'list_nik_terdaftar' not in st.session_state:
    try:
        df_karyawan = safe_gsheet_read(conn, URL_KITA, "Master_Karyawan", ttl=3600)
        st.session_state.list_nik_terdaftar = df_karyawan['NIK'].astype(str).str.strip().tolist()
    except Exception:
        st.session_state.list_nik_terdaftar = []

if 'nama_terpilih' not in st.session_state: st.session_state.nama_terpilih = ""
if 'nik_karyawan'  not in st.session_state: st.session_state.nik_karyawan  = ""

# ============================================================
# CACHED SHEET READERS
# ============================================================
@st.cache_data(ttl=3600)
def get_main_data(url):
    """Worksheet: MainData — Part_No, Part_Name, MODEL, LINE, URUTAN, SEC /PCS"""
    df = conn.read(spreadsheet=url, worksheet="MainData", ttl=3600)
    df.columns = df.columns.str.strip()
    return df

@st.cache_data(ttl=10)
def read_proses_sheet(url):
    """Worksheet: Proses — Tanggal, Nama, NIK, Part_No, Part_Name, Model, Line,
       Urutan_Proses, Actual_Line, Sec_Pcs, Waktu_Mulai, Waktu_Selesai,
       ACT, NG, %_Prod, Total Istirahat, Rasio_NG, Total_Jam, Status"""
    df = conn.read(spreadsheet=url, worksheet="Proses", ttl=10)
    df.columns = df.columns.str.strip()
    return df

@st.cache_data(ttl=30)
def read_abnormal_sheet(url):
    """Worksheet: ABNORMAL — Tanggal, Mesin, Part_No, Model, Part_Name,
       Urutan_Proses, Operator, Kode_Abnormal, Uraian_Abnormal, Total_Waktu, Keterangan"""
    return conn.read(spreadsheet=url, worksheet="ABNORMAL", ttl=30)

@st.cache_data(ttl=30)
def read_waktu_kerja_sheet(url):
    """Worksheet: Waktu Kerja — Tanggal, Nama, NIK, Check-In, Check-Out, Total_Jam, Aktivitas"""
    return conn.read(spreadsheet=url, worksheet="Waktu Kerja", ttl=30)

try:
    main_df = get_main_data(URL_KITA)
except Exception as e:
    st.error(f"Gagal memuat MainData: {e}")
    main_df = pd.DataFrame()

# ============================================================
# URUTAN KOLOM — harus identik dengan header di GSheet
# ============================================================
KOLOM_PROSES = [
    "Tanggal", "Nama", "NIK", "Part_No", "Part_Name",
    "Model", "Line", "Urutan_Proses", "Actual_Line", "Sec_Pcs",
    "Waktu_Mulai", "Waktu_Selesai", "ACT", "NG",
    "%_Prod", "Total Istirahat", "Rasio_NG", "Total_Jam", "Status"
]
KOLOM_ABNORMAL = [
    "Tanggal", "Mesin", "Part_No", "Model", "Part_Name",
    "Urutan_Proses", "Operator", "Kode_Abnormal",
    "Uraian_Abnormal", "Total_Waktu", "Keterangan"
]
KOLOM_WAKTU_KERJA = [
    "Tanggal", "Nama", "NIK", "Check-In", "Check-Out", "Total_Jam", "Aktivitas"
]

# ============================================================
# FUNGSI HELPER NIK — dipakai di banyak tempat
# ============================================================
def bersihkan_nik(nik_raw):
    """Normalisasi NIK: hapus quote, titik, spasi."""
    return str(nik_raw).replace("'", "").replace(".", "").strip()

def cek_nik_match(df_kolom_nik, nik_bersih):
    """Return boolean Series: exact match NIK setelah normalisasi."""
    return df_kolom_nik.astype(str).apply(bersihkan_nik) == nik_bersih

def cek_belum_checkout(df_kolom_checkout):
    """Return boolean Series: baris yang Check-Out kosong/NaN."""
    return df_kolom_checkout.isna() | (df_kolom_checkout.astype(str).str.strip() == "")

# ============================================================
# SIMPAN KE SHEET — hybrid append_row + conn.update
# START    → append_row  (atomic, 1 req)
# ABNORMAL → append_row  (atomic, 1 req)
# FINISH   → conn.update (edit baris existing)
# ============================================================
def simpan_ke_sheet(data_dict, tipe):
    try:
        if tipe == "START":
            # Cek duplikat dari cache (hemat API)
            df_proses    = read_proses_sheet(URL_KITA)
            double_check = df_proses[
                (df_proses['Nama'] == data_dict['Nama']) &
                (df_proses['Status'] == 'START')
            ]
            if not double_check.empty:
                st.error("⚠️ Data START sudah ada. Klik Reset Scanner lalu scan ulang.")
                return False
            ws = get_worksheet("Proses")
            if ws is None:
                return False
            row_values = [str(data_dict.get(k, "")) for k in KOLOM_PROSES]
            berhasil   = safe_append_row(ws, row_values)
            if berhasil:
                read_proses_sheet.clear()
            return berhasil

        elif tipe == "FINISH":
            df_proses = read_proses_sheet(URL_KITA).copy()
            for col in ['Total_Jam', 'Rasio_NG', '%_Prod', 'ACT', 'NG']:
                if col in df_proses.columns:
                    df_proses[col] = df_proses[col].astype(object)
            nama_karyawan = st.session_state.get('nama_terpilih', '')
            mask = (
                (df_proses['Nama'].astype(str).str.strip() == str(nama_karyawan).strip()) &
                (df_proses['Part_No'].astype(str)
                    .str.replace(r'\.0$', '', regex=True).str.strip()
                    == str(data_dict['Part_No']).strip()) &
                (df_proses['Status'] == 'START')
            )
            if not mask.any():
                st.error("❌ Tidak ditemukan data START aktif. Lakukan Scan Start dulu!")
                return False
            idx = df_proses[mask].index[-1]
            df_proses.at[idx, 'Waktu_Selesai']  = data_dict['Waktu_Selesai']
            df_proses.at[idx, 'ACT']             = data_dict['ACT']
            df_proses.at[idx, 'NG']              = data_dict['NG']
            df_proses.at[idx, '%_Prod']          = data_dict['%_Prod']
            df_proses.at[idx, 'Total Istirahat'] = data_dict['Total Istirahat']
            df_proses.at[idx, 'Rasio_NG']        = data_dict['Rasio_NG']
            df_proses.at[idx, 'Total_Jam']       = data_dict['Total_Jam']
            df_proses.at[idx, 'Status']          = 'FINISH'
            safe_gsheet_update(conn, URL_KITA, "Proses", df_proses)
            read_proses_sheet.clear()
            return True

        elif tipe == "ABNORMAL":
            ws = get_worksheet("ABNORMAL")
            if ws is None:
                return False
            row_values = [str(data_dict.get(k, "")) for k in KOLOM_ABNORMAL]
            berhasil   = safe_append_row(ws, row_values)
            if berhasil:
                read_abnormal_sheet.clear()
                st.session_state.pop('abnormal_data', None)
            return berhasil

    except Exception as e:
        st.error(f"Gagal memproses data. Catat laporan dan lapor ke Admin. Error: {e}")
        return False


# ============================================================
# FUNGSI BANTU: CARI BARIS CHECK-IN AKTIF
# ============================================================
def get_last_active_row(df, nama):
    if 'Check-Out' not in df.columns or 'Nama' not in df.columns:
        return None
    mask = (
        (df['Nama'].astype(str).str.strip() == str(nama).strip()) &
        cek_belum_checkout(df['Check-Out'])
    )
    active_rows = df[mask]
    return active_rows.iloc[-1].to_dict() if not active_rows.empty else None


# ============================================================
# FUNGSI BANTU: CEK PROSES AKTIF (START) UNTUK OPERATOR
# ============================================================
def cek_proses_aktif(nik_input):
    try:
        df = read_proses_sheet(URL_KITA).copy()
        if df.empty:
            return None
        nik_bersih     = bersihkan_nik(nik_input)
        proses_ongoing = df[
            cek_nik_match(df['NIK'], nik_bersih) &
            (df['Status'] == 'START')
        ]
        return proses_ongoing.iloc[-1].to_dict() if not proses_ongoing.empty else None
    except Exception as e:
        st.error(f"Error pengecekan proses aktif: {e}")
        return None


# ============================================================
# FUNGSI VERIFIKASI CHECK-IN — dipakai di Layar 1 & fallback
# Return: (is_checkin: bool, df_waktu: DataFrame | None)
# ============================================================
def verifikasi_checkin_dari_sheet(nik_raw):
    """
    Baca sheet Waktu Kerja fresh (ttl=0) dan cek apakah NIK
    punya baris Check-In aktif (Check-Out kosong).
    Mengembalikan tuple (is_checkin_aktif, df_waktu).
    """
    try:
        df = safe_gsheet_read(conn, URL_KITA, "Waktu Kerja", ttl=0)
        nik_bersih    = bersihkan_nik(nik_raw)
        checkin_found = df[
            cek_nik_match(df['NIK'], nik_bersih) &
            cek_belum_checkout(df['Check-Out'])
        ]
        return (not checkin_found.empty), df
    except Exception:
        # Kalau API gagal, kembalikan None untuk df — ditangani caller
        return False, None


# ============================================================
# LOGIKA SCAN BARCODE / KANBAN
# ============================================================
def handle_scan():
    raw_scan = st.session_state.get('barcode_input', '').strip()

    # Bersihkan karakter tersembunyi dari QR code
    raw_scan = raw_scan.replace('\n', '').replace('\r', '').replace('\t', '').strip()
    if not raw_scan:
        return

    # Debounce — cegah scan sama diproses 2x dalam 2 detik
    now = time.time()
    if (raw_scan == st.session_state.get('last_kanban_scan', '') and
            now - st.session_state.get('last_kanban_time', 0) < 2.0):
        st.session_state.barcode_input = ""
        return
    st.session_state.last_kanban_scan = raw_scan
    st.session_state.last_kanban_time = now

    part_no_scanned = raw_scan.split(';')[0].strip()
    main_df_string  = main_df.copy()
    main_df_string['Part_No'] = (
        main_df_string['Part_No'].astype(str)
        .str.replace(r'\.0$', '', regex=True).str.strip()
    )
    match           = main_df_string[main_df_string['Part_No'] == part_no_scanned]
    status_sekarang = st.session_state.get('status_kerja', 'IDLE')
    nama_karyawan   = st.session_state.get('nama_terpilih', '')

    if status_sekarang == "IDLE":
        if 'proses_data' not in st.session_state:
            st.session_state.proses_data = [read_proses_sheet(URL_KITA)]
        df_proses = st.session_state.proses_data[0]
        ongoing   = df_proses[
            (df_proses['Nama'] == nama_karyawan) & (df_proses['Status'] == 'START')
        ]
        if not ongoing.empty:
            row_terakhir = ongoing.iloc[-1]
            p_no         = str(row_terakhir['Part_No']).replace('.0', '').strip()
            match_main   = main_df_string[main_df_string['Part_No'] == p_no]
            st.session_state.current_part = {
                'part_no':       p_no,
                'part_name':     row_terakhir['Part_Name'],
                'model':         row_terakhir['Model'],
                'urutan_proses': row_terakhir['Urutan_Proses'],
                'Actual_Line':   row_terakhir.get('Actual_Line', 'N/A'),
                'line':          row_terakhir['Line'],
                'sec_pcs':       match_main.iloc[0]['SEC /PCS'] if not match_main.empty else 0
            }
            st.session_state.waktu_start  = datetime.strptime(
                f"{row_terakhir['Tanggal']} {row_terakhir['Waktu_Mulai']}", "%Y-%m-%d %H:%M:%S"
            )
            st.session_state.status_kerja = "RUNNING"
            st.session_state.barcode_input = ""
            st.success(f"🔄 Sesi {p_no} dipulihkan!")
            st.rerun()
        elif not match.empty:
            st.session_state.available_processes = match.to_dict('records')
            st.session_state.status_kerja        = "SELECTING_PROCESS"
            st.session_state.barcode_input        = ""
            st.rerun()
        else:
            st.error(f"❌ Part No '{part_no_scanned}' tidak terdaftar di Main Data!")
            st.session_state.barcode_input = ""

    elif status_sekarang == "RUNNING":
        current_p_no = str(st.session_state.current_part['part_no']).strip()
        if part_no_scanned == current_p_no:
            st.session_state.status_kerja  = "FINISHING"
            st.session_state.waktu_end     = get_waktu_wib()
            st.session_state.barcode_input = ""
            st.toast("🏁 Scan Finish Berhasil!")
            st.rerun()
        else:
            st.error(f"❌ Barcode ({part_no_scanned}) berbeda dengan Part aktif: {current_p_no}")
            st.session_state.barcode_input = ""
    # Tidak ada baris barcode_input="" di sini — sudah di-clear di tiap branch


# ============================================================
# LOGIKA UTAMA — routing ke layar yang benar
#
# Alur routing:
#   nama_karyawan kosong      → Layar 1 (scan ID)
#   nama_karyawan ada +
#     is_sudah_checkin False  → Layar 2 (belum check-in)
#   nama_karyawan ada +
#     is_sudah_checkin True   → Layar 3/4 (area produksi)
#
# KUNCI FIX:
#   is_sudah_checkin di-resolve SEBELUM routing ke layar manapun.
#   Blok fallback di bawah hanya berjalan kalau belum terverifikasi
#   oleh scan ID (yang sudah set is_sudah_checkin + data_waktu_kerja).
#   Kalau API gagal di fallback, kita TIDAK override is_sudah_checkin
#   yang sudah di-set oleh scan ID — sehingga tidak false-negative.
# ============================================================
nama_karyawan = st.session_state.get('nama_terpilih', "")
nik_karyawan  = st.session_state.get('nik_karyawan',  "")

if 'is_sudah_checkin' not in st.session_state:
    st.session_state.is_sudah_checkin = False

# ------------------------------------------------------------------
# FALLBACK VERIFIKASI CHECK-IN
# Hanya jalan kalau:
#   1. Operator sudah scan ID (nama_karyawan ada), DAN
#   2. is_sudah_checkin masih False (belum diverifikasi scan ID), DAN
#   3. data_waktu_kerja belum ada di session (scan ID belum simpan)
#
# Kalau scan ID sudah simpan data_waktu_kerja + is_sudah_checkin=True,
# blok ini di-skip seluruhnya — tidak ada API call tambahan.
# ------------------------------------------------------------------
if nama_karyawan and not st.session_state.is_sudah_checkin:
    if 'data_waktu_kerja' not in st.session_state:
        # Data belum ada — perlu fetch. Pakai safe_gsheet_read dengan retry.
        try:
            df_fallback = safe_gsheet_read(conn, URL_KITA, "Waktu Kerja", ttl=30)
            st.session_state.data_waktu_kerja = df_fallback
        except Exception:
            # API gagal — simpan DataFrame kosong sebagai marker,
            # tapi JANGAN override is_sudah_checkin yang mungkin sudah True.
            # is_sudah_checkin tetap False → masuk Layar 2 → operator bisa coba check-in.
            st.session_state.data_waktu_kerja = pd.DataFrame()

    df_cek = st.session_state.data_waktu_kerja
    if not df_cek.empty:
        # Gunakan helper yang sama — exact match, tidak ada str.contains
        nik_bersih    = bersihkan_nik(nik_karyawan)
        checkin_found = df_cek[
            cek_nik_match(df_cek['NIK'], nik_bersih) &
            cek_belum_checkout(df_cek['Check-Out'])
        ]
        # Hanya update ke True jika ditemukan — tidak pernah paksa jadi False
        # kalau sebelumnya sudah True (misal set oleh scan ID)
        if not checkin_found.empty:
            st.session_state.is_sudah_checkin = True
        # Kalau empty tapi sebelumnya sudah True (dari scan ID) → tetap True
        # Kalau empty dan memang False → tetap False → masuk Layar 2

is_sudah_checkin = st.session_state.is_sudah_checkin


# ============================================================
# LAYAR 1: BELUM SCAN ID OPERATOR
# ============================================================
if not nama_karyawan:
    st.subheader("👋 Selamat Datang! Silakan Scan ID Operator")

    # Guard: jika sedang memproses scan sebelumnya, stop render scanner
    # agar scanner tidak kirim ulang data saat rerun
    if st.session_state.get('sedang_proses_scan_id', False):
        st.info("⏳ Memproses data operator, harap tunggu...")
        st.stop()

    barcode_id = qrcode_scanner(key='scanner_id_operator')

    if barcode_id and barcode_id.strip():
        # Bersihkan karakter tersembunyi
        barcode_id = barcode_id.replace('\n','').replace('\r','').replace('\t','').strip()

        # Debounce — cegah ID yang sama diproses 2x dalam 3 detik
        now = time.time()
        if (barcode_id == st.session_state.get('last_id_scan_value', '') and
                now - st.session_state.get('last_id_scan_time', 0) < 3.0):
            st.stop()
        st.session_state.last_id_scan_value = barcode_id
        st.session_state.last_id_scan_time  = now

        # Validasi format — harus ada separator ";"
        if ";" not in barcode_id:
            st.error("❌ Format ID tidak valid. QR Code harus berformat: NIK;Nama")
            st.stop()

        raw_nik  = barcode_id.split(';')[0].strip()
        raw_nama = barcode_id.split(';')[1].strip()

        if not raw_nik or not raw_nama:
            st.error("❌ NIK atau Nama kosong dari hasil scan. Coba scan ulang.")
            st.stop()

        # Verifikasi NIK di master — exact match
        nik_scan_clean   = bersihkan_nik(raw_nik)
        nik_master_clean = [bersihkan_nik(n) for n in st.session_state.list_nik_terdaftar]

        if nik_scan_clean not in nik_master_clean:
            st.error(f"🚫 Akses Ditolak! NIK {raw_nik} tidak terdaftar.")
            time.sleep(2)
            st.rerun()

        # ── Set guard SEBELUM API call ──
        # Ini mencegah scanner re-render dan kirim data saat rerun
        st.session_state.sedang_proses_scan_id = True

        # ── Set identity session SEBELUM API call ──
        # Kalau API gagal setelah ini, identity tetap tersimpan
        st.session_state.nik_karyawan  = raw_nik
        st.session_state.nama_terpilih = raw_nama
        # Reset state lama dari sesi sebelumnya
        st.session_state.pop('data_waktu_kerja', None)
        st.session_state.pop('proses_data', None)
        st.session_state.pop('current_part', None)
        st.session_state.pop('sudah_start_diklik', None)

        # ── STEP 1: Verifikasi check-in SEKARANG (bukan saat rerun) ──
        # Hasilnya langsung disimpan ke session_state agar blok fallback
        # di atas di-skip sepenuhnya saat rerun.
        is_checkin_aktif = False
        df_waktu_fresh   = None

        with st.spinner("Memverifikasi status Check-In..."):
            is_checkin_aktif, df_waktu_fresh = verifikasi_checkin_dari_sheet(raw_nik)

        if df_waktu_fresh is not None:
            # Simpan ke session agar fallback tidak fetch ulang
            st.session_state.data_waktu_kerja = df_waktu_fresh
            st.session_state.is_sudah_checkin = is_checkin_aktif
        else:
            # API gagal — set False, operator akan masuk Layar 2 untuk check-in
            st.session_state.is_sudah_checkin = False
            st.warning("⚠️ Tidak bisa verifikasi check-in (API timeout). Silakan check-in kembali.")

        # ── STEP 2: Cek proses aktif ──
        data_aktif = None
        with st.spinner("Mengecek proses aktif..."):
            try:
                data_aktif = cek_proses_aktif(raw_nik)
            except Exception as e:
                st.warning(f"⚠️ Tidak bisa cek proses aktif: {e}. Melanjutkan sebagai IDLE.")
                data_aktif = None

        # ── STEP 3: Set status kerja berdasarkan data ──
        if data_aktif:
            # Ada proses START yang belum selesai → langsung ke RUNNING
            st.session_state.status_kerja       = "RUNNING"
            st.session_state.sudah_start_diklik = True
            st.session_state.current_part = {
                'part_no':       data_aktif.get('Part_No', ''),
                'part_name':     data_aktif.get('Part_Name', ''),
                'model':         data_aktif.get('Model', ''),
                'line':          data_aktif.get('Line', ''),
                'urutan_proses': data_aktif.get('Urutan_Proses', ''),
                'sec_pcs':       float(data_aktif.get('Sec_Pcs', 0)),
                'Actual_Line':   data_aktif.get('Actual_Line', '')
            }
            try:
                waktu_str = str(data_aktif['Waktu_Mulai'])
                if " " in waktu_str:
                    waktu_str = waktu_str.split(" ")[1]
                st.session_state.waktu_start = datetime.combine(
                    date.today(), datetime.strptime(waktu_str, "%H:%M:%S").time()
                )
            except Exception:
                st.session_state.waktu_start = get_waktu_wib()
            st.success(f"🔄 Melanjutkan proses: {data_aktif.get('Part_Name')}")
        else:
            st.session_state.status_kerja = "IDLE"
            st.success(f"✅ Terverifikasi: {raw_nama}")

        # Lepas guard — proses selesai
        st.session_state.sedang_proses_scan_id = False

        time.sleep(1)
        st.rerun()


# ============================================================
# LAYAR 2: SUDAH SCAN NAMA TAPI BELUM CHECK-IN
# ============================================================
elif not is_sudah_checkin:
    st.warning(f"⚠️ Halo **{nama_karyawan}** | {nik_karyawan} — Anda belum Check-In.")

    # Guard double-click — SEBELUM tombol dirender
    if st.session_state.get('checkin_sedang_proses', False):
        st.warning("⏳ Check-In sedang diproses, harap tunggu...")
        st.stop()

    if st.button("🟢 KLIK UNTUK CHECK-IN SEKARANG", use_container_width=True):
        st.session_state.checkin_sedang_proses = True
        try:
            waktu_skrg = get_waktu_wib()

            # Cek duplikat fresh — ttl=0
            with st.spinner("Memeriksa data Check-In..."):
                df_cek_fresh = safe_gsheet_read(conn, URL_KITA, "Waktu Kerja", ttl=0)

            nik_bersih = bersihkan_nik(nik_karyawan)
            duplikat   = df_cek_fresh[
                cek_nik_match(df_cek_fresh['NIK'], nik_bersih) &
                cek_belum_checkout(df_cek_fresh['Check-Out'])
            ]

            if not duplikat.empty:
                st.warning("⚠️ Anda sudah tercatat Check-In sebelumnya!")
                st.session_state.is_sudah_checkin      = True
                st.session_state.data_waktu_kerja      = df_cek_fresh
                st.session_state.checkin_sedang_proses = False
                time.sleep(1)
                st.rerun()

            # append_row: atomic, tidak ada race condition
            row_checkin = [
                waktu_skrg.strftime("%Y-%m-%d"),  # Tanggal
                nama_karyawan,                     # Nama
                f"'{nik_karyawan}",                # NIK
                waktu_skrg.strftime("%H:%M:%S"),   # Check-In
                "",                                # Check-Out
                "0",                               # Total_Jam
                "Mulai Shift"                      # Aktivitas
            ]

            with st.spinner("Menyimpan Check-In..."):
                ws_waktu = get_worksheet("Waktu Kerja")
                if ws_waktu is None:
                    st.error("❌ Gagal koneksi ke sheet Waktu Kerja.")
                    st.session_state.checkin_sedang_proses = False
                    st.stop()
                berhasil = safe_append_row(ws_waktu, row_checkin)

            if berhasil:
                read_waktu_kerja_sheet.clear()
                st.session_state.pop('data_waktu_kerja', None)
                st.session_state.is_sudah_checkin      = True
                st.session_state.status_kerja          = "IDLE"
                st.session_state.checkin_sedang_proses = False
                st.success("✅ Berhasil Check-In! Scanner Part siap digunakan.")
                time.sleep(1)
                st.rerun()

        except Exception as e:
            st.session_state.checkin_sedang_proses = False
            error_msg = str(e)
            if "429" in error_msg or "quota" in error_msg.lower() or "rate" in error_msg.lower():
                st.error("❌ Google Sheets API kelebihan beban (429). Tunggu 1-2 menit lalu coba lagi.")
                st.info("📋 Data BELUM tersimpan. Jangan tutup aplikasi.")
            elif "500" in error_msg or "503" in error_msg:
                st.error("❌ Server Google bermasalah (500/503). Coba lagi dalam beberapa saat.")
                st.info("📋 Data BELUM tersimpan.")
            elif "403" in error_msg or "forbidden" in error_msg.lower():
                st.error("❌ Akses ditolak (403). Hubungi Admin untuk cek permission Google Sheets.")
            else:
                st.error(f"❌ Gagal Check-In: {error_msg}")
                st.info("📋 Catat waktu check-in manual dan lapor ke Admin.")

    st.divider()
    if st.button("⬅️ Kembali / Scan Ulang ID Operator", type="secondary", use_container_width=True):
        for key in ['nama_terpilih', 'nik_karyawan', 'is_sudah_checkin',
                    'data_waktu_kerja', 'checkin_sedang_proses',
                    'sedang_proses_scan_id', 'last_id_scan_value', 'last_id_scan_time']:
            st.session_state.pop(key, None)
        st.rerun()


# ============================================================
# LAYAR 3 & 4: SUDAH CHECK-IN — AREA PRODUKSI
# ============================================================
else:
    st.success(f"👷 Operator: **{nama_karyawan}** | **{nik_karyawan}** | Sesi Aktif")
    status_kerja = st.session_state.get('status_kerja', 'IDLE')

    # ----------------------------------------------------------
    # STATUS: IDLE
    # ----------------------------------------------------------
    if status_kerja == "IDLE":
        st.write("<span style='font-size: 18px; font-weight: bold;'>📸 Opsi 1: Scan KANBAN untuk mulai proses</span>", unsafe_allow_html=True)
        barcode_part = qrcode_scanner(key='scanner_part_prod')
        if barcode_part and barcode_part.strip():
            st.session_state.barcode_input = barcode_part
            handle_scan()

        st.divider()
        st.write("<span style='font-size: 18px; font-weight: bold;'>⌨️ Opsi 2: Input Part No. Manual</span>", unsafe_allow_html=True)
        manual_input = st.text_input("Ketik Part No.", key="manual_part_input").strip().upper()
        if st.button("✅ Konfirmasi Input Manual", use_container_width=True):
            if manual_input:
                st.session_state.barcode_input = manual_input
                handle_scan()

        st.divider()
        st.write("Jika sudah selesai semua pekerjaan shift ini:")

        with st.popover("🔴 SELESAI SHIFT (CHECK-OUT)", use_container_width=True):
            st.write("### Konfirmasi Check-Out")
            st.warning("Apakah Anda yakin ingin mengakhiri shift sekarang?")
            df_proses_cek         = read_proses_sheet(URL_KITA)
            pekerjaan_menggantung = df_proses_cek[
                (df_proses_cek['Nama'] == nama_karyawan) &
                (df_proses_cek['Status'] == 'START')
            ]
            if not pekerjaan_menggantung.empty:
                st.error(f"❌ Tidak bisa Check-Out! Masih ada pekerjaan aktif: "
                         f"**{pekerjaan_menggantung.iloc[0]['Part_No']}**. Selesaikan dulu.")
            else:
                st.success("✅ Semua pekerjaan sudah selesai.")
                if st.button("YA, SAYA YAKIN CHECK-OUT", type="primary", use_container_width=True):
                    with st.spinner("Memproses Check-Out..."):
                        try:
                            waktu_out     = get_waktu_wib()
                            df_waktu      = safe_gsheet_read(conn, URL_KITA, "Waktu Kerja", ttl=0).copy()
                            checkin_row   = get_last_active_row(df_waktu, nama_karyawan)
                            if checkin_row:
                                dt_in           = get_checkin_datetime(checkin_row, waktu_out)
                                total_jam_shift = round((waktu_out - dt_in).total_seconds() / 3600, 2)
                                mask_update = (
                                    (df_waktu['Nama'] == nama_karyawan) &
                                    cek_belum_checkout(df_waktu['Check-Out'])
                                )
                                idx_pd = df_waktu[mask_update].index[-1]
                                df_waktu.at[idx_pd, 'Check-Out'] = waktu_out.strftime("%H:%M:%S")
                                df_waktu.at[idx_pd, 'Total_Jam'] = total_jam_shift
                                df_waktu.at[idx_pd, 'Aktivitas'] = "Shift Complete"
                                safe_gsheet_update(conn, URL_KITA, "Waktu Kerja", df_waktu)
                                read_waktu_kerja_sheet.clear()
                                st.session_state.pop('data_waktu_kerja', None)
                                st.session_state.is_sudah_checkin = False
                                st.session_state.nama_terpilih    = ""
                                st.session_state.nik_karyawan     = ""
                                st.session_state.status_kerja     = "IDLE"
                                st.success(f"✅ Check-Out Berhasil! Total: {total_jam_shift} jam")
                                time.sleep(3)
                                st.rerun()
                            else:
                                st.error("❌ Data Check-In aktif tidak ditemukan!")
                        except Exception as e:
                            err = str(e)
                            if "429" in err or "quota" in err.lower():
                                st.error("❌ API Quota habis saat Check-Out. Tunggu 1-2 menit.")
                            elif "500" in err or "503" in err:
                                st.error("❌ Server Google bermasalah. Coba lagi.")
                            else:
                                st.error(f"❌ Gagal Check-Out: {err}")
                            st.info("📋 Data BELUM tersimpan. Jangan tutup aplikasi.")

            st.divider()
            if st.button("⬅️ Ganti Operator / Salah Scan Nama", use_container_width=True):
                for key in ['nama_terpilih', 'nik_karyawan', 'is_sudah_checkin',
                            'status_kerja', 'data_waktu_kerja', 'checkin_sedang_proses',
                            'sedang_proses_scan_id', 'last_id_scan_value', 'last_id_scan_time']:
                    st.session_state.pop(key, None)
                st.rerun()

    # ----------------------------------------------------------
    # STATUS: SELECTING_PROCESS
    # ----------------------------------------------------------
    elif status_kerja == "SELECTING_PROCESS":
        st.subheader("🔍 Pilih Urutan Proses")
        data_pilihan = st.session_state.get('available_processes', [])
        list_line    = list(dict.fromkeys(
            (main_df['LINE'].unique().tolist() if 'LINE' in main_df.columns else []) +
            ["BM", "CM", "DM", "ERM", "NRM", "IRM", "KRM"]
        ))
        if not any(p.get('URUTAN') == 'DPMR' for p in data_pilihan):
            sample = data_pilihan[0] if data_pilihan else {}
            data_pilihan.append({
                'URUTAN': 'DPMR', 'Part_Name': sample.get('Part_Name', 'REPAIR'),
                'Part_No': sample.get('Part_No', 'REPAIR'),
                'MODEL': sample.get('MODEL', 'REPAIR'),
                'LINE': sample.get('LINE', '-'), 'SEC /PCS': 0
            })
        actual_line  = st.selectbox("Pilih Line Produksi (Actual Line)", options=list_line)
        opsi_display = {f"{p['URUTAN']} | {p['Part_Name']}": p for p in data_pilihan}
        pilihan_user = st.selectbox("Pilih Urutan Proses Produksi", options=list(opsi_display.keys()))
        if st.button("Konfirmasi & Mulai Kerja"):
            detail = opsi_display[pilihan_user]
            st.session_state.current_part = {
                "part_no":       detail.get('Part_No', 'N/A'),
                "part_name":     detail.get('Part_Name', 'N/A'),
                "model":         detail.get('MODEL', 'N/A'),
                "sec_pcs":       detail.get('SEC /PCS', 0),
                "line":          detail.get('LINE', 'N/A'),
                "Actual_Line":   actual_line,
                "urutan_proses": detail.get('URUTAN', 'DPMR')
            }
            st.session_state.status_kerja = "RUNNING"
            st.session_state.waktu_start  = get_waktu_wib()
            st.rerun()

    # ----------------------------------------------------------
    # STATUS: RUNNING
    # ----------------------------------------------------------
    elif status_kerja == "RUNNING":
        dp = st.session_state.get('current_part')
        if dp:
            durasi_live = get_waktu_wib() - st.session_state.waktu_start.replace(tzinfo=None)
            menit_live  = int(durasi_live.total_seconds() / 60)
            jam_live    = round(durasi_live.total_seconds() / 3600, 2)

            st.info(f"⚡ **Proses Berjalan:** {dp['part_name']} | {dp['part_no']}")
            st.write("Konfirmasi Mulai Kerja")

            if not st.session_state.get('sudah_start_diklik'):
                if st.button("🚀 Konfirmasi Start Proses", use_container_width=True):
                    data_start = {
                        "Tanggal":       get_waktu_wib().strftime("%Y-%m-%d"),
                        "Nama":          nama_karyawan,
                        "NIK":           f"'{st.session_state.get('nik_karyawan', '-')}",
                        "Part_No":       dp['part_no'],
                        "Part_Name":     dp['part_name'],
                        "Model":         dp['model'],
                        "Line":          dp['line'],
                        "Urutan_Proses": dp['urutan_proses'],
                        "Actual_Line":   dp.get('Actual_Line', ""),
                        "Sec_Pcs":       dp['sec_pcs'],
                        "Waktu_Mulai":   st.session_state.waktu_start.strftime("%H:%M:%S"),
                        "Waktu_Selesai": "", "ACT": 0, "NG": 0,
                        "%_Prod": "", "Total Istirahat": "",
                        "Rasio_NG": "", "Total_Jam": "", "Status": "START"
                    }
                    if simpan_ke_sheet(data_start, "START"):
                        st.session_state.sudah_start_diklik = True
                        st.balloons()
                        time.sleep(2)
                        st.success("✅ Produksi Dimulai!")
                        st.rerun()
            else:
                st.success("✅ Proses Sudah Dimulai")
                st.info("JIKA DPMR: Masukkan jumlah Part OK dan NG di INPUT ABNORMAL!")

            col1, col2, col3, col4, col5 = st.columns(5, gap="small")
            col1.metric("Urutan",         dp['urutan_proses'])
            col2.metric("Target Sec/Pcs", dp['sec_pcs'])
            col3.metric("Mulai",          st.session_state.waktu_start.strftime('%H:%M:%S'))
            col4.metric("Sudah Berjalan", f"{menit_live} Menit", delta=f"{jam_live} Jam")
            col5.metric("Actual Line",    dp.get('Actual_Line', ''))

            st.divider()

            with st.expander("⚠️ INPUT ABNORMAL", expanded=False):
                st.write("Input langsung tersimpan ke database. Jika DPMR, tulis OK dan NG total di Keterangan.")
                list_kode = [
                    "A [Ganti Proses]", "B [Ganti/Tambah Coil]", "C [Periksa ATA]",
                    "D [Trial]", "E [2S]", "F [Briefing Rutin]",
                    "G1 [Material NG dan Tukar Proses]", "G2 [Kualitas NG dan Tukar Proses]",
                    "H [Tooling]", "I [Mesin Abnormal]", "K1 [Penanganan Kualitas NG]",
                    "K2 [Penanganan Dies NG]", "L [Kekurangan Material]",
                    "M [Lain-Lain]", "N [No KANBAN Plan]", "O [DPMR]"
                ]
                if "ab_counter" not in st.session_state:
                    st.session_state.ab_counter = 0
                c_kod, c_men, c_ket = st.columns([1, 1, 2])
                k_sel    = c_kod.selectbox("Kode", options=list_kode,
                               key=f"ab_kode_run_{st.session_state.ab_counter}")
                m_val    = c_men.number_input("Menit", min_value=0, step=1,
                               key=f"ab_menit_run_{st.session_state.ab_counter}")
                kt_val   = c_ket.text_input("Keterangan", placeholder="Contoh: Mesin Down",
                               key=f"ab_ket_run_{st.session_state.ab_counter}").upper()
                if st.button("🚀 Kirim Data Abnormal", use_container_width=True,
                             key=f"btn_ab_submit_{st.session_state.ab_counter}"):
                    if not st.session_state.get('sudah_start_diklik'):
                        st.error("⚠️ Klik tombol START PROSES sebelum kirim data abnormal!")
                    elif k_sel and m_val > 0:
                        parts           = k_sel.split(" [")
                        kode_hanya      = parts[0]
                        uraian_abnormal = parts[1].replace("]", "") if len(parts) > 1 else ""
                        row_ab = {
                            "Tanggal":         get_waktu_wib().strftime("%Y-%m-%d"),
                            "Mesin":           dp.get('Actual_Line', ''),
                            "Part_No":         dp.get('part_no', ''),
                            "Model":           dp.get('model', ''),
                            "Part_Name":       dp.get('part_name', ''),
                            "Urutan_Proses":   dp.get('urutan_proses', ''),
                            "Operator":        nama_karyawan,
                            "Kode_Abnormal":   kode_hanya,
                            "Uraian_Abnormal": uraian_abnormal,
                            "Total_Waktu":     m_val,
                            "Keterangan":      kt_val
                        }
                        if simpan_ke_sheet(row_ab, "ABNORMAL"):
                            st.toast(f"✅ Kode {k_sel} tersimpan!")
                            st.session_state.ab_counter += 1
                            time.sleep(1)
                    else:
                        st.error("Pilih Kode & isi Menit terlebih dahulu!")

            st.divider()
            st.write("<span style='font-size: 18px; font-weight: bold;'>📸 SCAN KANBAN untuk FINISH</span>", unsafe_allow_html=True)
            barcode_data = qrcode_scanner(key='scanner_finish_part')
            if barcode_data and barcode_data.strip():
                st.session_state.barcode_input = barcode_data
                handle_scan()

            st.divider()
            st.write("<span style='font-size: 18px; font-weight: bold;'>⌨️ Input KANBAN Manual</span>", unsafe_allow_html=True)
            manual_finish = st.text_input("Ketik Part No", key="manual_part_finish_input").strip().upper()
            if st.button("✅ Konfirmasi Input Manual Finish", use_container_width=True):
                if manual_finish:
                    st.session_state.barcode_input = manual_finish
                    handle_scan()

    # ----------------------------------------------------------
    # STATUS: FINISHING
    # ----------------------------------------------------------
    elif status_kerja == "FINISHING":
        dp = st.session_state.get('current_part')
        if dp:
            st.subheader(f"📝 Laporan Akhir: {dp['part_name']}")
            waktu_start   = st.session_state.get('waktu_start', get_waktu_wib())
            waktu_end     = st.session_state.get('waktu_end',   get_waktu_wib())
            durasi        = waktu_end.replace(tzinfo=None) - waktu_start.replace(tzinfo=None)
            jam_total     = durasi.total_seconds() / 60
            jam_bersih    = jam_total % 1440

            c1, c2, c3, c4 = st.columns(4)
            act_raw = c1.text_input("Jumlah ACT", value="0")
            ng_raw  = c2.text_input("Jumlah NG",  value="0")
            try:
                act = int(act_raw)
                ng  = int(ng_raw)
            except ValueError:
                act = 0; ng = 0

            c3.metric("Durasi",      f"{round(jam_total, 2)} Menit",
                      delta=f"{round(jam_total/60, 2)} Jam")
            c4.metric("Waktu Start", st.session_state.waktu_start.strftime("%H:%M:%S"))

            st.write("### ☕ Potongan Waktu Istirahat")
            DAFTAR_BREAK   = {"Break 1 (10m)": 10, "Break 2 (10m)": 10,
                              "Istirahat (40m)": 40, "Extra Break (15m)": 15, "2S (15m)": 15}
            pilihan_break  = st.multiselect("Pilih:", options=list(DAFTAR_BREAK.keys()))
            extra_custom   = st.number_input("Lainnya (Menit)", min_value=0, step=1, value=0)
            total_potongan = sum(DAFTAR_BREAK[i] for i in pilihan_break) + extra_custom
            durasi_bersih  = max(0, jam_bersih - total_potongan)
            st.info(f"⏱️ Durasi Bersih: {durasi_bersih:.1f} Menit")

            is_repair     = (dp.get('urutan_proses') == "DPMR")
            val_sec_pcs   = float(dp.get('sec_pcs', 0))
            standar_input = (val_sec_pcs * act) / 60 if (act > 0 and not is_repair) else 0
            persen_prod   = round((standar_input / durasi_bersih) * 100, 2) \
                            if (durasi_bersih > 0 and not is_repair) else 0.0

            if st.button("🚀 Kirim Data SPH", use_container_width=True):
                if act > 0:
                    data_finish = {
                        "Part_No":         dp['part_no'],
                        "Waktu_Selesai":   waktu_end.strftime("%H:%M:%S"),
                        "ACT":             act, "NG": ng,
                        "%_Prod":          "N/A" if is_repair else f"{persen_prod:.2f}%",
                        "Total Istirahat": total_potongan,
                        "Rasio_NG":        "N/A" if is_repair else
                                           (f"{(ng/act*100):.2f}%" if act > 0 else "0%"),
                        "Total_Jam":       round(durasi_bersih / 60, 2),
                        "Status":          "FINISH"
                    }
                    if simpan_ke_sheet(data_finish, "FINISH"):
                        st.session_state.data_sph_terkirim = True
                        st.success("✅ SPH Terkirim!")
                else:
                    st.error("⚠️ Jumlah ACT harus diisi dan lebih dari 0!")

            if st.session_state.get('data_sph_terkirim'):
                st.divider()
                st.subheader("📊 Ringkasan Hasil Produksi")
                c1, c2, c3 = st.columns(3, gap="medium")
                c1.metric("Persentase Produksi", f"{persen_prod:.2f} %")
                c2.metric("Total Jam Kerja",      f"{round(durasi_bersih/60, 2)} Jam")
                c3.metric("Rasio NG",              f"{(ng/act * 100) if act > 0 else 0:.2f} %")
                st.info("✅ Data SPH sudah tercatat di database.")
                st.divider()

                if st.button("🏁 SELESAI & SCAN PART BARU", type="primary", use_container_width=True):
                    for k in ['status_kerja', 'current_part', 'waktu_start', 'waktu_end',
                              'data_sph_terkirim', 'available_processes', 'sudah_start_diklik',
                              'barcode_input', 'is_submitting', 'proses_data', 'abnormal_data',
                              'ab_counter', 'last_kanban_scan', 'last_kanban_time']:
                        st.session_state.pop(k, None)
                    st.session_state.status_kerja = "IDLE"
                    st.balloons()
                    st.success("✅ Laporan selesai! Siap scan part baru.")
                    time.sleep(2)
                    st.rerun()

    # ----------------------------------------------------------
    # Tombol Reset — selalu tampil saat logged in
    # ----------------------------------------------------------
    if st.session_state.get('status_kerja') == "RUNNING":
        col_ref, col_res = st.columns(2)
        with col_ref:
            if st.button("🔄 Perbarui Waktu"):
                st.rerun()
        with col_res:
            if st.button("🚫 Reset Scanner", type="secondary"):
                for k in ['status_kerja', 'current_part', 'waktu_start',
                          'waktu_end', 'sudah_start_diklik', 'proses_data',
                          'last_kanban_scan', 'last_kanban_time']:
                    st.session_state.pop(k, None)
                st.rerun()
    else:
        if st.button("❌ Reset Scanner", type="secondary"):
            for k in ['status_kerja', 'current_part', 'proses_data',
                      'last_kanban_scan', 'last_kanban_time']:
                st.session_state.pop(k, None)
            st.rerun()
