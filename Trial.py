import streamlit as st
import streamlit.components.v1 as components
from streamlit_qrcode_scanner import qrcode_scanner
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import pytz
from datetime import datetime, timedelta, timezone, date
import time

# SETUP THEME LANGSUNG DI KODE
st.set_page_config(page_title="Laporan Produksi Press PT. ISI", layout="wide")

# Injeksi JavaScript untuk mencegah refresh tak sengaja
components.html(
    """
    <script>
    window.parent.addEventListener('beforeunload', function (e) {
        // Pesan standar browser (beberapa browser modern mungkin tidak menampilkan teks kustom)
        var confirmationMessage = 'Data sedang diproses. Jika refresh, sesi scan akan hilang!';
        (e || window.event).returnValue = confirmationMessage;
        return confirmationMessage;
    });
    </script>
    """,
    height=0,
)

# Suntik CSS untuk warna
st.markdown("""
    <style>
    /* 1. Warna Background Utama */
    .stApp {
        background-color: #261ad6;
    }
    
    /* 2. Warna Sidebar */
    [data-testid="stSidebar"] {
        background-color: #ff0909;
    }

    /* 3. Warna Semua Teks */
    h1, h2, h3, p, span, label {
        color: #ffffff !important;
    }
    div.stButton > button {
        background-color: #00FF00 !important;
        color: black !important;
        border-radius: 10px;
    }
    div.stButton > button[kind="secondary"][key="btn_reset_biru"],
    div.stButton > button[key="btn_reset_biru"] {
        background: linear-gradient(45deg, #FF4444, #CC0000) !important;
        color: white !important;
        border: 2px solid #990000 !important;
        border-radius: 8px !important;
        font-weight: bold !important;
        transition: all 0.3s ease !important;
    }
    div.stButton > button[kind="secondary"][key="btn_reset_biru"]:hover,
    div.stButton > button[key="btn_reset_biru"]:hover {
        background: linear-gradient(45deg, #CC0000, #990000) !important;
        color: white !important;
        transform: scale(1.05) !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.3) !important;
    }
    div.stButton > button[kind="secondary"][key="btn_reset_biru"]:active,
    div.stButton > button[key="btn_reset_biru"]:active {
        background: #990000 !important;
        transform: scale(0.98) !important;
    }
    div.stButton > button p {
        color: #000000 !important;
        font-weight: bold !important;
    </style>
    """, unsafe_allow_html=True)

def get_waktu_wib():
    tz_jkt = pytz.timezone('Asia/Jakarta')
    return datetime.now(tz_jkt).replace(tzinfo=None)

def get_checkin_datetime(checkin_row, waktu_out):
    """
    Parse Check-In datetime handling cross-midnight shifts.
    If parsed dt_in > waktu_out, assume previous day.
    """
    tgl_in = checkin_row['Tanggal']
    jam_in = checkin_row['Check-In']
    
    try:
        dt_in = datetime.strptime(f"{tgl_in} {jam_in}", "%Y-%m-%d %H:%M:%S")
        
        # Cross-midnight check: if checkin appears "future", shift to prev day
        if dt_in > waktu_out:
            dt_in = dt_in - timedelta(days=1)
            st.info(f"🔄 Cross-midnight: Adjusted dt_in from {tgl_in} to previous day")
        
        return dt_in
    except Exception as e:
        st.error(f"Parse error: {e}. Using fallback.")
        return waktu_out - timedelta(hours=8)  # Assume 8h shift

# --- KONFIGURASI ---
st.set_page_config(page_title="Laporan Produksi Press PT ISI", layout="wide")
URL_KITA = "https://docs.google.com/spreadsheets/d/1uDmbbLhFsMdGSnozbRBMwEDPP2T20HqpEnJGYd2P390/edit"

if 'waktu_end' not in st.session_state:
    st.session_state.waktu_end = get_waktu_wib()
if 'waktu_start' not in st.session_state:
    st.session_state.waktu_start = get_waktu_wib()

# Inisialisasi Koneksi
conn = st.connection("gsheets", type=GSheetsConnection)

if 'list_nik_terdaftar' not in st.session_state:
    try:
        df_karyawan = conn.read(spreadsheet=URL_KITA, worksheet="Master_Karyawan", ttl=3600)
        st.session_state.list_nik_terdaftar = df_karyawan['NIK'].astype(str).str.strip().tolist()
    except:
        st.session_state.list_nik_terdaftar = []

