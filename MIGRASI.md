# Migrasi Laporan Produksi Press: Google Sheets → Supabase

## Isi paket

| File | Fungsi |
|---|---|
| `supabase_schema.sql` | Tabel, relasi, index anti-dobel, view laporan, RLS. Jalankan sekali di SQL Editor. |
| `db.py` | Lapisan database: koneksi, retry, semua fungsi CRUD. |
| `Trial.py` | Aplikasi Streamlit (alur UI sama: IDLE → SELECTING_PROCESS → RUNNING → FINISHING). |
| `master_import.py` | Logika konversi CSV Sheets → tabel Supabase (dipakai menu Admin & skrip). |
| `import_master.py` | Import master dari komputer (alternatif menu Admin). |
| `test_koneksi.py` | Uji koneksi + aturan anti-dobel, data uji dihapus otomatis. |
| `requirements.txt` | Dependensi baru (gsheets, gspread, oauth2client, pytz dihapus). |
| `secrets.toml.example` | Contoh konfigurasi kredensial. |

## Pemetaan Sheet → Tabel

| Sheet lama | Tabel baru | Catatan |
|---|---|---|
| Master_Karyawan | `master_karyawan` | NIK disimpan tanpa titik/kutip; kolom `aktif` untuk menonaktifkan karyawan. |
| MainData | `main_data` + `master_line` | Unik per (part_no, urutan). Daftar line kini dari tabel, bukan hardcode. |
| Waktu Kerja | `waktu_kerja` | `check_in`/`check_out` = timestamptz. |
| Proses | `proses` | Terhubung ke `waktu_kerja` (shift). Kolom kosong `Waktu_Mulai`/`Waktu_Selesai` dihapus. `%_Prod` & `Rasio_NG` disimpan sebagai angka (NULL = N/A untuk DPMR). |
| ABNORMAL | `abnormal` + `master_kode_abnormal` | Terhubung ke `proses`; kode abnormal kini dari tabel. |

Untuk tampilan persis seperti sheet lama (jam WIB, `%_Prod` berformat "83.33%"), buka view `v_laporan_proses`, `v_laporan_waktu_kerja`, `v_laporan_abnormal`.

## Langkah implementasi (tanpa perlu Python di komputer)

1. **Buat tabel**: Supabase Dashboard → project *Production Laporan_Press* → **SQL Editor** → New query → paste seluruh isi `supabase_schema.sql` → **Run**. Harus muncul "Success. No rows returned".
2. **Ambil kredensial**: Project Settings → **API Keys** → salin *Secret key* (`sb_secret_...`). URL project: `https://ligyksfajemetxtdwjtn.supabase.co`.
3. **Isi Secrets di Streamlit Cloud**: App → ⋮ → Settings → **Secrets**, paste:
   ```toml
   [supabase]
   url = "https://ligyksfajemetxtdwjtn.supabase.co"
   key = "sb_secret_...."

   [admin]
   pin = "PIN_PILIHAN_ANDA"
   ```
   Simpan, lalu **Reboot app**.
4. **Import data master**: di Google Sheets, buka sheet `Master_Karyawan` → File → Download → CSV. Ulangi untuk sheet `MainData`. Di aplikasi, buka sidebar → **🛠️ Admin: Import Data Master** → isi PIN → klik **Cek Koneksi Database** → upload kedua CSV → **Import ke Supabase**.
5. **Uji coba** dengan checklist di bawah.
6. **Masa transisi**: jadikan Google Sheets read-only ±1 minggu sebagai cadangan.

Alternatif lewat komputer: `pip install -r requirements.txt`, buat `.streamlit/secrets.toml` dari contoh, lalu `python test_koneksi.py` dan `python import_master.py`.

## Checklist uji manual (dengan 1 HP)

- [ ] Scan QR ID valid → masuk layar Check-In. QR NIK tak terdaftar → "Akses Ditolak".
- [ ] Check-In → baris baru di `waktu_kerja`. Klik dua kali cepat → tetap 1 baris.
- [ ] Scan KANBAN → pilih Condition **Overtime**, Actual Line, urutan → Konfirmasi.
- [ ] Ubah jam start manual (mis. 15 menit lalu) → Konfirmasi Start → cek `proses.actual_time_start` di view = jam WIB yang dipilih, `condition` = Overtime.
- [ ] Tutup browser, buka lagi, scan ID → proses langsung dipulihkan (RUNNING) dengan jam start yang benar.
- [ ] Kirim 1 abnormal → muncul di `abnormal` dengan `proses_id` terisi; form kosong lagi.
- [ ] Scan KANBAN berbeda → ditolak. Scan KANBAN sama → layar FINISHING.
- [ ] Isi ACT/NG, jam finish manual, break → Kirim SPH → status FINISH, %_Prod & Rasio_NG sesuai hitungan lama.
- [ ] Ulangi dengan urutan DPMR → `persen_prod` & `rasio_ng` NULL (tampil N/A).
- [ ] Check-Out saat masih ada START → ditolak. Setelah selesai → `check_out` terisi.
- [ ] Uji shift malam: start 23:50, finish 00:30 → `total_jam` positif dan benar.

## Yang berubah dibanding versi Google Sheets

- **Tidak ada lagi tulis-ulang seluruh sheet.** Setiap aksi hanya `insert`/`update` 1 baris berdasarkan `id`, jadi dua operator yang menyimpan bersamaan tidak saling menimpa.
- **Anti-dobel dijaga database**, bukan hanya aplikasi: 1 shift aktif per NIK, 1 START aktif per NIK, abnormal dengan `client_ref` unik. Klik dobel / koneksi putus lalu retry tidak menghasilkan data ganda.
- **Waktu selalu WIB yang benar.** Versi lama memakai `date.today()` (zona server Streamlit Cloud = UTC), sehingga input antara 00:00–07:00 WIB tercatat di tanggal kemarin. Sekarang semua waktu timezone-aware dan proses yang melewati tengah malam dihitung benar.
- **Pemulihan sesi diperbaiki**: sesi yang dipulihkan lewat scan KANBAN kini langsung berstatus "sudah start" (dulu bisa memicu START ganda).
- **Cache hanya untuk data master** (5–60 menit). Data transaksi selalu dibaca langsung dari database. Tombol "Update Data Master" tetap ada.
- Pemilih jam memakai langkah 1 menit dan nilai default-nya tidak berubah saat menit berganti, jadi jam yang sudah diketik operator tidak ter-reset.

## Troubleshooting

| Gejala | Penyebab & solusi |
|---|---|
| `Konfigurasi [supabase] url/key belum ada` | `secrets.toml` belum dibuat / salah nama section. |
| `permission denied` / data kosong padahal ada | Memakai *publishable/anon key*. Ganti ke *secret key*. |
| `violates foreign key ... master_line` | Line belum ada di `master_line`. Tambahkan lewat Table Editor. |
| `violates foreign key ... master_karyawan` | NIK belum di-import. Jalankan `import_master.py` ulang. |
| "Koneksi ke database terputus" | Jaringan pabrik putus; aplikasi sudah retry 3×. Coba lagi setelah sinyal kembali. |
