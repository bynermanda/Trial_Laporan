"""
Laporan Produksi Dept. Press — PT Indosafety Sentosa
Versi Supabase · tampilan "Industrial Dark / Operator Terminal".

Alur layar (tanpa check-in/check-out):
  1. Scan ID Operator
  2. Area laporan: IDLE → SELECTING_PROCESS → RUNNING → FINISHING

Akses database ada di db.py, tema & komponen tampilan di ui.py.
"""
import time
import uuid
from datetime import timedelta

import streamlit as st
import streamlit.components.v1 as components
from streamlit_qrcode_scanner import qrcode_scanner

import db
import ui
from db import DBError, DuplicateError, combine_wib, normalize_nik, now_wib, parse_ts

# set_page_config WAJIB jadi perintah Streamlit pertama
st.set_page_config(
    page_title="Press Terminal · PT ISI",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)


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
    "Break 1 · 10m":        10,
    "Break 2 · 10m":        10,
    "Istirahat · 40m":      40,
    "Extra Break · 15m":    15,
    "2S · 15m":             15,
    "Ist. Jumat · 70m":     70,
}

KEYS_PROSES = [
    "status_kerja", "current_part", "waktu_start", "waktu_end",
    "data_sph_terkirim", "available_processes", "sudah_start_diklik",
    "actual_summary_data", "ab_counter",
    "default_jam_start", "input_actual_time_start", "input_actual_time_finish",
    "radio_condition",
] + [f"brk_{i}" for i in range(len(DAFTAR_BREAK))]
KEYS_OPERATOR = ["nama_terpilih", "nik_karyawan"] + KEYS_PROSES


# ============================================================
# TEMA & PENGAMAN REFRESH
# ============================================================
ui.terapkan_tema()

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
# HELPER
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


def fmt_angka(v) -> str:
    f = float(v or 0)
    return f"{f:g}" if f == int(f) else f"{f:.2f}"


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
                flash(f"Sesi {aktif['part_no']} dipulihkan!", "🔄")
                st.rerun()

            proses_list = db.get_part_processes(part_no)
            if not proses_list:
                st.error(f"❌ Part No **{part_no}** tidak terdaftar di Main Data.")
                return
            st.session_state.available_processes = proses_list
            st.session_state.status_kerja = "SELECTING_PROCESS"
            st.rerun()

        elif status == "RUNNING":
            dp = st.session_state.current_part
            if not st.session_state.get("sudah_start_diklik"):
                st.error("⚠️ Tekan **MULAI PRODUKSI** dulu sebelum scan FINISH.")
                return
            if part_no == str(dp["part_no"]).strip():
                st.session_state.status_kerja = "FINISHING"
                st.session_state.waktu_end = now_wib()
                flash("Scan Finish berhasil!", "🏁")
                st.rerun()
            else:
                st.error(f"❌ KANBAN **{part_no}** berbeda dengan Part aktif **{dp['part_no']}**.")
    except DBError as e:
        tampilkan_error(e, "Gagal membaca data")


# ============================================================
# MENU ADMIN (di bawah layar Scan ID)
# ============================================================
def menu_admin() -> None:
    with st.expander("⚙️ Admin"):
        if st.button("🔄 Muat Ulang Data Master", width="stretch"):
            st.cache_data.clear()
            st.success("Cache data master dikosongkan.")

        try:
            pin_benar = str(st.secrets.get("admin", {}).get("pin", "")).strip()
        except Exception:
            pin_benar = ""
        if not pin_benar:
            st.info("Tambahkan [admin] pin = \"....\" di Secrets untuk membuka menu import.")
            return
        if st.text_input("PIN Admin", type="password", key="admin_pin") != pin_benar:
            return

        if st.button("🔌 Cek Koneksi Database", width="stretch"):
            try:
                st.success(f"Terhubung. Karyawan terdaftar: {db.ping()}")
            except DBError as e:
                st.error(f"{e}")

        st.caption("Google Sheets → File → Download → CSV, lalu upload di sini. Aman diulang (upsert).")
        f_kary = st.file_uploader("Master_Karyawan.csv", type="csv", key="up_kary")
        f_main = st.file_uploader("MainData.csv", type="csv", key="up_main")

        if st.button("⬆️ Import ke Supabase", disabled=not (f_kary or f_main), width="stretch"):
            import pandas as pd
            import master_import as mi
            try:
                client = db.get_client()
                if f_kary:
                    n = mi.import_karyawan(client, pd.read_csv(f_kary, dtype=str))
                    st.success(f"master_karyawan: {n} baris")
                if f_main:
                    n_line, n_part = mi.import_main_data(client, pd.read_csv(f_main, dtype=str))
                    st.success(f"master_line: {n_line} baris, main_data: {n_part} baris")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Import gagal: {e}")