nama_karyawan = st.session_state.get('nama_terpilih', None)
nik_karyawan = st.session_state.get('nik_karyawan', "")
if 'nama_terpilih' not in st.session_state:
    st.session_state.nama_terpilih = ""
if 'nik_karyawan' not in st.session_state:
    st.session_state.nik_karyawan = ""

# Fungsi Membaca MainData dengan Cache
@st.cache_data(ttl=3600)
def get_main_data(url):
    df = conn.read(spreadsheet=url, worksheet="MainData", ttl=3600)
    df.columns = df.columns.str.strip()
    return df

try:
    main_df = get_main_data(URL_KITA)
except Exception as e:
    st.error(f"Gagal memuat MainData: {e}")
    main_df = pd.DataFrame()

# --- FUNGSI KIRIM DATA ---
def simpan_ke_sheet(data_dict, tipe):
    try:
        df_proses = conn.read(spreadsheet=URL_KITA, worksheet="Proses", ttl=0)
        
        if tipe == "START":
            double_check = df_proses[(df_proses['Nama'] == data_dict['Nama']) & 
                                 (df_proses['Status'] == 'START')]
            
            if not double_check.empty:
                st.error("⚠️ Data START sudah ada di database atau sedang aktif.")
                st.error("⚠️ klik BATAL/Reset Scanner dan Scan barcode yang sesuai.")
                return False
            
            new_row = pd.DataFrame([data_dict])
            updated_df = pd.concat([df_proses, new_row], ignore_index=True)
            conn.update(spreadsheet=URL_KITA, worksheet="Proses", data=updated_df)
            return True
            
        elif tipe == "FINISH":
            df_proses.columns = df_proses.columns.str.strip()

            kolom_angka = ['Total_Jam', 'Rasio_NG', '%_Prod', 'ACT', 'NG']
            for col in kolom_angka:
                if col in df_proses.columns:
                    df_proses[col] = df_proses[col].astype(object)
            mask = (df_proses['Nama'].astype(str).str.strip() == str(nama_karyawan).strip()) & \
                   (df_proses['Part_No'].astype(str).str.replace(r'\.0$', '', regex=True) == str(data_dict['Part_No']).strip()) & \
                   (df_proses['Status'] == 'START')
            
            if mask.any():
                idx = df_proses[mask].index[-1]
                
                df_proses.at[idx, 'Waktu_Selesai'] = data_dict['Waktu_Selesai']
                df_proses.at[idx, 'ACT'] = data_dict['ACT']
                df_proses.at[idx, 'NG'] = data_dict['NG']
                df_proses.at[idx, '%_Prod'] = data_dict['%_Prod']
                df_proses.at[idx, 'Total Istirahat'] = data_dict['Total Istirahat']
                df_proses.at[idx, 'Rasio_NG'] = data_dict['Rasio_NG']
                df_proses.at[idx, 'Total_Jam'] = data_dict['Total_Jam']
                df_proses.at[idx, 'Status'] = 'FINISH'
                conn.update(spreadsheet=URL_KITA, worksheet="Proses", data=df_proses)
                return True
            else:
                st.error("❌ Tidak ditemukan data 'START' yang aktif untuk Part ini. Scan Start dulu!")
                return False
            
        elif tipe == "ABNORMAL":
            try:
                df_existing = conn.read(spreadsheet=URL_KITA, worksheet="ABNORMAL", ttl=0)
            
                new_row = pd.DataFrame([data_dict])
                updated_df = pd.concat([df_existing, new_row], ignore_index=True)
                conn.update(spreadsheet=URL_KITA, worksheet="ABNORMAL", data=updated_df)

                st.cache_data.clear()
                if 'abnormal_data' in st.session_state:
                    del st.session_state.abnormal_data
                return True
            except Exception as e:
                st.error(f"Gagal menyimpan data abnormal: {e}")
                return False

    except Exception as e:
        st.error(f"Gagal memproses data, Catat Laporan dan Lapor Admin: {e}")
        return False
    

