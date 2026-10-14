"""
Laporan Produksi Dept. Press — PT Indosafety Sentosa
Versi Supabase (pengganti Google Sheets).

Alur layar:
  1. Scan ID Operator
  2. Check-In
  3. Area produksi: IDLE → SELECTING_PROCESS → RUNNING → FINISHING

Semua akses database ada di db.py.
"""
import time
import uuid
from datetime import timedelta

import streamlit as st
import streamlit.components.v1 as components
from streamlit_qrcode_scanner import qrcode_scanner

import db
from db import DBError, DuplicateError, combine_wib, normalize_nik, now_wib, parse_ts

# set_page_config WAJIB jadi perintah Streamlit pertama
st.set_page_config(page_title="Laporan Produksi Press PT. ISI", layout="wide")


# ============================================================
# KONSTANTA
# ============================================================
FALLBACK_KODE_ABNORMAL = [
    "A [Ganti Proses]", "B [Ganti/Tambah Coil]", "C [Periksa ATA]",
    "D [Trial]", "E [2S]", "F [Briefing Rutin]",
    "G1 [Material NG dan Tukar Proses]", "G2 [Kualitas NG dan Tukar Proses]",
    "H [Tooling]", "I [Mesin Abnormal]", "K1 [Penanganan Kualitas NG]",
    "K2 [Penanganan Dies NG]", "L [Kekurangan Material]",
    "M [Lain-Lain]", "N [No KANBAN Plan]", "O [DPMR]",
]
FALLBACK_LINE = ["BM", "CM", "DM", "ERM", "NRM", "IRM", "KRM"]

DAFTAR_BREAK = {
    "Break 1 (10m)":         10,
    "Break 2 (10m)":         10,
    "Istirahat (40m)":       40,
    "Extra Break (15m)":     15,
    "2S (15m)":              15,
    "Istirahat Jumat (70m)": 70,
}

KEYS_PROSES = [
    "status_kerja", "current_part", "waktu_start", "waktu_end",
    "data_sph_terkirim", "available_processes", "sudah_start_diklik",
    "actual_summary_data", "ab_counter",
    "default_jam_start", "input_actual_time_start", "input_actual_time_finish",
]
KEYS_OPERATOR = ["nama_terpilih", "nik_karyawan", "shift"] + KEYS_PROSES


# ============================================================
# JAVASCRIPT — cegah refresh tidak sengaja
# ============================================================
components.html(
    """
    <script>
    window.parent.addEventListener('beforeunload', function (e) {
        var msg = 'Data sedang diproses. Jika refresh, sesi scan akan hilang!';
        (e || window.event).returnValue = msg;
        return msg;
    });
    </script>
    """,
    height=0,
)