# ============================================================
# STATE SAAT INI
# ============================================================
tampilkan_flash()

nama_karyawan = st.session_state.get("nama_terpilih", "")
nik_karyawan = st.session_state.get("nik_karyawan", "")

if not nik_karyawan:
    tahap = "LOGIN"
else:
    tahap = st.session_state.get("status_kerja", "IDLE")

ui.topbar(tahap, nama_karyawan, nik_karyawan)


# ============================================================
# LAYAR 1: SCAN ID OPERATOR
# ============================================================
if tahap == "LOGIN":
    _, tengah, _ = st.columns([1, 2, 1])
    with tengah:
        with st.container(key="card_login"):
            ui.judul("Langkah 1 · Identitas Operator", "Arahkan kamera ke QR Code ID card Anda.")
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
                        st.error(f"🚫 Akses ditolak! NIK **{raw_nik}** tidak terdaftar.")
                    else:
                        reset_keys(KEYS_OPERATOR)
                        st.session_state.nik_karyawan = nik
                        st.session_state.nama_terpilih = kary.get("nama") or raw_nama

                        with st.spinner("Mengecek status kerja terakhir..."):
                            aktif = db.get_active_proses(nik)

                        if aktif:
                            pulihkan_proses(aktif)
                            flash(f"Melanjutkan proses: {aktif.get('part_name')}", "🔄")
                        else:
                            st.session_state.status_kerja = "IDLE"
                            flash(f"Terverifikasi: {st.session_state.nama_terpilih}")
                        st.rerun()
                except DBError as e:
                    tampilkan_error(e, "Gagal verifikasi ID")

        st.write("")
        menu_admin()


# ============================================================
# LAYAR 2: IDLE — scan kanban / input manual
# ============================================================
elif tahap == "IDLE":
    try:
        rekap = db.ringkasan_hari_ini(nik_karyawan)
    except DBError:
        rekap = None
    ui.kpi_grid([
        ("Tanggal", now_wib().strftime("%d %b %Y"), ""),
        ("Laporan Hari Ini", f"{rekap['jumlah']} part" if rekap else "—", "", "SPH terkirim"),
        ("Total ACT Hari Ini", f"{rekap['act']} pcs" if rekap else "—", "ok"),
    ])

    kiri, kanan = st.columns([3, 2], gap="medium")
    with kiri:
        with st.container(key="card_scan_start"):
            ui.judul("Scan KANBAN", "Scan QR KANBAN part yang akan diproses.")
            barcode_part = qrcode_scanner(key="scanner_part_prod")
            if barcode_part:
                handle_scan(barcode_part)

    with kanan:
        with st.container(key="card_manual_start"):
            ui.judul("Input Manual", "Jika QR KANBAN rusak / tidak terbaca.")
            manual_input = st.text_input("Part No.", key="manual_part_input",
                                         placeholder="cth. 23-4579831-2").strip().upper()
            if st.button("LANJUT ➜", key="btn_manual_start", type="primary", width="stretch") and manual_input:
                handle_scan(manual_input)

        st.write("")
        if st.button("⏻  KELUAR / GANTI OPERATOR", key="stop_logout", width="stretch"):
            reset_keys(KEYS_OPERATOR)
            flash("Anda sudah keluar. Silakan scan ID berikutnya.", "👋")
            st.rerun()