# --- FUNGSI BANTU: CARI BARIS AKTIF TERAKHIR UNTUK CHECK-IN/CHECK-OUT ---
def get_last_active_row(df, nama):
    """
    Return FULL LAST ACTIVE ROW dict (not just index) for checkin data.
    """
    if 'Check-Out' not in df.columns or 'Nama' not in df.columns:
        return None
    
    nama_target = str(nama).strip()
    mask = (df['Nama'].astype(str).str.strip() == nama_target) & \
           (df['Check-Out'].isna() | (df['Check-Out'].astype(str).str.strip() == ""))

    active_rows = df[mask]
    
    if not active_rows.empty:
        return active_rows.iloc[-1].to_dict()
    return None

##--- FUNGSI BANTU: CEK PROSES AKTIF (START) UNTUK OPERATOR ---
def cek_proses_aktif(nik_karyawan):
    try:
        df = conn.read(spreadsheet=URL_KITA, worksheet="Proses", ttl=0)
        if df.empty:
            return None
        
        df['NIK'] = df['NIK'].astype(str).str.replace("'", "")
        nik_clean = str(nik_karyawan).replace("'", "")
        
        proses_ongoing = df[(df['NIK'] == nik_clean) & (df['Status'] == 'START')]
        
        if not proses_ongoing.empty:
            return proses_ongoing.iloc[-1].to_dict()
        return None
    except Exception as e:
        st.error(f"Error pengecekan data: {e}")
        return None

