# Migrasi Laporan Produksi Press: Google Sheets → Supabase

## Isi paket

| File | Fungsi |
|---|---|
| `supabase_schema.sql` | Tabel, relasi, index anti-dobel, view laporan, RLS. Jalankan sekali di SQL Editor. |
| `db.py` | Lapisan database: koneksi, retry, semua fungsi CRUD. |
| `Trial.py` | Aplikasi Streamlit (alur UI sama: IDLE → SELECTING_PROCESS → RUNNING → FINISHING). |
| `import_master.py` | Pindahkan Master_Karyawan & MainData dari CSV Sheets ke Supabase. |
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

## Langkah implementasi

1. **Buat project Supabase** (region Singapore `ap-southeast-1`, terdekat ke Karawang).
2. **Jalankan skema**: Dashboard → SQL Editor → paste `supabase_schema.sql` → Run.
3. **Kredensial**: Project Settings → API → salin *Project URL* dan *Secret key*. Salin `secrets.toml.example` ke `.streamlit/secrets.toml` dan isi. Tambahkan `.streamlit/secrets.toml` ke `.gitignore`.
4. **Pasang dependensi**: `pip install -r requirements.txt`
5. **Uji koneksi**: `python test_koneksi.py` → harus muncul `🎉 SEMUA TES LULUS`.
6. **Import master**: download sheet `Master_Karyawan` & `MainData` sebagai CSV → `python import_master.py`.
7. **Jalankan aplikasi lokal**: `streamlit run Trial.py`, lalu uji manual (checklist di bawah).
8. **Deploy**: push ke GitHub (tanpa secrets.toml), lalu di Streamlit Cloud → Settings → Secrets paste isi `secrets.toml`.
9. **Masa transisi**: jadikan Google Sheets read-only ±1 minggu sebagai cadangan.

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