# ============================================================
# LAYAR 3: SELECTING_PROCESS — kondisi, line & urutan proses
# ============================================================
elif tahap == "SELECTING_PROCESS":
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

    contoh = data_pilihan[0]
    with st.container(key="card_part_info"):
        st.markdown(
            f'<div class="sec">Part terdeteksi</div>'
            f'<div class="bigname">{ui.esc(contoh.get("part_name"))}</div>'
            f'<div class="hint mono">{ui.esc(contoh.get("part_no"))} · {ui.esc(contoh.get("model"))}</div>',
            unsafe_allow_html=True,
        )

    st.write("")
    opsi_display = {f"{p['urutan']}": p for p in data_pilihan}

    kiri, kanan = st.columns(2, gap="medium")
    with kiri:
        with st.container(key="card_pilih_proses"):
            ui.judul("1 · Urutan Proses")
            if len(opsi_display) <= 12:
                pilihan_user = st.radio("Urutan proses", options=list(opsi_display.keys()), index=0,
                                        horizontal=True, key=f"radio_urutan_{contoh.get('part_no')}",
                                        label_visibility="collapsed")
            else:
                pilihan_user = st.selectbox("Urutan proses", options=list(opsi_display.keys()),
                                            key=f"sel_urutan_{contoh.get('part_no')}", label_visibility="collapsed")

            ui.judul("2 · Kondisi Kerja")
            selected_condition = st.radio(
                "Kondisi", options=["Normal", "Overtime"], index=0, horizontal=True,
                key="radio_condition", label_visibility="collapsed",
            )

    with kanan:
        with st.container(key="card_pilih_line"):
            ui.judul("3 · Mesin / Actual Line")
            detail_awal = opsi_display.get(pilihan_user or "", contoh)
            line_default = detail_awal.get("line")
            idx_line = list_line.index(line_default) if line_default in list_line else 0
            actual_line = st.selectbox("Actual line", options=list_line, index=idx_line,
                                       key="sel_actual_line", label_visibility="collapsed")

            if pilihan_user:
                d = opsi_display[pilihan_user]
                ui.kpi_grid([
                    ("Target Sec/Pcs", fmt_angka(d.get("sec_pcs")), "accent"),
                    ("Line Standar", d.get("line") or "-", ""),
                ])

    st.write("")
    b1, b2 = st.columns([1, 3], gap="medium")
    with b1:
        if st.button("✕ Batal", width="stretch"):
            reset_keys(KEYS_PROSES)
            st.rerun()
    with b2:
        if st.button("KONFIRMASI PROSES ➜", key="go_pilih_proses", width="stretch", disabled=not pilihan_user):
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


