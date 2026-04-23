import streamlit as st
import streamlit.components.v1 as components
from streamlit_qrcode_scanner import qrcode_scanner
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import pytz
from datetime import datetime, timedelta, date
import time
import random

# ============================================================
# FIX 1: set_page_config WAJIB di baris pertama sebelum apapun
# ============================================================
st.set_page_config(page_title="Laporan Produksi Press PT. ISI", layout="wide")

# ============================================================
# SAFE API WRAPPERS — retry otomatis untuk 429 / 500 / 503
# ============================================================

def safe_gsheet_update(conn, spreadsheet, worksheet, data, max_retries=4):
    """
    Wrapper conn.update dengan exponential backoff + jitter.
    Menangani 429 Quota Exceeded dan 500/503 Server Error.
    """
    for attempt in range(max_retries):
        try:
            conn.update(spreadsheet=spreadsheet, worksheet=worksheet, data=data)
            return True
        except Exception as e:
            error_str = str(e).lower()
            is_429 = "429" in error_str or "quota" in error_str or "rate" in error_str
            is_5xx = "500" in error_str or "503" in error_str or "internal" in error_str
            is_retryable = is_429 or is_5xx

            if is_retryable and attempt < max_retries - 1:
                base_wait = (2 ** (attempt + 1)) + 2
                jitter = random.uniform(0, 2)
                wait_time = round(base_wait + jitter, 1)
                st.warning(f"⏳ Server sibuk, mencoba ulang dalam {wait_time} detik... ({attempt+1}/{max_retries-1})")
                time.sleep(wait_time)
                continue
            else:
                raise e
    return False


def safe_gsheet_read(conn, spreadsheet, worksheet, ttl=10, max_retries=4):
    """
    Wrapper conn.read dengan exponential backoff + jitter.
    """
    for attempt in range(max_retries):
        try:
            df = conn.read(spreadsheet=spreadsheet, worksheet=worksheet, ttl=ttl)
            return df
        except Exception as e:
            error_str = str(e).lower()
            is_retryable = any(
                code in error_str for code in ["429", "500", "503", "quota", "rate", "internal"]
            )
            if is_retryable and attempt < max_retries - 1:
                base_wait = (2 ** (attempt + 1)) + 2
                jitter = random.uniform(0, 2)
                wait_time = round(base_wait + jitter, 1)
                st.warning(f"⏳ Membaca data, mencoba ulang dalam {wait_time} detik... ({attempt+1}/{max_retries-1})")
                time.sleep(wait_time)
                continue
            else:
                raise e
    return pd.DataFrame()


# ============================================================
# JAVASCRIPT — cegah refresh tidak sengaja
# ============================================================
components.html(
    """
    <script>
    window.parent.addEventListener('beforeunload', function (e) {
        var confirmationMessage = 'Data sedang diproses. Jika refresh, sesi scan akan hilang!';
        (e || window.event).returnValue = confirmationMessage;
        return confirmationMessage;
    });
    </script>
    """,
    height=0,
)