# --- LOGIKA PROSES SCAN ---
def handle_scan():
    raw_scan = st.session_state.barcode_input.strip()
    if not raw_scan:
        return

    part_no_scanned = raw_scan.split(';')[0].strip()

    main_df_string = main_df.copy()
    main_df_string['Part_No'] = main_df_string['Part_No'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    
    match = main_df_string[main_df_string['Part_No'] == part_no_scanned]

    status_sekarang = st.session_state.get('status_kerja', 'IDLE')

    if status_sekarang == "IDLE":
        if 'proses_data' not in st.session_state:
            st.session_state.proses_data = [conn.read(spreadsheet=URL_KITA, worksheet="Proses", ttl=0)]
        
        df_proses = st.session_state.proses_data[0]
        ongoing = df_proses[(df_proses['Nama'] == nama_karyawan) & (df_proses['Status'] == 'START')]

        if not ongoing.empty:
            row_terakhir = ongoing.iloc[-1]
            p_no = str(row_terakhir['Part_No']).replace('.0', '').strip() 
            
            match_main = main_df_string[main_df_string['Part_No'] == p_no]
            
            st.session_state.current_part = {
                'part_no': p_no,
                'part_name': row_terakhir['Part_Name'],
                'model': row_terakhir['Model'],
                'urutan_proses': row_terakhir['Urutan_Proses'],
                'Actual_Line': row_terakhir.get('Actual_Line', 'N/A'),
                'line': row_terakhir['Line'],
                'sec_pcs': match_main.iloc[0]['SEC /PCS'] if not match_main.empty else 0
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
            st.error(f"❌ Part No {part_no_scanned} tidak terdaftar di Main Data!")
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
            st.error(f"❌ Barcode ({part_no_scanned}) berbeda! Part aktif: {current_p_no}")
            st.session_state.barcode_input = ""

    st.session_state.barcode_input = ""

 #--- LOGIKA UTAMA ---            
nama_karyawan = st.session_state.get('nama_terpilih', "")
nik_karyawan = st.session_state.get('nik_karyawan', "")

if 'is_sudah_checkin' not in st.session_state:
    st.session_state.is_sudah_checkin = False

if nama_karyawan and not st.session_state.is_sudah_checkin:
    if 'data_waktu_kerja' not in st.session_state:
        try:
            st.session_state.data_waktu_kerja = conn.read(spreadsheet=URL_KITA, worksheet="Waktu Kerja", ttl=5)
        except Exception as e:
            st.session_state.data_waktu_kerja = pd.DataFrame()

    df_cek = st.session_state.data_waktu_kerja
    
    if not df_cek.empty:
        nik_clean = str(nik_karyawan).replace("'", "").replace(".", "").strip()
        
        checkin_found = df_cek[
            (df_cek['NIK'].astype(str).str.replace(".", "").str.contains(nik_clean)) & 
            (df_cek['Check-Out'].isna() | (df_cek['Check-Out'] == ""))
        ]
        
        if not checkin_found.empty:
            st.session_state.is_sudah_checkin = True
        else:
            st.session_state.is_sudah_checkin = False

is_sudah_checkin = st.session_state.is_sudah_checkin


# --- TAMPILAN UTAMA ---
st.title("📟 Laporan Produksi Department Press PT Indosafety Sentosa")

# LAYAR 1: BELUM SCAN NAMA
if not nama_karyawan:
    st.subheader("👋 Selamat Datang! Silakan Scan ID Operator")
    barcode_id = qrcode_scanner(key='scanner_id_operator')
    
    if barcode_id:
        if ";" in barcode_id:
            raw_nik = barcode_id.split(';')[0].strip()
            raw_nama = barcode_id.split(';')[1].strip()

            nik_scan_clean = raw_nik.replace(".", "")
            nik_master_clean = [str(n).replace(".", "").strip() for n in st.session_state.list_nik_terdaftar]
            
            if nik_scan_clean in nik_master_clean:
                st.session_state.nik_karyawan = raw_nik
                st.session_state.nama_terpilih = raw_nama
                st.session_state.is_sudah_checkin = False 
                
                if 'data_waktu_kerja' in st.session_state:
                    del st.session_state.data_waktu_kerja 

                with st.spinner("Mengecek status kerja terakhir..."):
                    data_aktif = cek_proses_aktif(raw_nik) 
                
                if data_aktif:
                    st.session_state.status_kerja = "RUNNING"
                    st.session_state.sudah_start_diklik = True
                    
                    st.session_state.current_part = {
                        'part_no': data_aktif.get('Part_No', ''),
                        'part_name': data_aktif.get('Part_Name', ''),
                        'model': data_aktif.get('Model', ''),
                        'line': data_aktif.get('Line', ''),
                        'urutan_proses': data_aktif.get('Urutan_Proses', ''),
                        'sec_pcs': float(data_aktif.get('Sec_Pcs', 0)),
                        'Actual_Line': data_aktif.get('Actual_Line', '')
                    }
                    
                    try:
                        waktu_str = data_aktif['Waktu_Mulai']
                        if " " in waktu_str:
                            waktu_str = waktu_str.split(" ")[1]
                        jam_obj = datetime.strptime(waktu_str, "%H:%M:%S").time()
                        st.session_state.waktu_start = datetime.combine(date.today(), jam_obj)
                    except Exception as e:
                        st.session_state.waktu_start = get_waktu_wib().replace(tzinfo=None)

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

# LAYAR 2: SUDAH SCAN NAMA TAPI BELUM CHECK-IN
elif not is_sudah_checkin:
    st.warning(f"⚠️ Halo **{nama_karyawan}**,{nik_karyawan} Anda belum Check-In.")
    if st.button("🟢 KLIK UNTUK CHECK-IN SEKARANG", use_container_width=True):
        waktu_skrg = get_waktu_wib()
        if 'df_waktu' not in st.session_state:
            st.session_state.df_waktu = conn.read(spreadsheet=URL_KITA, worksheet="Waktu Kerja", ttl=20)
            df_to_save = st.session_state.df_waktu
        new_data = {
            "Tanggal": waktu_skrg.strftime("%Y-%m-%d"),
            "Nama": nama_karyawan,
            "NIK": f"'{nik_karyawan}",
            "Check-In": waktu_skrg.strftime("%H:%M:%S"),
            "Check-Out": "",
            "Total_Jam": 0,
            "Aktivitas": "Mulai Shift"
        }
        new_row_df = pd.DataFrame([new_data])
        df_updated = pd.concat([df_to_save, new_row_df], ignore_index=True)
        conn.update(spreadsheet=URL_KITA, worksheet="Waktu Kerja", data=df_updated)
        st.session_state.is_sudah_checkin = True
        if 'df_waktu' in st.session_state:
            del st.session_state.df_waktu 
        st.session_state.df_waktu_cache = df_updated 
        st.session_state.status_kerja = "IDLE" 
        st.success("Berhasil Check-In! Scanner Part Aktif.")
        st.rerun()

    st.divider()
    if st.button("⬅️ Kembali / Scan Ulang ID Operator", type="secondary", use_container_width=True):
        st.session_state.nama_terpilih = ""
        st.session_state.nik_karyawan = ""
        st.session_state.is_sudah_checkin = False
        if 'data_waktu_kerja' in st.session_state:
            del st.session_state.data_waktu_kerja
        st.rerun()


# LAYAR 3 & 4: SUDAH CHECK-IN (AREA PRODUKSI)
else:
    st.success(f"👷 Operator: **{nama_karyawan}**|**{nik_karyawan}** | Sesi Aktif")

    status_kerja = st.session_state.get('status_kerja', 'IDLE')

    if status_kerja == "IDLE":
        st.write(" ### 📸 Opsi 1: Scan KANBAN untuk mulai proses")
        barcode_part = qrcode_scanner(key='scanner_part_prod')
        if barcode_part:
            st.session_state.barcode_input = barcode_part
            handle_scan()

        st.divider()

        st.write("### ⌨️ Opsi 2: Input  Part No. Manual")
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

            df_proses = conn.read(spreadsheet=URL_KITA, worksheet="Proses", ttl=0)
            pekerjaan_menggantung = df_proses[(df_proses['Nama'] == nama_karyawan) & (df_proses['Status'] == 'START')]

            if not pekerjaan_menggantung.empty:
                part_no_aktif = pekerjaan_menggantung.iloc[0]['Part_No']
                st.error(f"❌ Tidak bisa Check-Out! Anda masih memiliki pekerjaan aktif pada Part: **{part_no_aktif}**. Silakan Finish-kan dulu.")
            else:
                st.success("✅ Semua pekerjaan sudah selesai.")
                if st.button("YA, SAYA YAKIN CHECK-OUT", type="primary", use_container_width=True):
                    with st.spinner("Memproses Check-Out..."):
                        waktu_out = get_waktu_wib()
                        df_waktu = conn.read(spreadsheet=URL_KITA, worksheet="Waktu Kerja", ttl=0)
                        checkin_row = get_last_active_row(df_waktu, nama_karyawan)
                        
                        if checkin_row:
                            # FIXED: Use new date-aware parsing
                            dt_in = get_checkin_datetime(checkin_row, waktu_out)
                            total_jam_shift = round((waktu_out - dt_in).total_seconds() / 3600, 2)
                            
                            st.info(f"🔍 Check-Out calc: dt_in={dt_in.strftime('%Y-%m-%d %H:%M:%S')}, out={waktu_out.strftime('%Y-%m-%d %H:%M:%S')}, total={total_jam_shift}h")
                            
                            # Update sheet
                            mask_update = (df_waktu['Nama'] == nama_karyawan) & df_waktu['Check-Out'].isna()
                            idx_pd = df_waktu[mask_update].index[-1]
                            
                            df_waktu.at[idx_pd, 'Check-Out'] = waktu_out.strftime("%H:%M:%S")
                            df_waktu.at[idx_pd, 'Total_Jam'] = total_jam_shift
                            df_waktu.at[idx_pd, 'Aktivitas'] = "Shift Complete"
                            conn.update(spreadsheet=URL_KITA, worksheet="Waktu Kerja", data=df_waktu)
                            
                            # Reset
                            st.session_state.is_sudah_checkin = False
                            st.session_state.nama_terpilih = ""
                            st.session_state.nik_karyawan = ""
                            st.session_state.status_kerja = "IDLE"
                            
                            st.success(f"✅ Check-Out Berhasil! Total: {total_jam_shift} hours")
                            time.sleep(3)
                            st.rerun()
                        else:
                            st.error("❌ No open Check-In found!")
            st.divider()
            if st.button("⬅️ Ganti Operator / Salah Scan Nama", use_container_width=True):
                for key in ['nama_terpilih', 'nik_karyawan', 'is_sudah_checkin', 'status_kerja', 'data_waktu_kerja']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()


    elif status_kerja == "SELECTING_PROCESS":
        st.subheader("🔍 Pilih Urutan Proses")
        data_pilihan = st.session_state.get('available_processes', [])
        list_line = main_df['LINE'].unique().tolist() if 'LINE' in main_df.columns else []
        if not any(p.get('URUTAN') == 'DPMR' for p in data_pilihan):
            sample_part_name = data_pilihan[0].get('Part_Name') if data_pilihan else "REPAIR"
            sample_part_no = data_pilihan[0].get('Part_No') if data_pilihan else "REPAIR"
            sample_model = data_pilihan[0].get('MODEL') if data_pilihan else "REPAIR"
            sample_line = data_pilihan[0].get('LINE') if data_pilihan else "-"

            dpmr_data = {
            'URUTAN': 'DPMR',
            'Part_Name': sample_part_name,
            'Part_No': sample_part_no,
            'MODEL': sample_model,
            'LINE': sample_line,
            'SEC /PCS': 0
        }
            data_pilihan.append(dpmr_data)
        
        actual_line = st.selectbox("Pilih Line Produksi (Actual Line)", options=list_line)
        opsi_display = {f"{p['URUTAN']} | {p['Part_Name']}": p for p in data_pilihan}
        pilihan_user = st.selectbox("Pilih Urutan Proses Produksi", options=list(opsi_display.keys()))
        if st.button("Konfirmasi & Mulai Kerja"):
            detail = opsi_display[pilihan_user]
            st.session_state.current_part = {
                "part_no": detail.get('Part_No', 'N/A'),
                "part_name": detail.get('Part_Name', 'N/A'),
                "model": detail.get('MODEL', 'N/A'),
                "sec_pcs": detail.get('SEC /PCS', 0),
                "line": detail.get('LINE', 'N/A'),
                "Actual_Line": actual_line,
                "urutan_proses": detail.get('URUTAN', 'DPMR')
            }
            st.session_state.status_kerja = "RUNNING"
            st.session_state.waktu_start = get_waktu_wib()
            st.rerun()


    elif status_kerja == "RUNNING":
        dp = st.session_state.get('current_part')
        
        if dp:
            waktu_sekarang = get_waktu_wib()
            durasi_live = waktu_sekarang.replace(tzinfo=None) - st.session_state.waktu_start.replace(tzinfo=None)
            menit_live = int(durasi_live.total_seconds() / 60)
            jam_live = round(durasi_live.total_seconds() / 3600, 2)
            st.info(f"⚡ **Proses Berjalan:** {dp['part_name']} | {dp['part_no']}")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Urutan", dp['urutan_proses'])
            col2.metric("Target Sec/Pcs", dp['sec_pcs'])
            col3.metric("Mulai", st.session_state.waktu_start.strftime('%H:%M:%S'))
            col4.metric("Sudah Berjalan", f"{menit_live} Menit", delta=f"{jam_live} Jam")
            col5.metric("Actual Line", dp.get('Actual_Line', ''))

            st.divider()

            # --- BAGIAN BARU: INPUT ABNORMAL SAAT RUNNING ---
            with st.expander("⚠️ INPUT ABNORMAL", expanded=False):
                st.write("Input akan langsung tersimpan ke database. Jika DPMR tulis OK dan NG total di Keterangan.")
                list_kode = ["A [Ganti Proses]", "B [Ganti/Tambah Coil]", "C [Perikasa ATA]", "D [Trial]", "E [2S]", "F [Briefing Rutin]", "G1 [Material NG dan Tukar Proses]",
                            "G2 [Kualitas NG dan Tukar Proses]", "H [Tooling]", "I [Mesin Abnormal]", "K1 [Penaganan Kualitas NG]", "K2 [Penanganan dies NG]", "L [Kekurangan Material]",
                            "M [Lain-Lain]", "N [No KANBAN Plan]", "O [DPMR]"]
                
                if "ab_counter" not in st.session_state:
                    st.session_state.ab_counter = 0

                c_kod, c_men, c_ket = st.columns([1, 1, 2])
                k_sel = c_kod.selectbox("Kode", options=list_kode, key=f"ab_kode_run_{st.session_state.ab_counter}")
                m_val = c_men.number_input("Menit", min_value=0, step=1, key=f"ab_menit_run_{st.session_state.ab_counter}")
                kt_input = c_ket.text_input("Keterangan", placeholder="Contoh: Mesin Down", key=f"ab_ket_run_{st.session_state.ab_counter}")
                kt_val = kt_input.upper()

                if st.button("🚀 Kirim Data Abnormal", use_container_width=True, key=f"btn_ab_submit_{st.session_state.ab_counter}"):
                    if not st.session_state.get('sudah_start_diklik'):
                        st.error("⚠️ Klik tombol START PROSES sebelum kirim data abnormal!")
                    elif k_sel != "" and m_val > 0:
                        parts = k_sel.split(" [")
                        kode_hanya = parts[0]
                        uraian_abnormal = parts[1].replace("]", "") if len(parts) > 1 else ""
                        row_ab = {
                            "Tanggal": get_waktu_wib().strftime("%Y-%m-%d"),
                            "Mesin": dp.get('line', ''),
                            "Part_No": dp.get('part_no', ''),
                            "Model": dp.get('model', ''),
                            "Part_Name": dp.get('part_name', ''),
                            "Urutan_Proses": dp.get('urutan_proses', ''),
                            "Operator": nama_karyawan,
                            "Kode_Abnormal": kode_hanya,      
                            "Uraian_Abnormal": uraian_abnormal,
                            "Total_Waktu": m_val,
                            "Keterangan": kt_val
                        }
                        if simpan_ke_sheet(row_ab, "ABNORMAL"):
                            st.toast(f"✅ Kode {k_sel} tersimpan!")
                            st.session_state.ab_counter += 1
                            time.sleep(1)
                        else:
                            st.error("Pilih Kode & Isi Menit!")
                            st.info("JIKA DPMR MASUKAN JUMLAH PART OK DAN NG DI INPUT ABNORMAL!!!")

            st.divider()

            if not st.session_state.get('sudah_start_diklik'):
                st.write("Konfirmasi Mulai Kerja")
                if st.button("🚀 Konfirmasi Start Proses", use_container_width=True):
                    data_start = {
                        "Tanggal": get_waktu_wib().strftime("%Y-%m-%d"),
                        "Nama": nama_karyawan,
                        "NIK": f"'{st.session_state.get('nik_karyawan', '-')}",
                        "Part_No": dp['part_no'],
                        "Part_Name": dp['part_name'],
                        "Model": dp['model'],
                        "Line": dp['line'],
                        "Urutan_Proses": dp['urutan_proses'],
                        "Actual_Line": dp.get('Actual_Line', ""),
                        "Sec_Pcs": dp['sec_pcs'],
                        "Waktu_Mulai": st.session_state.waktu_start.strftime("%H:%M:%S"),
                        "Waktu_Selesai": "",
                        "ACT": 0, "NG": 0, "Status": "START"
                    }
                    if simpan_ke_sheet(data_start, "START"):
                        st.session_state.sudah_start_diklik = True
                        st.balloons()
                        st.success("✅ Produksi Dimulai!")
                        st.rerun()
            else:
                st.success("✅ Proses Sudah Dimulai")
                st.info("JIKA DPMR MASUKAN JUMLAH PART OK DAN NG DI INPUT ABNORMAL!!!")

            st.divider()

            st.subheader("SCAN KANBAN untuk FINISH")
            barcode_data = qrcode_scanner(key='scanner_finish_part')
            if barcode_data:
                st.session_state.barcode_input = barcode_data
                handle_scan()

            st.divider()
            st.write("### ⌨️ Input KANBAN Manual")
            manual_finish = st.text_input("Ketik Part No", key="manual_part_finish_input").strip().upper()
            if st.button("✅ Konfirmasi Input Manual Finish", use_container_width=True):
                if manual_finish:
                    st.session_state.barcode_input = manual_finish
                    handle_scan()

    elif status_kerja == "FINISHING":
        dp = st.session_state.get('current_part')
        if dp:
            st.subheader(f"📝 Laporan Akhir: {dp['part_name']}")
            
            waktu_start = st.session_state.get('waktu_start', get_waktu_wib())
            waktu_end = st.session_state.get('waktu_end', get_waktu_wib())
            durasi = waktu_end.replace(tzinfo=None) - waktu_start.replace(tzinfo=None)
            jam_total = durasi.total_seconds() / 60
            jam_bersih = jam_total % 1440

            c1, c2, c3, c4 = st.columns(4)
            act_raw = c1.text_input("Jumlah ACT", value="0")
            ng_raw = c2.text_input("Jumlah NG", value="0")
            try:
                act = int(act_raw)
                ng = int(ng_raw)
            except ValueError:
                act = 0
                ng = 0
            c3.metric("Durasi", f"{round(jam_total,2)} Menit", delta=f"{round(jam_total/60, 2)} Jam")
            c4.metric("Waktu Start", st.session_state.waktu_start.strftime("%H:%M:%S"))

            # Potongan Istirahat
            st.write("### ☕ Potongan Waktu Istirahat")
            DAFTAR_BREAK = {
                "Break 1 (10m)": 10,
                "Break 2 (10m)": 10,
                "Istirahat (40m)": 40,
                "Extra Break (15m)": 15,
                "2S (15m)": 15
            }
            pilihan_break = st.multiselect("Pilih:", options=list(DAFTAR_BREAK.keys()))
            extra_custom = st.number_input("Lainnya (Menit)", min_value=0, step=1, value=0)
            total_potongan = sum([DAFTAR_BREAK[item] for item in pilihan_break]) + extra_custom
            durasi_bersih = max(0, jam_bersih - total_potongan)
            st.info(f"⏱️ Durasi Bersih: {durasi_bersih:.1f} Menit")

            is_repair = (dp.get('urutan_proses') == "DPMR")
            val_sec_pcs = float(dp.get('sec_pcs', 0))
            standar_input = (val_sec_pcs * act) / 60 if (act > 0 and not is_repair) else 0
            persen_prod = round((standar_input / durasi_bersih) * 100, 2) if (durasi_bersih > 0 and not is_repair) else 0.0

            if st.button("🚀 Kirim Data SPH", use_container_width=True):
                if act > 0:
                    data_finish = {
                        "Part_No": dp['part_no'],
                        "Waktu_Selesai": waktu_end.strftime("%H:%M:%S"),
                        "ACT": act,
                        "NG": ng,
                        "%_Prod": "N/A" if is_repair else f"{persen_prod:.2f}%",
                        "Total Istirahat": total_potongan,
                        "Rasio_NG": "N/A" if is_repair else (f"{(ng/act*100):.2f}%" if act > 0 else "0%"),
                        "Total_Jam": round(durasi_bersih/60, 2),
                        "Status": "FINISH"
                    }
                    if simpan_ke_sheet(data_finish, "FINISH"):
                        st.session_state.data_sph_terkirim = True
                        st.success("✅ SPH Terkirim!")

                else:
                    st.error("⚠️ ACT harus diisi di halaman atas")

            if st.session_state.get('data_sph_terkirim'):
                st.divider()
                st.subheader("📊 Ringkasan Hasil Produksi")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Persentase Produksi", f"{persen_prod:.2f} %")
                c2.metric("Total Jam Kerja", f"{round(durasi_bersih/60, 2)} Jam")
                c3.metric("Rasio NG", f"{(ng/act * 100) if act > 0 else 0:.2f} %")

                st.info("DATA SPH sudah tercatat.")
                st.divider()
    
                if st.button("🏁 SELESAI & SCAN PART BARU", type="primary", use_container_width=True):
                    # RESET SEMUA SESSION STATE
                    keys_to_reset = [
                        'status_kerja', 'current_part', 'waktu_start', 'waktu_end', 
                        'data_sph_terkirim', 'available_processes', 'sudah_start_diklik',
                        'barcode_input', 'is_submitting', 'proses_data', 'abnormal_data'
                    ]
                    for k in keys_to_reset:
                        if k in st.session_state: 
                            del st.session_state[k]

                    # Set ulang status ke IDLE agar siap scan part baru
                    st.session_state.status_kerja = "IDLE"
                    st.balloons()
                    st.success("✅ Laporan Proses selesai! Siap untuk scan part baru.")
                    time.sleep(2)
                    st.rerun()

    if st.session_state.get('status_kerja') == "RUNNING":
        col_ref, col_res = st.columns(2)
        with col_ref:
            if st.button("🔄 Perbarui Waktu"):
                st.rerun()
        with col_res:
            if st.button("🚫 Reset Scanner", type="secondary"):
                keys_to_clean = ['status_kerja', 'current_part', 'waktu_start', 'waktu_end']
                for k in keys_to_clean:
                    if k in st.session_state: 
                        del st.session_state[k]
                st.rerun()
    else:
        if st.button(" ❌ Reset Scanner", type="secondary"):
            keys_to_clean = ['status_kerja', 'current_part']
            for k in keys_to_clean:
                if k in st.session_state: 
                    del st.session_state[k]
            st.rerun()