# ============================================================
# LAYAR 4: RUNNING — proses produksi berjalan
# ============================================================
elif tahap == "RUNNING":
    dp = st.session_state.get("current_part")
    if not dp:
        st.session_state.status_kerja = "IDLE"
        st.rerun()

    sudah_start = bool(st.session_state.get("sudah_start_diklik"))
    ui.panel_produksi(dp, st.session_state.waktu_start, sudah_start)

    ui.kpi_grid([
        ("Target Sec/Pcs", fmt_angka(dp["sec_pcs"]), "accent"),
        ("Target / Jam", f"{int(3600 / dp['sec_pcs'])} pcs" if dp["sec_pcs"] else "—", ""),
        ("Line Standar", dp["line"] or "-", ""),
        ("Status Data", "TERSIMPAN" if sudah_start else "BELUM START", "ok" if sudah_start else "bad"),
    ])

    # ---------------- Konfirmasi START ----------------
    if not sudah_start:
        with st.container(key="card_start"):
            ui.judul("Konfirmasi Mulai Produksi", "Sesuaikan jam mulai bila perlu, lalu tekan MULAI PRODUKSI.")
            c_jam, c_btn = st.columns([1, 2], gap="medium", vertical_alignment="bottom")
            with c_jam:
                jam_manual = st.time_input(
                    "Jam Start",
                    # default dikunci sekali agar input operator tidak ter-reset saat menit berganti
                    value=st.session_state.setdefault(
                        "default_jam_start", now_wib().time().replace(second=0, microsecond=0)),
                    step=60,
                    key="input_actual_time_start",
                )
            with c_btn:
                klik_start = st.button("▶  MULAI PRODUKSI", key="go_start", width="stretch")

        if klik_start:
            now = now_wib()
            start_dt = combine_wib(now.date(), jam_manual)
            # Shift malam: jam start 23:50 diinput pukul 00:10 → milik kemarin
            if start_dt > now + timedelta(minutes=5):
                start_dt -= timedelta(days=1)

            data_start = {
                "tanggal":           start_dt.date(),
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
                flash(f"Produksi dimulai pukul {start_dt:%H:%M} ({dp['condition']})", "🚀")
                st.rerun()
            except DuplicateError:
                st.error("⚠️ Masih ada proses START aktif di database. "
                         "Tekan Reset lalu scan KANBAN lagi — sesi lama akan dipulihkan.")
            except DBError as e:
                tampilkan_error(e, "Gagal menyimpan START")

    # ---------------- Finish & Abnormal (tab) ----------------
    tab_finish, tab_abnormal = st.tabs(["🏁  FINISH", "⚠️  ABNORMAL"])

    with tab_finish:
        kiri, kanan = st.columns([3, 2], gap="medium")
        with kiri:
            with st.container(key="card_scan_finish"):
                ui.judul("Scan KANBAN Finish", "Scan KANBAN yang sama untuk mengakhiri proses.")
                barcode_data = qrcode_scanner(key="scanner_finish_part")
                if barcode_data:
                    handle_scan(barcode_data)
        with kanan:
            with st.container(key="card_manual_finish"):
                ui.judul("Input Manual Finish")
                manual_finish = st.text_input("Part No.", key="manual_part_finish_input",
                                              placeholder=dp["part_no"]).strip().upper()
                if st.button("FINISH ➜", key="btn_manual_finish", type="primary", width="stretch") and manual_finish:
                    handle_scan(manual_finish)

    with tab_abnormal:
        with st.container(key="card_abnormal"):
            ui.judul("Catat Kendala", "Langsung tersimpan. Untuk DPMR, tulis jumlah OK & NG di Keterangan.")
            try:
                list_kode = [f"{r['kode']} [{r['uraian']}]" for r in db.get_kode_abnormal()] or FALLBACK_KODE_ABNORMAL
            except DBError:
                list_kode = FALLBACK_KODE_ABNORMAL

            counter = st.session_state.setdefault("ab_counter", 0)
            c_kod, c_men = st.columns([3, 1], gap="small")
            k_sel  = c_kod.selectbox("Kode Abnormal", options=list_kode, key=f"ab_kode_run_{counter}")
            m_val  = c_men.number_input("Menit", min_value=0, step=1, key=f"ab_menit_run_{counter}")
            kt_val = st.text_input("Keterangan", placeholder="cth. MESIN DOWN, TUNGGU MAINTENANCE",
                                   key=f"ab_ket_run_{counter}").upper()

            if st.button("KIRIM ABNORMAL", key=f"go_abnormal_{counter}", width="stretch"):
                if not st.session_state.get("sudah_start_diklik"):
                    st.error("⚠️ Tekan MULAI PRODUKSI sebelum kirim data abnormal.")
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
                        flash(f"Abnormal {kode.strip()} · {int(m_val)} menit tersimpan", "⚠️")
                        st.rerun()
                    except DBError as e:
                        tampilkan_error(e, "Gagal menyimpan ABNORMAL")
                else:
                    st.error("Pilih Kode & isi Menit (lebih dari 0).")

    # ---------------- Tombol bawah ----------------
    st.divider()
    c_ref, c_res = st.columns(2)
    with c_ref:
        if st.button("↻ Perbarui", width="stretch"):
            st.rerun()
    with c_res:
        if st.button("Reset Scanner", width="stretch"):
            # Data START di database TIDAK dihapus; scan KANBAN berikutnya akan memulihkannya.
            reset_keys(KEYS_PROSES)
            st.rerun()


# ============================================================
# LAYAR 5: FINISHING — ACT, NG, jam finish, istirahat, kirim SPH
# ============================================================
elif tahap == "FINISHING":
    dp = st.session_state.get("current_part")
    if not dp:
        st.session_state.status_kerja = "IDLE"
        st.rerun()

    sudah_terkirim = st.session_state.get("data_sph_terkirim", False)
    dt_start = st.session_state.waktu_start
    is_repair = dp["urutan_proses"] == "DPMR"

    with st.container(key="card_finish_head"):
        st.markdown(
            f'<div class="sec">Laporan akhir · Urutan {ui.esc(dp["urutan_proses"])} · {ui.esc(dp["condition"]).upper()}</div>'
            f'<div class="bigname">{ui.esc(dp["part_name"])}</div>'
            f'<div class="hint mono">{ui.esc(dp["part_no"])} · Line {ui.esc(dp["Actual_Line"] or "-")} · '
            f'Start {dt_start:%H:%M}</div>',
            unsafe_allow_html=True,
        )

    st.write("")
    kiri, kanan = st.columns([3, 2], gap="medium")

    with kiri:
        with st.container(key="card_hasil"):
            ui.judul("1 · Hasil Produksi")
            c1, c2 = st.columns(2)
            act = int(c1.number_input("ACT (pcs OK)", min_value=0, step=1, value=0, disabled=sudah_terkirim))
            ng = int(c2.number_input("NG (pcs)", min_value=0, step=1, value=0, disabled=sudah_terkirim))

            ui.judul("2 · Jam Selesai")
            default_finish = st.session_state.get("waktu_end") or now_wib()
            waktu_finish_manual = st.time_input(
                "Jam Finish",
                value=default_finish.time().replace(second=0, microsecond=0),
                step=60,
                key="input_actual_time_finish",
                disabled=sudah_terkirim,
                label_visibility="collapsed",
            )

            ui.judul("3 · Potongan Istirahat")
            kolom_break = st.columns(3, gap="small")
            pilihan_break = [
                nama for i, nama in enumerate(DAFTAR_BREAK)
                if kolom_break[i % 3].checkbox(nama, key=f"brk_{i}", disabled=sudah_terkirim)
            ]
            extra_custom = st.number_input("Potongan lain (menit)", min_value=0, step=1, value=0,
                                           disabled=sudah_terkirim)

    # ---------- Perhitungan (rumus sama dengan versi lama) ----------
    dt_finish = combine_wib(dt_start.date(), waktu_finish_manual)
    if dt_finish < dt_start:             # lewat tengah malam
        dt_finish += timedelta(days=1)
    durasi_kotor_menit = (dt_finish - dt_start).total_seconds() / 60
    total_potongan = sum(DAFTAR_BREAK[b] for b in pilihan_break) + int(extra_custom)

    durasi_bersih_menit = max(0.0, durasi_kotor_menit - total_potongan)
    total_jam_actual = durasi_bersih_menit / 60
    total_waktu_actual_str = f"{int(durasi_bersih_menit // 60)} Jam {int(durasi_bersih_menit % 60)} Menit"

    val_sec_pcs   = float(dp.get("sec_pcs") or 0)
    standar_input = (val_sec_pcs * act) / 60 if (act > 0 and not is_repair) else 0
    persen_prod   = round((standar_input / durasi_bersih_menit) * 100, 2) if (durasi_bersih_menit > 0 and not is_repair) else 0.0
    rasio_ng      = round(ng / act * 100, 2) if (act > 0 and not is_repair) else 0.0

    with kanan:
        with st.container(key="card_preview"):
            ui.judul("Pratinjau SPH", "Diperbarui otomatis saat Anda mengisi.")
            ui.kpi_grid([
                ("% Produksi", "N/A" if is_repair else f"{persen_prod:.1f}%",
                 "hero " + ("" if is_repair else "ok" if persen_prod >= 85 else "accent" if persen_prod >= 60 else "bad")),
                ("Rasio NG", "N/A" if is_repair else f"{rasio_ng:.2f}%",
                 "" if is_repair else "ok" if rasio_ng <= 1 else "accent" if rasio_ng <= 3 else "bad"),
                ("Durasi Bersih", f"{int(durasi_bersih_menit // 60)}j {int(durasi_bersih_menit % 60)}m", "",
                 f"Kotor {int(durasi_kotor_menit)}m − istirahat {total_potongan}m"),
                ("Waktu", f"{dt_start:%H:%M}–{dt_finish:%H:%M}", ""),
            ])
            if ng > act > 0:
                st.warning("NG lebih besar dari ACT. Periksa kembali angkanya.")

    st.write("")

    # ---------- Kirim SPH ----------
    if not sudah_terkirim:
        b1, b2 = st.columns([1, 3], gap="medium")
        with b1:
            if st.button("← Kembali", width="stretch"):
                st.session_state.status_kerja = "RUNNING"
                st.rerun()
        with b2:
            if st.button("KIRIM DATA SPH", key="go_kirim_sph", width="stretch"):
                if act <= 0:
                    st.error("⚠️ Jumlah ACT harus lebih dari 0.")
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
                            st.error("❌ Tidak ditemukan data START aktif untuk Part ini. Lakukan Start dulu.")
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
                                "act":                act,
                                "ng":                 ng,
                            }
                            flash("SPH terkirim!")
                            st.rerun()
                    except DBError as e:
                        tampilkan_error(e, "Gagal menyimpan SPH")

    # ---------- Ringkasan setelah terkirim ----------
    else:
        s = st.session_state.get("actual_summary_data", {})
        st.success("✅ Data SPH sudah tercatat di database.")
        ui.kpi_grid([
            ("% Produksi", "N/A" if s.get("is_repair") else f"{s.get('persen_prod', 0):.2f}%", "hero accent"),
            ("ACT / NG", f"{s.get('act', 0)} / {s.get('ng', 0)}", "hero"),
            ("Rasio NG", "N/A" if s.get("is_repair") else f"{s.get('rasio_ng', 0):.2f}%", "hero"),
            ("Total Waktu", s.get("total_waktu_actual", "-"), "hero", f"{s.get('total_jam', 0)} jam"),
        ])
        if st.button("SELESAI · SCAN PART BARU", key="go_selesai", width="stretch"):
            reset_keys(KEYS_PROSES)
            st.session_state.status_kerja = "IDLE"
            flash("Laporan proses selesai. Siap scan part baru.", "🎉")
            st.rerun()


# ============================================================
# Reset untuk layar IDLE (bila scanner macet)
# ============================================================
if tahap == "IDLE":
    st.divider()
    if st.button("Reset Scanner", width="stretch"):
        reset_keys(KEYS_PROSES)
        st.rerun()