# ============================================================
# CSS STYLING
# ============================================================
st.markdown("""
    <style>
    .block-container {
        padding-top: 1.5rem !important;
    }
    header {
        visibility: hidden;
    }
    h1 {
        margin-top: -10px !important;
        padding-top: 0px !important;
        margin-bottom: 5px !important;
        line-height: 1.1 !important;
    }
    .stApp {
        background-color: #261ad6;
    }
    [data-testid="stSidebar"] {
        background-color: #b30000;
    }
    h1, h2, h3, p, span, label, .stMarkdown {
        color: #ffffff !important;
    }
    div.stButton > button {
        background-color: #00FF00 !important;
        color: black !important;
        border-radius: 10px;
        font-weight: bold !important;
    }
    div.stButton > button[key="btn_reset_biru"] {
        background: linear-gradient(45deg, #FF4444, #CC0000) !important;
        color: white !important;
        border: 2px solid #990000 !important;
        border-radius: 8px !important;
    }
    div.stButton > button p {
        font-size: 18px !important;
        font-weight: bold !important;
        color: black !important;
    }
    div.stButton > button[key="btn_reset_biru"] p {
        color: white !important;
        font-weight: bold !important;
        font-size: 18px !important;
    }
    div.stMarkdown p {
        font-size: 16px !important;
        font-weight: normal !important;
        line-height: 1.5 !important;
        font-family: sans-serif !important;
    }
    hr {
        margin-top: 0.5rem !important;
        margin-bottom: 0.5rem !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.3) !important;
    }
    div[data-testid="stTextInput"] input {
        background-color: #000000 !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    div[data-testid="stNumberInput"] input {
        background-color: #000000 !important;
        color: #ffffff !important;
    }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] {
        background-color: #000000 !important;
        color: #ffffff !important;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #ffffff !important;
        box-shadow: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ============================================================
# JUDUL
# ============================================================
st.markdown(
    """
    <h1 style='text-align: center; font-size: 28px; margin-top: -20px; margin-bottom: 0px; line-height: 1.2;'>
        📟 Laporan Produksi Dept. Press <br> PT Indosafety Sentosa
    </h1>
    """,
    unsafe_allow_html=True
)

# ============================================================
# SIDEBAR — tombol update data master
# ============================================================
if st.sidebar.button("🔄 Update Data Master"):
    st.cache_data.clear()
    st.success("Data berhasil diperbarui!")
    st.rerun()

# ============================================================
# FUNGSI WAKTU
# ============================================================
def get_waktu_wib():
    tz_jkt = pytz.timezone('Asia/Jakarta')
    return datetime.now(tz_jkt).replace(tzinfo=None)


def get_checkin_datetime(checkin_row, waktu_out):
    """
    Parse Check-In datetime, handle cross-midnight shift.
    Nama kolom sesuai sheet: 'Tanggal', 'Check-In'.
    """
    tgl_in = checkin_row['Tanggal']
    jam_in = checkin_row['Check-In']
    try:
        dt_in = datetime.strptime(f"{tgl_in} {jam_in}", "%Y-%m-%d %H:%M:%S")
        if dt_in > waktu_out:
            dt_in = dt_in - timedelta(days=1)
        return dt_in
    except Exception:
        return waktu_out - timedelta(hours=8)

# ============================================================
# KONFIGURASI URL & KONEKSI
# ============================================================
URL_KITA = "https://docs.google.com/spreadsheets/d/1uDmbbLhFsMdGSnozbRBMwEDPP2T20HqpEnJGYd2P390/edit"

if 'waktu_end' not in st.session_state:
    st.session_state.waktu_end = get_waktu_wib()
if 'waktu_start' not in st.session_state:
    st.session_state.waktu_start = get_waktu_wib()

conn = st.connection("gsheets", type=GSheetsConnection)

# Load Master_Karyawan sekali per session — kolom: NIK
if 'list_nik_terdaftar' not in st.session_state:
    try:
        df_karyawan = safe_gsheet_read(conn, URL_KITA, "Master_Karyawan", ttl=3600)
        st.session_state.list_nik_terdaftar = df_karyawan['NIK'].astype(str).str.strip().tolist()
    except Exception:
        st.session_state.list_nik_terdaftar = []

if 'nama_terpilih' not in st.session_state:
    st.session_state.nama_terpilih = ""
if 'nik_karyawan' not in st.session_state:
    st.session_state.nik_karyawan = ""

# ============================================================
# CACHED SHEET READERS
# Nama worksheet sesuai GSheet: "MainData", "Proses",
# "ABNORMAL", "Waktu Kerja", "Master_Karyawan"
# ============================================================

@st.cache_data(ttl=3600)
def get_main_data(url):
    """Worksheet: MainData — kolom: Part_No, Part_Name, MODEL, LINE, URUTAN, SEC /PCS"""
    df = conn.read(spreadsheet=url, worksheet="MainData", ttl=3600)
    df.columns = df.columns.str.strip()
    return df

@st.cache_data(ttl=10)
def read_proses_sheet(url):
    """
    Worksheet: Proses
    Kolom: Tanggal, Nama, NIK, Part_No, Part_Name, Model, Line,
           Urutan_Proses, Actual_Line, Sec_Pcs, Waktu_Mulai,
           Waktu_Selesai, ACT, NG, %_Prod, Total Istirahat,
           Rasio_NG, Total_Jam, Status
    """
    df = conn.read(spreadsheet=url, worksheet="Proses", ttl=10)
    df.columns = df.columns.str.strip()
    return df

@st.cache_data(ttl=30)
def read_abnormal_sheet(url):
    """
    Worksheet: ABNORMAL
    Kolom: Tanggal, Mesin, Part_No, Model, Part_Name,
           Urutan_Proses, Operator, Kode_Abnormal,
           Uraian_Abnormal, Total_Waktu, Keterangan
    """
    return conn.read(spreadsheet=url, worksheet="ABNORMAL", ttl=30)

@st.cache_data(ttl=30)
def read_waktu_kerja_sheet(url):
    """
    Worksheet: Waktu Kerja
    Kolom: Tanggal, Nama, NIK, Check-In, Check-Out,
           Total_Jam, Aktivitas
    """
    return conn.read(spreadsheet=url, worksheet="Waktu Kerja", ttl=30)


try:
    main_df = get_main_data(URL_KITA)
except Exception as e:
    st.error(f"Gagal memuat MainData: {e}")
    main_df = pd.DataFrame()

# ============================================================
# FUNGSI SIMPAN KE SHEET — semua pakai safe_gsheet_update
# ============================================================
def simpan_ke_sheet(data_dict, tipe):
    """
    tipe: "START" | "FINISH" | "ABNORMAL"
    Semua nama key di data_dict harus sesuai nama kolom di GSheet.
    """
    try:
        if tipe == "START":
            df_proses = read_proses_sheet(URL_KITA).copy()

            # Cek duplikat START untuk operator yang sama
            double_check = df_proses[
                (df_proses['Nama'] == data_dict['Nama']) &
                (df_proses['Status'] == 'START')
            ]
            if not double_check.empty:
                st.error("⚠️ Data START sudah ada di database. Klik Reset Scanner lalu scan ulang.")
                return False

            updated_df = pd.concat([df_proses, pd.DataFrame([data_dict])], ignore_index=True)
            safe_gsheet_update(conn, URL_KITA, "Proses", updated_df)
            read_proses_sheet.clear()
            return True

        elif tipe == "FINISH":
            df_proses = read_proses_sheet(URL_KITA).copy()

            # Konversi kolom angka ke object agar bisa diisi string/float campuran
            kolom_angka = ['Total_Jam', 'Rasio_NG', '%_Prod', 'ACT', 'NG']
            for col in kolom_angka:
                if col in df_proses.columns:
                    df_proses[col] = df_proses[col].astype(object)

            nama_karyawan = st.session_state.get('nama_terpilih', '')
            mask = (
                (df_proses['Nama'].astype(str).str.strip() == str(nama_karyawan).strip()) &
                (df_proses['Part_No'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    == str(data_dict['Part_No']).strip()) &
                (df_proses['Status'] == 'START')
            )

            if mask.any():
                idx = df_proses[mask].index[-1]
                # Nama kolom sesuai sheet
                df_proses.at[idx, 'Waktu_Selesai']   = data_dict['Waktu_Selesai']
                df_proses.at[idx, 'ACT']              = data_dict['ACT']
                df_proses.at[idx, 'NG']               = data_dict['NG']
                df_proses.at[idx, '%_Prod']           = data_dict['%_Prod']
                df_proses.at[idx, 'Total Istirahat']  = data_dict['Total Istirahat']
                df_proses.at[idx, 'Rasio_NG']         = data_dict['Rasio_NG']
                df_proses.at[idx, 'Total_Jam']        = data_dict['Total_Jam']
                df_proses.at[idx, 'Status']           = 'FINISH'

                safe_gsheet_update(conn, URL_KITA, "Proses", df_proses)
                read_proses_sheet.clear()
                return True
            else:
                st.error("❌ Tidak ditemukan data START aktif untuk Part ini. Lakukan Scan Start dulu!")
                return False

        elif tipe == "ABNORMAL":
            df_existing = read_abnormal_sheet(URL_KITA).copy()
            updated_df = pd.concat([df_existing, pd.DataFrame([data_dict])], ignore_index=True)
            safe_gsheet_update(conn, URL_KITA, "ABNORMAL", updated_df)
            read_abnormal_sheet.clear()
            if 'abnormal_data' in st.session_state:
                del st.session_state.abnormal_data
            return True

    except Exception as e:
        st.error(f"Gagal memproses data. Catat laporan dan lapor ke Admin. Error: {e}")
        return False


# ============================================================
# FUNGSI BANTU: CARI BARIS CHECK-IN AKTIF (belum check-out)
# Kolom sheet: Nama, Check-Out
# ============================================================
def get_last_active_row(df, nama):
    if 'Check-Out' not in df.columns or 'Nama' not in df.columns:
        return None
    nama_target = str(nama).strip()
    mask = (
        (df['Nama'].astype(str).str.strip() == nama_target) &
        (df['Check-Out'].isna() | (df['Check-Out'].astype(str).str.strip() == ""))
    )
    active_rows = df[mask]
    if not active_rows.empty:
        return active_rows.iloc[-1].to_dict()
    return None


# ============================================================
# FUNGSI BANTU: CEK PROSES AKTIF (START) UNTUK OPERATOR
# Kolom sheet: NIK, Status
# ============================================================
def cek_proses_aktif(nik_input):
    try:
        df = read_proses_sheet(URL_KITA).copy()
        if df.empty:
            return None
        df['NIK'] = df['NIK'].astype(str).str.replace("'", "").str.strip()
        nik_clean = str(nik_input).replace("'", "").strip()
        proses_ongoing = df[(df['NIK'] == nik_clean) & (df['Status'] == 'START')]
        if not proses_ongoing.empty:
            return proses_ongoing.iloc[-1].to_dict()
        return None
    except Exception as e:
        st.error(f"Error pengecekan data proses aktif: {e}")
        return None


# ============================================================
# LOGIKA SCAN BARCODE / KANBAN
# ============================================================
def handle_scan():
    raw_scan = st.session_state.get('barcode_input', '').strip()
    if not raw_scan:
        return

    part_no_scanned = raw_scan.split(';')[0].strip()

    main_df_string = main_df.copy()
    main_df_string['Part_No'] = (
        main_df_string['Part_No']
        .astype(str)
        .str.replace(r'\.0$', '', regex=True)
        .str.strip()
    )

    match = main_df_string[main_df_string['Part_No'] == part_no_scanned]
    status_sekarang = st.session_state.get('status_kerja', 'IDLE')

    if status_sekarang == "IDLE":
        # Pakai cached function, bukan conn.read langsung
        if 'proses_data' not in st.session_state:
            st.session_state.proses_data = [read_proses_sheet(URL_KITA)]

        df_proses = st.session_state.proses_data[0]
        nama_karyawan = st.session_state.get('nama_terpilih', '')
        ongoing = df_proses[
            (df_proses['Nama'] == nama_karyawan) &
            (df_proses['Status'] == 'START')
        ]

        if not ongoing.empty:
            row_terakhir = ongoing.iloc[-1]
            p_no = str(row_terakhir['Part_No']).replace('.0', '').strip()
            match_main = main_df_string[main_df_string['Part_No'] == p_no]

            st.session_state.current_part = {
                'part_no':        p_no,
                'part_name':      row_terakhir['Part_Name'],
                'model':          row_terakhir['Model'],
                'urutan_proses':  row_terakhir['Urutan_Proses'],
                'Actual_Line':    row_terakhir.get('Actual_Line', 'N/A'),
                'line':           row_terakhir['Line'],
                'sec_pcs':        match_main.iloc[0]['SEC /PCS'] if not match_main.empty else 0
            }

            dt_str = f"{row_terakhir['Tanggal']} {row_terakhir['Waktu_Mulai']}"
            st.session_state.waktu_start = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            st.session_state.status_kerja = "RUNNING"
            st.success(f"🔄 Sesi {p_no} dipulihkan!")
            st.session_state.barcode_input = ""
            st.rerun()

        elif not match.empty:
            st.session_state.available_processes = match.to_dict('records')
            st.session_state.status_kerja = "SELECTING_PROCESS"
            st.session_state.barcode_input = ""
            st.rerun()
        else:
            st.error(f"❌ Part No '{part_no_scanned}' tidak terdaftar di Main Data!")
            st.session_state.barcode_input = ""

    elif status_sekarang == "RUNNING":
        current_p_no = str(st.session_state.current_part['part_no']).strip()
        if part_no_scanned == current_p_no:
            st.session_state.status_kerja = "FINISHING"
            st.session_state.waktu_end = get_waktu_wib()
            st.toast("🏁 Scan Finish Berhasil!")
            st.session_state.barcode_input = ""
            st.rerun()
        else:
            st.error(f"❌ Barcode ({part_no_scanned}) berbeda dengan Part aktif: {current_p_no}")
            st.session_state.barcode_input = ""

    st.session_state.barcode_input = ""


# ============================================================
# LOGIKA UTAMA — baca session state
# ============================================================
nama_karyawan = st.session_state.get('nama_terpilih', "")
nik_karyawan  = st.session_state.get('nik_karyawan', "")

if 'is_sudah_checkin' not in st.session_state:
    st.session_state.is_sudah_checkin = False

# Cek status check-in dari sheet jika belum terverifikasi di session
if nama_karyawan and not st.session_state.is_sudah_checkin:
    if 'data_waktu_kerja' not in st.session_state:
        try:
            st.session_state.data_waktu_kerja = read_waktu_kerja_sheet(URL_KITA)
        except Exception:
            st.session_state.data_waktu_kerja = pd.DataFrame()

    df_cek = st.session_state.data_waktu_kerja

    if not df_cek.empty:
        # FIX 5: exact match NIK, bukan str.contains — hindari false positive
        nik_clean = str(nik_karyawan).replace("'", "").replace(".", "").strip()
        checkin_found = df_cek[
            (df_cek['NIK'].astype(str).str.replace("'", "").str.replace(".", "").str.strip() == nik_clean) &
            (df_cek['Check-Out'].isna() | (df_cek['Check-Out'].astype(str).str.strip() == ""))
        ]
        st.session_state.is_sudah_checkin = not checkin_found.empty

is_sudah_checkin = st.session_state.is_sudah_checkin


# ============================================================
# LAYAR 1: BELUM SCAN ID OPERATOR
# ============================================================
if not nama_karyawan:
    st.subheader("👋 Selamat Datang! Silakan Scan ID Operator")
    barcode_id = qrcode_scanner(key='scanner_id_operator')

    if barcode_id:
        if ";" in barcode_id:
            raw_nik  = barcode_id.split(';')[0].strip()
            raw_nama = barcode_id.split(';')[1].strip()

            # FIX 5: exact match saat verifikasi NIK master
            nik_scan_clean   = raw_nik.replace(".", "").strip()
            nik_master_clean = [str(n).replace(".", "").strip() for n in st.session_state.list_nik_terdaftar]

            if nik_scan_clean in nik_master_clean:
                st.session_state.nik_karyawan   = raw_nik
                st.session_state.nama_terpilih  = raw_nama
                st.session_state.is_sudah_checkin = False

                if 'data_waktu_kerja' in st.session_state:
                    del st.session_state.data_waktu_kerja

                with st.spinner("Mengecek status kerja terakhir..."):
                    data_aktif = cek_proses_aktif(raw_nik)

                if data_aktif:
                    st.session_state.status_kerja      = "RUNNING"
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
                        jam_obj = datetime.strptime(waktu_str, "%H:%M:%S").time()
                        st.session_state.waktu_start = datetime.combine(date.today(), jam_obj)
                    except Exception:
                        st.session_state.waktu_start = get_waktu_wib()

                    st.success(f"🔄 Melanjutkan proses: {data_aktif.get('Part_Name')}")
                else:
                    st.session_state.status_kerja = "IDLE"
                    st.success(f"✅ Terverifikasi: {raw_nama}")

                time.sleep(1)
                st.rerun()

            else:
                st.error(f"🚫 Akses Ditolak! NIK {raw_nik} tidak terdaftar.")
                time.sleep(2)
                st.rerun()


# ============================================================
# LAYAR 2: SUDAH SCAN NAMA TAPI BELUM CHECK-IN
# ============================================================
elif not is_sudah_checkin:
    st.warning(f"⚠️ Halo **{nama_karyawan}** | {nik_karyawan} — Anda belum Check-In.")

    # FIX 4: Guard double-click SEBELUM tombol dirender
    if st.session_state.get('checkin_sedang_proses', False):
        st.warning("⏳ Check-In sedang diproses, harap tunggu...")
        st.stop()

    if st.button("🟢 KLIK UNTUK CHECK-IN SEKARANG", use_container_width=True):
        st.session_state.checkin_sedang_proses = True

        try:
            waktu_skrg = get_waktu_wib()

            with st.spinner("Membaca data Check-In..."):
                # ttl=0 agar selalu baca data terbaru saat check-in
                df_to_save = safe_gsheet_read(conn, URL_KITA, "Waktu Kerja", ttl=0)

            # FIX 5: exact match NIK sebelum simpan, cegah duplikat
            nik_clean = str(nik_karyawan).replace("'", "").replace(".", "").strip()
            duplikat = df_to_save[
                (df_to_save['NIK'].astype(str).str.replace("'", "").str.replace(".", "").str.strip() == nik_clean) &
                (df_to_save['Check-Out'].isna() | (df_to_save['Check-Out'].astype(str).str.strip() == ""))
            ]

            if not duplikat.empty:
                st.warning("⚠️ Anda sudah tercatat Check-In sebelumnya!")
                st.session_state.is_sudah_checkin = True
                st.session_state.checkin_sedang_proses = False
                if 'data_waktu_kerja' in st.session_state:
                    del st.session_state.data_waktu_kerja
                time.sleep(1)
                st.rerun()

            # Data check-in baru — kolom sesuai worksheet "Waktu Kerja"
            new_data = {
                "Tanggal":    waktu_skrg.strftime("%Y-%m-%d"),
                "Nama":       nama_karyawan,
                "NIK":        f"'{nik_karyawan}",
                "Check-In":   waktu_skrg.strftime("%H:%M:%S"),
                "Check-Out":  "",
                "Total_Jam":  0,
                "Aktivitas":  "Mulai Shift"
            }

            df_updated = pd.concat([df_to_save, pd.DataFrame([new_data])], ignore_index=True)

            with st.spinner("Menyimpan ke Google Sheets..."):
                berhasil = safe_gsheet_update(conn, URL_KITA, "Waktu Kerja", df_updated)

            if berhasil:
                # FIX 7: invalidate cache & session agar rerun langsung baca fresh
                read_waktu_kerja_sheet.clear()
                if 'data_waktu_kerja' in st.session_state:
                    del st.session_state.data_waktu_kerja

                st.session_state.is_sudah_checkin     = True
                st.session_state.status_kerja         = "IDLE"
                st.session_state.checkin_sedang_proses = False
                st.success("✅ Berhasil Check-In! Scanner Part siap digunakan.")
                time.sleep(1)
                st.rerun()

        except Exception as e:
            # FIX 2: tampilkan pesan error spesifik per kode error
            st.session_state.checkin_sedang_proses = False
            error_msg = str(e)
            if "429" in error_msg or "quota" in error_msg.lower() or "rate" in error_msg.lower():
                st.error("❌ Google Sheets API kelebihan beban (429). Tunggu 1-2 menit lalu coba lagi.")
                st.info("📋 Data BELUM tersimpan. Jangan tutup aplikasi.")
            elif "500" in error_msg or "503" in error_msg:
                st.error("❌ Server Google sedang bermasalah (500/503). Coba lagi dalam beberapa saat.")
                st.info("📋 Data BELUM tersimpan.")
            elif "403" in error_msg or "forbidden" in error_msg.lower():
                st.error("❌ Akses ditolak (403). Hubungi Admin untuk cek permission Google Sheets.")
            else:
                st.error(f"❌ Gagal Check-In: {error_msg}")
                st.info("📋 Catat waktu check-in manual dan lapor ke Admin.")

    st.divider()
    if st.button("⬅️ Kembali / Scan Ulang ID Operator", type="secondary", use_container_width=True):
        for key in ['nama_terpilih', 'nik_karyawan', 'is_sudah_checkin', 'data_waktu_kerja', 'checkin_sedang_proses']:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()


# ============================================================
# LAYAR 3 & 4: SUDAH CHECK-IN — AREA PRODUKSI
# ============================================================
else:
    st.success(f"👷 Operator: **{nama_karyawan}** | **{nik_karyawan}** | Sesi Aktif")

    status_kerja = st.session_state.get('status_kerja', 'IDLE')

    # ----------------------------------------------------------
    # STATUS: IDLE — scan kanban / input manual / check-out
    # ----------------------------------------------------------
    if status_kerja == "IDLE":
        st.write("<span style='font-size: 18px; font-weight: bold;'>📸 Opsi 1: Scan KANBAN untuk mulai proses</span>", unsafe_allow_html=True)
        barcode_part = qrcode_scanner(key='scanner_part_prod')
        if barcode_part:
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

            df_proses_cek = read_proses_sheet(URL_KITA)
            pekerjaan_menggantung = df_proses_cek[
                (df_proses_cek['Nama'] == nama_karyawan) &
                (df_proses_cek['Status'] == 'START')
            ]

            if not pekerjaan_menggantung.empty:
                part_no_aktif = pekerjaan_menggantung.iloc[0]['Part_No']
                st.error(f"❌ Tidak bisa Check-Out! Masih ada pekerjaan aktif: **{part_no_aktif}**. Selesaikan dulu.")
            else:
                st.success("✅ Semua pekerjaan sudah selesai.")
                if st.button("YA, SAYA YAKIN CHECK-OUT", type="primary", use_container_width=True):
                    with st.spinner("Memproses Check-Out..."):
                        try:
                            waktu_out = get_waktu_wib()
                            # Baca fresh saat checkout — ttl=0
                            df_waktu = safe_gsheet_read(conn, URL_KITA, "Waktu Kerja", ttl=0).copy()
                            checkin_row = get_last_active_row(df_waktu, nama_karyawan)

                            if checkin_row:
                                dt_in = get_checkin_datetime(checkin_row, waktu_out)
                                total_jam_shift = round((waktu_out - dt_in).total_seconds() / 3600, 2)

                                # FIX: mask pakai isna() | string kosong agar robust
                                mask_update = (
                                    (df_waktu['Nama'] == nama_karyawan) &
                                    (df_waktu['Check-Out'].isna() | (df_waktu['Check-Out'].astype(str).str.strip() == ""))
                                )
                                idx_pd = df_waktu[mask_update].index[-1]

                                # Nama kolom sesuai worksheet "Waktu Kerja"
                                df_waktu.at[idx_pd, 'Check-Out']  = waktu_out.strftime("%H:%M:%S")
                                df_waktu.at[idx_pd, 'Total_Jam']  = total_jam_shift
                                df_waktu.at[idx_pd, 'Aktivitas']  = "Shift Complete"

                                # FIX 3: pakai safe_gsheet_update — ada retry kalau 429
                                safe_gsheet_update(conn, URL_KITA, "Waktu Kerja", df_waktu)
                                read_waktu_kerja_sheet.clear()

                                st.session_state.is_sudah_checkin = False
                                st.session_state.nama_terpilih    = ""
                                st.session_state.nik_karyawan     = ""
                                st.session_state.status_kerja     = "IDLE"

                                st.success(f"✅ Check-Out Berhasil! Total jam kerja: {total_jam_shift} jam")
                                time.sleep(3)
                                st.rerun()
                            else:
                                st.error("❌ Data Check-In aktif tidak ditemukan!")

                        except Exception as e:
                            error_msg = str(e)
                            if "429" in error_msg or "quota" in error_msg.lower():
                                st.error("❌ API Quota habis saat Check-Out. Tunggu 1-2 menit lalu coba lagi.")
                            elif "500" in error_msg or "503" in error_msg:
                                st.error("❌ Server Google bermasalah. Coba lagi.")
                            else:
                                st.error(f"❌ Gagal Check-Out: {error_msg}")
                            st.info("📋 Data BELUM tersimpan. Jangan tutup aplikasi.")

            st.divider()
            if st.button("⬅️ Ganti Operator / Salah Scan Nama", use_container_width=True):
                for key in ['nama_terpilih', 'nik_karyawan', 'is_sudah_checkin',
                            'status_kerja', 'data_waktu_kerja', 'checkin_sedang_proses']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()

    # ----------------------------------------------------------
    # STATUS: SELECTING_PROCESS — pilih urutan proses & actual line
    # ----------------------------------------------------------
    elif status_kerja == "SELECTING_PROCESS":
        st.subheader("🔍 Pilih Urutan Proses")
        data_pilihan = st.session_state.get('available_processes', [])

        list_line_db  = main_df['LINE'].unique().tolist() if 'LINE' in main_df.columns else []
        add_options   = ["BM", "CM", "DM", "ERM", "NRM", "IRM", "KRM"]
        list_line     = list(dict.fromkeys(list_line_db + add_options))

        # Tambah opsi DPMR kalau belum ada
        if not any(p.get('URUTAN') == 'DPMR' for p in data_pilihan):
            sample = data_pilihan[0] if data_pilihan else {}
            dpmr_data = {
                'URUTAN':     'DPMR',
                'Part_Name':  sample.get('Part_Name', 'REPAIR'),
                'Part_No':    sample.get('Part_No', 'REPAIR'),
                'MODEL':      sample.get('MODEL', 'REPAIR'),
                'LINE':       sample.get('LINE', '-'),
                'SEC /PCS':   0
            }
            data_pilihan.append(dpmr_data)

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
    # STATUS: RUNNING — proses produksi berjalan
    # ----------------------------------------------------------
    elif status_kerja == "RUNNING":
        dp = st.session_state.get('current_part')
        if dp:
            waktu_sekarang = get_waktu_wib()
            durasi_live    = waktu_sekarang - st.session_state.waktu_start.replace(tzinfo=None)
            menit_live     = int(durasi_live.total_seconds() / 60)
            jam_live       = round(durasi_live.total_seconds() / 3600, 2)

            st.info(f"⚡ **Proses Berjalan:** {dp['part_name']} | {dp['part_no']}")
            st.write("Konfirmasi Mulai Kerja")

            # Tombol START — hanya muncul jika belum diklik
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
                        "Waktu_Selesai": "",
                        "ACT":           0,
                        "NG":            0,
                        "Status":        "START"
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

            # Metric cards
            col1, col2, col3, col4, col5 = st.columns(5, gap="small")
            col1.metric("Urutan",          dp['urutan_proses'])
            col2.metric("Target Sec/Pcs",  dp['sec_pcs'])
            col3.metric("Mulai",           st.session_state.waktu_start.strftime('%H:%M:%S'))
            col4.metric("Sudah Berjalan",  f"{menit_live % 1440} Menit", delta=f"{jam_live % 60} Jam")
            col5.metric("Actual Line",     dp.get('Actual_Line', ''))

            st.divider()

            # Input Abnormal
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
                k_sel    = c_kod.selectbox("Kode", options=list_kode, key=f"ab_kode_run_{st.session_state.ab_counter}")
                m_val    = c_men.number_input("Menit", min_value=0, step=1, key=f"ab_menit_run_{st.session_state.ab_counter}")
                kt_input = c_ket.text_input("Keterangan", placeholder="Contoh: Mesin Down", key=f"ab_ket_run_{st.session_state.ab_counter}")
                kt_val   = kt_input.upper()

                if st.button("🚀 Kirim Data Abnormal", use_container_width=True, key=f"btn_ab_submit_{st.session_state.ab_counter}"):
                    if not st.session_state.get('sudah_start_diklik'):
                        st.error("⚠️ Klik tombol START PROSES sebelum kirim data abnormal!")
                    elif k_sel and m_val > 0:
                        parts          = k_sel.split(" [")
                        kode_hanya     = parts[0]
                        uraian_abnormal = parts[1].replace("]", "") if len(parts) > 1 else ""

                        # Nama kolom sesuai worksheet "ABNORMAL"
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
            if barcode_data:
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
    # STATUS: FINISHING — input ACT, NG, istirahat, kirim SPH
    # ----------------------------------------------------------
    elif status_kerja == "FINISHING":
        dp = st.session_state.get('current_part')
        if dp:
            st.subheader(f"📝 Laporan Akhir: {dp['part_name']}")

            waktu_start = st.session_state.get('waktu_start', get_waktu_wib())
            waktu_end   = st.session_state.get('waktu_end',   get_waktu_wib())
            durasi      = waktu_end.replace(tzinfo=None) - waktu_start.replace(tzinfo=None)
            jam_total   = durasi.total_seconds() / 60
            jam_bersih  = jam_total % 1440

            c1, c2, c3, c4 = st.columns(4)
            act_raw = c1.text_input("Jumlah ACT", value="0")
            ng_raw  = c2.text_input("Jumlah NG",  value="0")
            try:
                act = int(act_raw)
                ng  = int(ng_raw)
            except ValueError:
                act = 0
                ng  = 0

            c3.metric("Durasi",      f"{round(jam_total, 2)} Menit", delta=f"{round(jam_total/60, 2)} Jam")
            c4.metric("Waktu Start", st.session_state.waktu_start.strftime("%H:%M:%S"))

            st.write("### ☕ Potongan Waktu Istirahat")
            DAFTAR_BREAK = {
                "Break 1 (10m)":      10,
                "Break 2 (10m)":      10,
                "Istirahat (40m)":    40,
                "Extra Break (15m)":  15,
                "2S (15m)":           15
            }
            pilihan_break  = st.multiselect("Pilih:", options=list(DAFTAR_BREAK.keys()))
            extra_custom   = st.number_input("Lainnya (Menit)", min_value=0, step=1, value=0)
            total_potongan = sum(DAFTAR_BREAK[item] for item in pilihan_break) + extra_custom
            durasi_bersih  = max(0, jam_bersih - total_potongan)
            st.info(f"⏱️ Durasi Bersih: {durasi_bersih:.1f} Menit")

            is_repair    = (dp.get('urutan_proses') == "DPMR")
            val_sec_pcs  = float(dp.get('sec_pcs', 0))
            standar_input = (val_sec_pcs * act) / 60 if (act > 0 and not is_repair) else 0
            persen_prod  = round((standar_input / durasi_bersih) * 100, 2) if (durasi_bersih > 0 and not is_repair) else 0.0

            if st.button("🚀 Kirim Data SPH", use_container_width=True):
                if act > 0:
                    # Nama kolom sesuai worksheet "Proses"
                    data_finish = {
                        "Part_No":          dp['part_no'],
                        "Waktu_Selesai":    waktu_end.strftime("%H:%M:%S"),
                        "ACT":              act,
                        "NG":               ng,
                        "%_Prod":           "N/A" if is_repair else f"{persen_prod:.2f}%",
                        "Total Istirahat":  total_potongan,
                        "Rasio_NG":         "N/A" if is_repair else (f"{(ng/act*100):.2f}%" if act > 0 else "0%"),
                        "Total_Jam":        round(durasi_bersih / 60, 2),
                        "Status":           "FINISH"
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
                    # FIX 8: tambah ab_counter ke keys_to_reset
                    keys_to_reset = [
                        'status_kerja', 'current_part', 'waktu_start', 'waktu_end',
                        'data_sph_terkirim', 'available_processes', 'sudah_start_diklik',
                        'barcode_input', 'is_submitting', 'proses_data', 'abnormal_data',
                        'ab_counter'
                    ]
                    for k in keys_to_reset:
                        if k in st.session_state:
                            del st.session_state[k]

                    st.session_state.status_kerja = "IDLE"
                    st.balloons()
                    st.success("✅ Laporan Proses selesai! Siap untuk scan part baru.")
                    time.sleep(2)
                    st.rerun()

    # ----------------------------------------------------------
    # Tombol Reset di bagian bawah — selalu tampil saat logged in
    # ----------------------------------------------------------
    if st.session_state.get('status_kerja') == "RUNNING":
        col_ref, col_res = st.columns(2)
        with col_ref:
            if st.button("🔄 Perbarui Waktu"):
                st.rerun()
        with col_res:
            if st.button("🚫 Reset Scanner", type="secondary"):
                keys_to_clean = ['status_kerja', 'current_part', 'waktu_start', 'waktu_end',
                                 'sudah_start_diklik', 'proses_data']
                for k in keys_to_clean:
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()
    else:
        if st.button("❌ Reset Scanner", type="secondary"):
            keys_to_clean = ['status_kerja', 'current_part', 'proses_data']
            for k in keys_to_clean:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()
