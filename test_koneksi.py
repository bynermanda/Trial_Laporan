"""
test_koneksi.py — Uji koneksi & aturan database Supabase dari awal sampai akhir.

Jalankan:  python test_koneksi.py
(kredensial dibaca dari .streamlit/secrets.toml)

Yang diuji:
  1. Koneksi + semua tabel bisa dibaca
  2. Check-in, dan check-in kedua DITOLAK (anti dobel)
  3. START proses, dan START kedua DITOLAK (anti dobel)
  4. ABNORMAL dengan client_ref sama DITOLAK (anti dobel kirim)
  5. FINISH hanya bisa sekali
  6. Check-out + view laporan dalam jam WIB
Semua data uji memakai NIK 'TEST-0000' dan DIHAPUS di akhir.
"""
import sys
import tomllib
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from postgrest.exceptions import APIError
from supabase import create_client

TZ = ZoneInfo("Asia/Jakarta")
NIK = "TEST-0000"
TABEL = ["master_karyawan", "master_line", "master_kode_abnormal", "main_data",
         "waktu_kerja", "proses", "abnormal"]
gagal = 0


def ok(msg):
    print(f"  ✅ {msg}")


def salah(msg):
    global gagal
    gagal += 1
    print(f"  ❌ {msg}")


def harus_duplikat(fn, label):
    try:
        fn()
        salah(f"{label}: seharusnya DITOLAK tapi lolos")
    except APIError as e:
        if e.code == "23505":
            ok(f"{label}: ditolak database (23505) ✔")
        else:
            salah(f"{label}: error tak terduga {e.code} {e.message}")


def main():
    cfg = tomllib.loads(Path(".streamlit/secrets.toml").read_text(encoding="utf-8"))["supabase"]
    c = create_client(cfg["url"], cfg["key"])

    print("1. Koneksi & tabel")
    for t in TABEL:
        try:
            res = c.table(t).select("*", count="exact").limit(1).execute()
            ok(f"{t}: {res.count} baris")
        except Exception as e:
            salah(f"{t}: {e}")
    if gagal:
        sys.exit("Koneksi/tabel bermasalah. Cek URL, key, dan apakah supabase_schema.sql sudah dijalankan.")

    now = datetime.now(TZ).replace(microsecond=0)
    try:
        c.table("master_karyawan").upsert({"nik": NIK, "nama": "OPERATOR TEST"}).execute()

        print("2. Check-in")
        shift = c.table("waktu_kerja").insert({
            "tanggal": now.date().isoformat(), "nik": NIK, "nama": "OPERATOR TEST",
            "check_in": now.isoformat()}).execute().data[0]
        ok(f"check-in id={shift['id']}")
        harus_duplikat(lambda: c.table("waktu_kerja").insert({
            "tanggal": now.date().isoformat(), "nik": NIK, "nama": "OPERATOR TEST"}).execute(),
            "check-in kedua")

        print("3. START proses")
        start = now - timedelta(minutes=30)
        base = {"tanggal": now.date().isoformat(), "waktu_kerja_id": shift["id"], "nik": NIK,
                "nama": "OPERATOR TEST", "part_no": "TEST-PART", "part_name": "PART UJI",
                "urutan_proses": "OP10", "actual_line": "BM", "condition": "Overtime",
                "sec_pcs": 6, "actual_time_start": start.isoformat()}
        proses = c.table("proses").insert(base).execute().data[0]
        ok(f"START id={proses['id']}, condition={proses['condition']}")
        harus_duplikat(lambda: c.table("proses").insert(base).execute(), "START kedua")

        print("4. ABNORMAL")
        ref = str(uuid.uuid4())
        ab = {"client_ref": ref, "proses_id": proses["id"], "tanggal": now.date().isoformat(),
              "jam_input": now.time().isoformat(), "operator": "OPERATOR TEST", "nik": NIK,
              "kode_abnormal": "I", "uraian_abnormal": "Mesin Abnormal", "total_waktu": 5}
        c.table("abnormal").insert(ab).execute()
        ok("abnormal tersimpan")
        harus_duplikat(lambda: c.table("abnormal").insert(ab).execute(), "abnormal dobel kirim")

        print("5. FINISH")
        fin = {"actual_time_finish": now.isoformat(), "act": 250, "ng": 2, "persen_prod": 83.33,
               "total_istirahat": 10, "rasio_ng": 0.8, "total_jam": 0.33, "status": "FINISH"}
        r1 = c.table("proses").update(fin).eq("id", proses["id"]).eq("status", "START").execute()
        r2 = c.table("proses").update(fin).eq("id", proses["id"]).eq("status", "START").execute()
        ok("FINISH tersimpan") if len(r1.data) == 1 else salah("FINISH pertama gagal")
        ok("FINISH kedua diabaikan (0 baris)") if not r2.data else salah("FINISH kedua menimpa data!")

        print("6. Check-out & view laporan")
        c.table("waktu_kerja").update({"check_out": now.isoformat(), "total_jam": 0.5,
                                       "aktivitas": "Shift Complete"}).eq("id", shift["id"]).execute()
        lap = c.table("v_laporan_proses").select("*").eq("id", proses["id"]).execute().data[0]
        jam_wib = start.strftime("%H:%M:%S")
        if lap["actual_time_start"] == jam_wib:
            ok(f"view WIB benar: start {lap['actual_time_start']}, %_Prod {lap['%_Prod']}")
        else:
            salah(f"jam view {lap['actual_time_start']} ≠ {jam_wib} (cek zona waktu)")
    except Exception as e:
        salah(f"Error tak terduga: {e}")
    finally:
        print("7. Bersihkan data uji")
        for t in ["abnormal", "proses", "waktu_kerja", "master_karyawan"]:
            c.table(t).delete().eq("nik", NIK).execute()
        ok("data uji dihapus")

    print("\n" + ("🎉 SEMUA TES LULUS" if not gagal else f"⚠️ {gagal} TES GAGAL"))
    sys.exit(1 if gagal else 0)


if __name__ == "__main__":
    main()