# ============================================================
# CSS STYLING (sama dengan versi Google Sheets)
# ============================================================
st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem !important; }
    header { visibility: hidden; }
    h1 { margin-top: -10px !important; padding-top: 0px !important;
         margin-bottom: 5px !important; line-height: 1.1 !important; }
    .stApp { background-color: #261ad6; }
    [data-testid="stSidebar"] { background-color: #b30000; }
    h1, h2, h3, p, span, label, .stMarkdown { color: #ffffff !important; }
    div.stButton > button {
        background-color: #00FF00 !important; color: black !important;
        border-radius: 10px; font-weight: bold !important;
    }
    div.stButton > button p { font-size: 18px !important; font-weight: bold !important; color: black !important; }
    div.stMarkdown p { font-size: 16px !important; font-weight: normal !important;
                       line-height: 1.5 !important; font-family: sans-serif !important; }
    hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important;
         border-bottom: 1px solid rgba(255, 255, 255, 0.3) !important; }
    div[data-testid="stTextInput"] input { background-color: #000000 !important; color: #ffffff !important;
                                           -webkit-text-fill-color: #ffffff !important; }
    div[data-testid="stNumberInput"] input { background-color: #000000 !important; color: #ffffff !important; }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] { background-color: #000000 !important; color: #ffffff !important; }
    div[data-testid="stTextInput"] input:focus { border-color: #ffffff !important; box-shadow: none !important; }
    </style>
    """, unsafe_allow_html=True)

st.markdown(
    """
    <h1 style='text-align: center; font-size: 28px; margin-top: -20px; margin-bottom: 0px; line-height: 1.2;'>
        📟 Laporan Produksi Dept. Press <br> PT Indosafety Sentosa
    </h1>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# SIDEBAR
# ============================================================
if st.sidebar.button("🔄 Update Data Master"):
    st.cache_data.clear()          # hanya master data yang di-cache
    st.sidebar.success("Data master diperbarui!")


# ============================================================
# HELPER UI
# ============================================================
def flash(msg: str, icon: str = "✅") -> None:
    """Simpan pesan untuk ditampilkan setelah st.rerun()."""
    st.session_state["_flash"] = (msg, icon)


def tampilkan_flash() -> None:
    if "_flash" in st.session_state:
        msg, icon = st.session_state.pop("_flash")
        st.toast(msg, icon=icon)


def tampilkan_error(e: Exception, konteks: str) -> None:
    if isinstance(e, DBError):
        st.error(f"❌ {konteks}: {e}")
    else:
        st.error(f"❌ {konteks}. Catat laporan manual & lapor Admin. Detail: {e}")
    st.info("📋 Data BELUM tersimpan. Jangan tutup aplikasi, silakan coba lagi.")


def reset_keys(keys: list[str]) -> None:
    for k in keys:
        st.session_state.pop(k, None)


def decode_scan(value) -> str:
    """Hasil qrcode_scanner bisa berupa str / bytes / file-like."""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="ignore").strip()
    if hasattr(value, "read"):
        try:
            data = value.read()
            return (data.decode("utf-8", errors="ignore") if isinstance(data, (bytes, bytearray)) else str(data)).strip()
        except Exception:
            pass
    return str(value).strip()


def part_dari_proses(row: dict) -> dict:
    """Bentuk dict current_part dari 1 baris tabel proses."""
    return {
        "proses_id":     row["id"],
        "part_no":       row["part_no"],
        "part_name":     row.get("part_name") or "",
        "model":         row.get("model") or "",
        "line":          row.get("line") or "",
        "urutan_proses": row["urutan_proses"],
        "Actual_Line":   row.get("actual_line") or "",
        "sec_pcs":       float(row.get("sec_pcs") or 0),
        "condition":     row.get("condition") or "Normal",
    }


def pulihkan_proses(row: dict) -> None:
    """Lanjutkan proses START yang belum selesai (mis. HP mati / browser tertutup)."""
    st.session_state.current_part = part_dari_proses(row)
    st.session_state.waktu_start = parse_ts(row["actual_time_start"])
    st.session_state.status_kerja = "RUNNING"
    st.session_state.sudah_start_diklik = True


# ============================================================
# LOGIKA SCAN KANBAN
# ============================================================
def handle_scan(raw) -> None:
    part_no = db.normalize_part_no(decode_scan(raw).split(";")[0])
    if not part_no:
        return

    status = st.session_state.get("status_kerja", "IDLE")
    nik = st.session_state.nik_karyawan

    try:
        if status == "IDLE":
            aktif = db.get_active_proses(nik)
            if aktif:
                pulihkan_proses(aktif)
                flash(f"🔄 Sesi {aktif['part_no']} dipulihkan!")
                st.rerun()

            proses_list = db.get_part_processes(part_no)
            if not proses_list:
                st.error(f"❌ Part No '{part_no}' tidak terdaftar di Main Data!")
                return
            st.session_state.available_processes = proses_list
            st.session_state.status_kerja = "SELECTING_PROCESS"
            st.rerun()

        elif status == "RUNNING":
            dp = st.session_state.current_part
            if not st.session_state.get("sudah_start_diklik"):
                st.error("⚠️ Klik '🚀 Konfirmasi Start Proses' dulu sebelum scan FINISH.")
                return
            if part_no == str(dp["part_no"]).strip():
                st.session_state.status_kerja = "FINISHING"
                st.session_state.waktu_end = now_wib()
                flash("🏁 Scan Finish Berhasil!")
                st.rerun()
            else:
                st.error(f"❌ Barcode ({part_no}) berbeda dengan Part aktif: {dp['part_no']}")
    except DBError as e:
        tampilkan_error(e, "Gagal membaca data")


tampilkan_flash()

nama_karyawan = st.session_state.get("nama_terpilih", "")
nik_karyawan = st.session_state.get("nik_karyawan", "")


# ============================================================
# LAYAR 1: BELUM SCAN ID OPERATOR
# ============================================================
if not nik_karyawan:
    st.subheader("👋 Selamat Datang! Silakan Scan ID Operator")
    barcode_id = qrcode_scanner(key="scanner_id_operator")

    if barcode_id:
        teks = decode_scan(barcode_id)
        if ";" not in teks:
            st.error("🚫 Format QR ID tidak valid. Harus berformat NIK;NAMA.")
        else:
            raw_nik, raw_nama = [x.strip() for x in teks.split(";")[:2]]
            nik = normalize_nik(raw_nik)
            try:
                kary = db.get_karyawan(nik)
                if not kary or not kary.get("aktif", True):
                    st.error(f"🚫 Akses Ditolak! NIK {raw_nik} tidak terdaftar.")
                else:
                    reset_keys(KEYS_OPERATOR)
                    st.session_state.nik_karyawan = nik
                    st.session_state.nama_terpilih = kary.get("nama") or raw_nama

                    with st.spinner("Mengecek status kerja terakhir..."):
                        st.session_state.shift = db.get_active_shift(nik)
                        aktif = db.get_active_proses(nik)

                    if aktif:
                        pulihkan_proses(aktif)
                        flash(f"🔄 Melanjutkan proses: {aktif.get('part_name')}")
                    else:
                        st.session_state.status_kerja = "IDLE"
                        flash(f"Terverifikasi: {st.session_state.nama_terpilih}")
                    st.rerun()
            except DBError as e:
                tampilkan_error(e, "Gagal verifikasi ID")


# ============================================================
# LAYAR 2: SUDAH SCAN ID TAPI BELUM CHECK-IN
# ============================================================
elif not st.session_state.get("shift"):
    st.warning(f"⚠️ Halo **{nama_karyawan}** | {nik_karyawan} — Anda belum Check-In.")

    if st.button("🟢 KLIK UNTUK CHECK-IN SEKARANG", width="stretch"):
        try:
            with st.spinner("Menyimpan Check-In..."):
                st.session_state.shift = db.check_in(nik_karyawan, nama_karyawan)
            st.session_state.status_kerja = "IDLE"
            jam = parse_ts(st.session_state.shift["check_in"]).strftime("%H:%M:%S")
            flash(f"Berhasil Check-In pukul {jam}! Scanner Part siap digunakan.")
            st.rerun()
        except DBError as e:
            tampilkan_error(e, "Gagal Check-In")

    st.divider()
    if st.button("⬅️ Kembali / Scan Ulang ID Operator", type="secondary", width="stretch"):
        reset_keys(KEYS_OPERATOR)
        st.rerun()


# ============================================================
# LAYAR 3 & 4: SUDAH CHECK-IN — AREA PRODUKSI
# ============================================================
else:
    st.success(f"👷 Operator: **{nama_karyawan}** | **{nik_karyawan}** | Sesi Aktif")
    status_kerja = st.session_state.get("status_kerja", "IDLE")

    # ----------------------------------------------------------
    # IDLE — scan kanban / input manual / check-out
    # ----------------------------------------------------------
    if status_kerja == "IDLE":
        st.write("<span style='font-size: 18px; font-weight: bold;'>📸 Opsi 1: Scan KANBAN untuk mulai proses</span>",
                 unsafe_allow_html=True)
        barcode_part = qrcode_scanner(key="scanner_part_prod")
        if barcode_part:
            handle_scan(barcode_part)

        st.divider()
        st.write("<span style='font-size: 18px; font-weight: bold;'>⌨️ Opsi 2: Input Part No. Manual</span>",
                 unsafe_allow_html=True)
        manual_input = st.text_input("Ketik Part No.", key="manual_part_input").strip().upper()
        if st.button("✅ Konfirmasi Input Manual", width="stretch") and manual_input:
            handle_scan(manual_input)

        st.divider()
        st.write("Jika sudah selesai semua pekerjaan shift ini:")

        with st.popover("🔴 SELESAI SHIFT (CHECK-OUT)", width="stretch"):
            st.write("### Konfirmasi Check-Out")
            st.warning("Apakah Anda yakin ingin mengakhiri shift sekarang?")

            if st.button("YA, SAYA YAKIN CHECK-OUT", type="primary", width="stretch"):
                try:
                    with st.spinner("Memproses Check-Out..."):
                        aktif = db.get_active_proses(nik_karyawan)
                        if aktif:
                            st.error(f"❌ Tidak bisa Check-Out! Masih ada pekerjaan aktif: "
                                     f"**{aktif['part_no']}**. Selesaikan dulu.")
                        else:
                            total_jam = db.check_out(st.session_state.shift)
                            reset_keys(KEYS_OPERATOR)
                            flash(f"Check-Out Berhasil! Total jam kerja: {total_jam} jam")
                            st.rerun()
                except DBError as e:
                    tampilkan_error(e, "Gagal Check-Out")

            st.divider()
            if st.button("⬅️ Ganti Operator / Salah Scan Nama", width="stretch"):
                reset_keys(KEYS_OPERATOR)
                st.rerun()

    # ----------------------------------------------------------
    # SELECTING_PROCESS — pilih urutan proses, line & condition
    # ----------------------------------------------------------
    elif status_kerja == "SELECTING_PROCESS":
        st.subheader("🔍 Pilih Detail Produksi")
        data_pilihan = list(st.session_state.get("available_processes", []))

        if not any(p.get("urutan") == "DPMR" for p in data_pilihan):
            sample = data_pilihan[0] if data_pilihan else {}
            data_pilihan.append({
                "urutan":    "DPMR",
                "part_name": sample.get("part_name", "REPAIR"),
                "part_no":   sample.get("part_no", "REPAIR"),
                "model":     sample.get("model", "REPAIR"),
                "line":      sample.get("line", "-"),
                "sec_pcs":   0,
            })

        try:
            list_line = db.get_lines() or FALLBACK_LINE
        except DBError:
            list_line = FALLBACK_LINE

        selected_condition = st.radio(
            "📌 Pilih Kondisi Kerja (Condition):",
            options=["Normal", "Overtime"],
            horizontal=True,
            key="radio_condition",
        )
        actual_line = st.selectbox("Pilih Line Produksi (Actual Line)", options=list_line)
        opsi_display = {f"{p['urutan']} | {p['part_name']}": p for p in data_pilihan}
        pilihan_user = st.selectbox("Pilih Urutan Proses Produksi", options=list(opsi_display.keys()))

        if st.button("Konfirmasi & Mulai Kerja", width="stretch"):
            d = opsi_display[pilihan_user]
            st.session_state.current_part = {
                "proses_id":     None,                 # diisi setelah START tersimpan
                "part_no":       d.get("part_no", "N/A"),
                "part_name":     d.get("part_name", "N/A"),
                "model":         d.get("model") or "",
                "sec_pcs":       float(d.get("sec_pcs") or 0),
                "line":          d.get("line") or "",
                "Actual_Line":   actual_line,
                "urutan_proses": d.get("urutan", "DPMR"),
                "condition":     selected_condition,
            }
            st.session_state.status_kerja = "RUNNING"
            st.session_state.sudah_start_diklik = False
            st.session_state.waktu_start = now_wib()
            st.rerun()

    # ----------------------------------------------------------
    # RUNNING — proses produksi berjalan
    # ----------------------------------------------------------
    elif status_kerja == "RUNNING":
        dp = st.session_state.get("current_part")
        if not dp:
            st.session_state.status_kerja = "IDLE"
            st.rerun()

        st.info(f"⚡ **Proses Berjalan:** {dp['part_name']} | {dp['part_no']} ({dp['condition']})")
        st.write("### Konfirmasi Mulai Kerja")

        if not st.session_state.get("sudah_start_diklik"):
            st.warning("⚠️ Tentukan Waktu Start Manual lalu klik tombol di bawah untuk mulai menghitung produksi.")
            jam_manual = st.time_input(
                "🕒 Pilih Waktu Start Produksi (Manual):",
                # default dikunci sekali agar input operator tidak ter-reset saat menit berganti
                value=st.session_state.setdefault(
                    "default_jam_start", now_wib().time().replace(second=0, microsecond=0)),
                step=60,
                key="input_actual_time_start",
            )

            if st.button("🚀 Konfirmasi Start Proses", width="stretch"):
                now = now_wib()
                start_dt = combine_wib(now.date(), jam_manual)
                # Shift malam: jam start 23:50 diinput pukul 00:10 → milik kemarin
                if start_dt > now + timedelta(minutes=5):
                    start_dt -= timedelta(days=1)

                data_start = {
                    "tanggal":           start_dt.date(),
                    "waktu_kerja_id":    st.session_state.shift["id"],
                    "nik":               nik_karyawan,
                    "nama":              nama_karyawan,
                    "part_no":           dp["part_no"],
                    "part_name":         dp["part_name"],
                    "model":             dp["model"],
                    "line":              dp["line"],
                    "urutan_proses":     dp["urutan_proses"],
                    "actual_line":       dp["Actual_Line"] or None,
                    "condition":         dp["condition"],
                    "sec_pcs":           dp["sec_pcs"],
                    "actual_time_start": start_dt,
                    "status":            "START",
                }
                try:
                    row = db.start_proses(data_start)
                    dp["proses_id"] = row["id"]
                    st.session_state.waktu_start = start_dt
                    st.session_state.sudah_start_diklik = True
                    flash(f"Produksi dimulai pukul {start_dt:%H:%M:%S} ({dp['condition']})!", "🚀")
                    st.rerun()
                except DuplicateError:
                    st.error("⚠️ Masih ada proses START aktif di database. "
                             "Klik Reset Scanner lalu scan KANBAN lagi — sesi lama akan dipulihkan.")
                except DBError as e:
                    tampilkan_error(e, "Gagal menyimpan START")
        else:
            st.success(f"✅ Proses Sudah Dimulai — Kondisi: **{dp['condition']}**")
            st.info("⚠️ Input ABNORMAL di bawah dan scan KANBAN FINISH untuk akhiri proses.")
            st.info("DATA START ANDA SUDAH TERSIMPAN DI DATABASE. SELAMAT BEKERJA! 🙌")

        durasi = now_wib() - st.session_state.waktu_start
        total_menit = max(0, int(durasi.total_seconds() // 60))

        col1, col2, col3, col4, col5, col6 = st.columns(6, gap="small")
        col1.metric("Urutan",         dp["urutan_proses"])
        col2.metric("Target Sec/Pcs", dp["sec_pcs"])
        col3.metric("Mulai (Start)",  st.session_state.waktu_start.strftime("%H:%M:%S"))
        col4.metric("Sudah Berjalan", f"{total_menit} Menit", delta=f"{total_menit / 60:.2f} Jam", delta_color="off")
        col5.metric("Actual Line",    dp["Actual_Line"])
        col6.metric("Kondisi",        dp["condition"])

        st.divider()

        # ---------------- Input Abnormal ----------------
        with st.expander("⚠️ INPUT ABNORMAL", expanded=False):
            st.write("Input langsung tersimpan ke database. Jika DPMR, tulis OK dan NG total di Keterangan.")
            try:
                list_kode = [f"{r['kode']} [{r['uraian']}]" for r in db.get_kode_abnormal()] or FALLBACK_KODE_ABNORMAL
            except DBError:
                list_kode = FALLBACK_KODE_ABNORMAL

            counter = st.session_state.setdefault("ab_counter", 0)
            c_kod, c_men, c_ket = st.columns([1, 1, 2])
            k_sel    = c_kod.selectbox("Kode", options=list_kode, key=f"ab_kode_run_{counter}")
            m_val    = c_men.number_input("Menit", min_value=0, step=1, key=f"ab_menit_run_{counter}")
            kt_val   = c_ket.text_input("Keterangan", placeholder="Contoh: Mesin Down", key=f"ab_ket_run_{counter}").upper()

            if st.button("🚀 Kirim Data Abnormal", width="stretch", key=f"btn_ab_submit_{counter}"):
                if not st.session_state.get("sudah_start_diklik"):
                    st.error("⚠️ Klik tombol START PROSES sebelum kirim data abnormal!")
                elif k_sel and m_val > 0:
                    kode, _, uraian = k_sel.partition(" [")
                    now = now_wib()
                    row_ab = {
                        # UUID tetap selama form ini belum terkirim → klik dobel tidak dobel data
                        "client_ref":      st.session_state.setdefault(f"ab_ref_{counter}", str(uuid.uuid4())),
                        "proses_id":       dp.get("proses_id"),
                        "tanggal":         now.date(),
                        "jam_input":       now.time().replace(microsecond=0),
                        "mesin":           dp["Actual_Line"] or None,
                        "part_no":         dp["part_no"],
                        "model":           dp["model"],
                        "part_name":       dp["part_name"],
                        "urutan_proses":   dp["urutan_proses"],
                        "operator":        nama_karyawan,
                        "nik":             nik_karyawan,
                        "kode_abnormal":   kode.strip(),
                        "uraian_abnormal": uraian.rstrip("]"),
                        "total_waktu":     int(m_val),
                        "keterangan":      kt_val or None,
                    }
                    try:
                        db.insert_abnormal(row_ab)
                        st.session_state.pop(f"ab_ref_{counter}", None)
                        st.session_state.ab_counter = counter + 1     # kosongkan form
                        flash(f"Kode {k_sel} tersimpan!")
                        st.rerun()
                    except DBError as e:
                        tampilkan_error(e, "Gagal menyimpan ABNORMAL")
                else:
                    st.error("Pilih Kode & isi Menit terlebih dahulu!")

        st.divider()
        st.write("<span style='font-size: 18px; font-weight: bold;'>📸 SCAN KANBAN untuk FINISH</span>",
                 unsafe_allow_html=True)
        barcode_data = qrcode_scanner(key="scanner_finish_part")
        if barcode_data:
            handle_scan(barcode_data)

        st.divider()
        st.write("<span style='font-size: 18px; font-weight: bold;'>⌨️ Input KANBAN Manual</span>",
                 unsafe_allow_html=True)
        manual_finish = st.text_input("Ketik Part No", key="manual_part_finish_input").strip().upper()
        if st.button("✅ Konfirmasi Input Manual Finish", width="stretch") and manual_finish:
            handle_scan(manual_finish)

    # ----------------------------------------------------------
    # FINISHING — ACT, NG, waktu finish manual, istirahat, kirim SPH
    # ----------------------------------------------------------
    elif status_kerja == "FINISHING":
        dp = st.session_state.get("current_part")
        if not dp:
            st.session_state.status_kerja = "IDLE"
            st.rerun()

        st.subheader(f"📝 Laporan Akhir: {dp['part_name']} ({dp['condition']})")
        sudah_terkirim = st.session_state.get("data_sph_terkirim", False)

        # 1. ACT & NG
        c1, c2 = st.columns(2)
        act_raw = c1.text_input("Jumlah ACT", value="0", disabled=sudah_terkirim)
        ng_raw  = c2.text_input("Jumlah NG",  value="0", disabled=sudah_terkirim)
        try:
            act, ng = int(act_raw), int(ng_raw)
            input_valid = act >= 0 and ng >= 0
        except ValueError:
            act, ng, input_valid = 0, 0, False
        if not input_valid:
            st.error("⚠️ ACT dan NG harus angka bulat ≥ 0.")

        # 2. Waktu finish manual
        st.write("### 🕒 Input Waktu Selesai Produksi (Manual)")
        default_finish = st.session_state.get("waktu_end") or now_wib()
        waktu_finish_manual = st.time_input(
            "Pilih Waktu Finish Produksi:",
            value=default_finish.time().replace(second=0, microsecond=0),
            step=60,
            key="input_actual_time_finish",
            disabled=sudah_terkirim,
        )

        dt_start = st.session_state.waktu_start
        dt_finish = combine_wib(dt_start.date(), waktu_finish_manual)
        if dt_finish < dt_start:             # lewat tengah malam
            dt_finish += timedelta(days=1)
        durasi_kotor_menit = (dt_finish - dt_start).total_seconds() / 60

        # 3. Potongan istirahat
        st.write("### ☕ Potongan Waktu Istirahat")
        pilihan_break = st.multiselect("Pilih Break:", options=list(DAFTAR_BREAK.keys()), disabled=sudah_terkirim)
        extra_custom  = st.number_input("Lainnya (Menit)", min_value=0, step=1, value=0, disabled=sudah_terkirim)
        total_potongan = sum(DAFTAR_BREAK[b] for b in pilihan_break) + int(extra_custom)

        # 4. Perhitungan (rumus sama dengan versi lama)
        durasi_bersih_menit = max(0.0, durasi_kotor_menit - total_potongan)
        total_jam_actual = durasi_bersih_menit / 60
        total_waktu_actual_str = f"{int(durasi_bersih_menit // 60)} Jam {int(durasi_bersih_menit % 60)} Menit"

        is_repair     = dp["urutan_proses"] == "DPMR"
        val_sec_pcs   = float(dp.get("sec_pcs") or 0)
        standar_input = (val_sec_pcs * act) / 60 if (act > 0 and not is_repair) else 0
        persen_prod   = round((standar_input / durasi_bersih_menit) * 100, 2) if (durasi_bersih_menit > 0 and not is_repair) else 0.0
        rasio_ng      = round(ng / act * 100, 2) if (act > 0 and not is_repair) else 0.0

        st.info(f"⏱️ **Waktu Start:** {dt_start:%Y-%m-%d %H:%M:%S}  →  **Finish:** {dt_finish:%Y-%m-%d %H:%M:%S}  "
                f"|  Durasi bersih: {total_waktu_actual_str}")
        st.divider()

        # 5. Kirim SPH
        if not sudah_terkirim and st.button("🚀 Kirim Data SPH", width="stretch"):
            if not input_valid or act <= 0:
                st.error("⚠️ Jumlah ACT harus diisi dan lebih dari 0!")
            else:
                data_finish = {
                    "actual_time_finish": dt_finish,
                    "act":                act,
                    "ng":                 ng,
                    "persen_prod":        None if is_repair else persen_prod,   # NULL = N/A
                    "total_istirahat":    total_potongan,
                    "rasio_ng":           None if is_repair else rasio_ng,
                    "total_jam":          round(total_jam_actual, 2),
                }
                try:
                    proses_id = dp.get("proses_id")
                    if not proses_id:                       # jaga-jaga sesi lama
                        aktif = db.get_active_proses(nik_karyawan)
                        proses_id = aktif["id"] if aktif and aktif["part_no"] == dp["part_no"] else None
                    if not proses_id:
                        st.error("❌ Tidak ditemukan data START aktif untuk Part ini. Lakukan Scan Start dulu!")
                    else:
                        with st.spinner("Menyimpan SPH..."):
                            db.finish_proses(proses_id, data_finish)
                        st.session_state.data_sph_terkirim = True
                        st.session_state.actual_summary_data = {
                            "total_waktu_actual": total_waktu_actual_str,
                            "persen_prod":        persen_prod,
                            "total_jam":          round(total_jam_actual, 2),
                            "rasio_ng":           rasio_ng,
                            "is_repair":          is_repair,
                        }
                        flash("SPH Terkirim!")
                        st.rerun()
                except DBError as e:
                    tampilkan_error(e, "Gagal menyimpan SPH")

        # 6. Ringkasan
        if sudah_terkirim:
            st.subheader("📊 Ringkasan Hasil Produksi")
            s = st.session_state.get("actual_summary_data", {})
            r1, r2, r3, r4 = st.columns(4, gap="medium")
            r1.metric("Total Waktu Actual", s.get("total_waktu_actual", "-"))
            r2.metric("Persentase Produksi", "N/A" if s.get("is_repair") else f"{s.get('persen_prod', 0):.2f} %")
            r3.metric("Total Jam Kerja", f"{s.get('total_jam', 0)} Jam")
            r4.metric("Rasio NG", "N/A" if s.get("is_repair") else f"{s.get('rasio_ng', 0):.2f} %")

            st.info("✅ Data SPH sudah tercatat di database.")
            st.divider()

            if st.button("🏁 SELESAI & SCAN PART BARU", type="primary", width="stretch"):
                reset_keys(KEYS_PROSES)
                st.session_state.status_kerja = "IDLE"
                flash("Laporan Proses selesai! Siap untuk scan part baru.", "🎉")
                st.rerun()

    # ----------------------------------------------------------
    # Tombol bawah
    # ----------------------------------------------------------
    st.divider()
    if st.session_state.get("status_kerja") == "RUNNING":
        col_ref, col_res = st.columns(2)
        with col_ref:
            if st.button("🔄 Perbarui Waktu"):
                st.rerun()
        with col_res:
            if st.button("🚫 Reset Scanner", type="secondary"):
                # Data START di database TIDAK dihapus; scan KANBAN berikutnya akan memulihkannya.
                reset_keys(KEYS_PROSES)
                st.rerun()
    elif not st.session_state.get("data_sph_terkirim"):
        if st.button("❌ Reset Scanner", type="secondary"):
            reset_keys(KEYS_PROSES)
            st.rerun()
