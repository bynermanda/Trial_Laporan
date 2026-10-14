-- =====================================================================
-- SKEMA SUPABASE — Laporan Produksi Dept. Press PT Indosafety Sentosa
-- Pengganti worksheet Google Sheets:
--   Master_Karyawan → master_karyawan
--   MainData        → main_data (+ master_line)
--   Waktu Kerja     → waktu_kerja
--   Proses          → proses
--   ABNORMAL        → abnormal (+ master_kode_abnormal)
--
-- Cara pakai: Supabase Dashboard → SQL Editor → paste seluruh file → Run.
-- Aman dijalankan ulang (pakai IF NOT EXISTS / ON CONFLICT).
--
-- Konvensi waktu:
--   * Semua jam disimpan sebagai TIMESTAMPTZ (UTC di database).
--   * Aplikasi mengirim waktu WIB (Asia/Jakarta) lengkap dengan offset,
--     view laporan mengonversi kembali ke WIB.
--   * Kolom `tanggal` (DATE) adalah tanggal WIB, untuk filter laporan harian.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. MASTER DATA
-- ---------------------------------------------------------------------

create table if not exists public.master_karyawan (
    nik          text primary key,                 -- disimpan TANPA titik & tanda kutip
    nama         text not null,
    departemen   text not null default 'PRESS',
    aktif        boolean not null default true,    -- false = karyawan keluar, tidak bisa login
    created_at   timestamptz not null default now(),
    constraint ck_master_karyawan_nik check (nik = btrim(nik) and nik <> '')
);

create table if not exists public.master_line (
    kode        text primary key,                  -- contoh: BM, CM, DM, ERM ...
    keterangan  text,
    aktif       boolean not null default true
);

create table if not exists public.master_kode_abnormal (
    kode           text primary key,               -- contoh: A, B, G1, K2 ...
    uraian         text not null,
    urutan_tampil  integer not null default 0,
    aktif          boolean not null default true
);

create table if not exists public.main_data (
    id          bigint generated always as identity primary key,
    part_no     text not null,
    part_name   text not null default '',
    model       text,
    line        text references public.master_line(kode) on update cascade,
    urutan      text not null,                     -- urutan proses (OP10, OP20, DPMR, ...)
    sec_pcs     numeric(10,2) not null default 0 check (sec_pcs >= 0),
    aktif       boolean not null default true,
    created_at  timestamptz not null default now(),
    constraint uq_main_data_part_urutan unique (part_no, urutan)
);
create index if not exists ix_main_data_part_no on public.main_data (part_no);


-- ---------------------------------------------------------------------
-- 2. WAKTU KERJA (absensi / shift)
-- ---------------------------------------------------------------------

create table if not exists public.waktu_kerja (
    id          bigint generated always as identity primary key,
    tanggal     date not null,                     -- tanggal WIB saat check-in
    nik         text not null references public.master_karyawan(nik) on update cascade,
    nama        text not null,                     -- snapshot nama saat check-in
    check_in    timestamptz not null default now(),
    check_out   timestamptz,
    total_jam   numeric(6,2),
    aktivitas   text not null default 'Mulai Shift',
    created_at  timestamptz not null default now(),
    constraint ck_waktu_kerja_checkout check (check_out is null or check_out >= check_in)
);

-- KUNCI ANTI DOBEL CHECK-IN: satu NIK hanya boleh punya 1 shift yang belum check-out.
-- Dijaga oleh database, jadi aman walau operator klik dua kali / pakai 2 HP.
create unique index if not exists uq_waktu_kerja_shift_aktif
    on public.waktu_kerja (nik) where check_out is null;
create index if not exists ix_waktu_kerja_tanggal on public.waktu_kerja (tanggal);


-- ---------------------------------------------------------------------
-- 3. PROSES (log produksi operator)
-- ---------------------------------------------------------------------

create table if not exists public.proses (
    id                  bigint generated always as identity primary key,
    tanggal             date not null,             -- tanggal WIB saat start
    waktu_kerja_id      bigint references public.waktu_kerja(id) on delete set null,
    nik                 text not null references public.master_karyawan(nik) on update cascade,
    nama                text not null,
    -- snapshot data part saat start (tidak FK ke main_data karena DPMR/REPAIR
    -- bisa memakai part_no yang tidak ada, dan master bisa berubah kemudian)
    part_no             text not null,
    part_name           text,
    model               text,
    line                text,
    urutan_proses       text not null,
    actual_line         text references public.master_line(kode) on update cascade,
    condition           text not null default 'Normal' check (condition in ('Normal', 'Overtime')),
    sec_pcs             numeric(10,2) not null default 0,
    actual_time_start   timestamptz not null,
    actual_time_finish  timestamptz,
    act                 integer not null default 0 check (act >= 0),
    ng                  integer not null default 0 check (ng >= 0),
    persen_prod         numeric(9,2),              -- NULL = N/A (DPMR)
    total_istirahat     integer not null default 0 check (total_istirahat >= 0),  -- menit
    rasio_ng            numeric(9,2),              -- NULL = N/A (DPMR)
    total_jam           numeric(6,2),
    status              text not null default 'START' check (status in ('START', 'FINISH')),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint ck_proses_finish_lengkap check (status = 'START' or actual_time_finish is not null),
    constraint ck_proses_finish_after_start check (actual_time_finish is null or actual_time_finish >= actual_time_start)
);

-- KUNCI ANTI DOBEL START: satu operator hanya boleh punya 1 proses berstatus START.
create unique index if not exists uq_proses_aktif_per_operator
    on public.proses (nik) where status = 'START';
create index if not exists ix_proses_tanggal on public.proses (tanggal);
create index if not exists ix_proses_part_no on public.proses (part_no);
create index if not exists ix_proses_waktu_kerja on public.proses (waktu_kerja_id);

-- updated_at otomatis
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists trg_proses_updated_at on public.proses;
create trigger trg_proses_updated_at
    before update on public.proses
    for each row execute function public.set_updated_at();


-- ---------------------------------------------------------------------
-- 4. ABNORMAL (pencatatan kendala)
-- ---------------------------------------------------------------------

create table if not exists public.abnormal (
    id               bigint generated always as identity primary key,
    client_ref       uuid not null unique default gen_random_uuid(),  -- kunci idempotensi (anti dobel kirim)
    proses_id        bigint references public.proses(id) on delete set null,
    tanggal          date not null,
    jam_input        time not null,                -- jam WIB saat input
    mesin            text,                         -- = actual_line
    part_no          text,
    model            text,
    part_name        text,
    urutan_proses    text,
    operator         text not null,
    nik              text references public.master_karyawan(nik) on update cascade,
    kode_abnormal    text not null references public.master_kode_abnormal(kode) on update cascade,
    uraian_abnormal  text,
    total_waktu      integer not null check (total_waktu > 0),  -- menit
    keterangan       text,
    created_at       timestamptz not null default now()
);
create index if not exists ix_abnormal_tanggal on public.abnormal (tanggal);
create index if not exists ix_abnormal_proses on public.abnormal (proses_id);


-- ---------------------------------------------------------------------
-- 5. DATA AWAL (seed)
-- ---------------------------------------------------------------------

insert into public.master_line (kode) values
    ('BM'), ('CM'), ('DM'), ('ERM'), ('NRM'), ('IRM'), ('KRM')
on conflict (kode) do nothing;

insert into public.master_kode_abnormal (kode, uraian, urutan_tampil) values
    ('A',  'Ganti Proses',                     1),
    ('B',  'Ganti/Tambah Coil',                2),
    ('C',  'Periksa ATA',                      3),
    ('D',  'Trial',                            4),
    ('E',  '2S',                               5),
    ('F',  'Briefing Rutin',                   6),
    ('G1', 'Material NG dan Tukar Proses',     7),
    ('G2', 'Kualitas NG dan Tukar Proses',     8),
    ('H',  'Tooling',                          9),
    ('I',  'Mesin Abnormal',                  10),
    ('K1', 'Penanganan Kualitas NG',          11),
    ('K2', 'Penanganan Dies NG',              12),
    ('L',  'Kekurangan Material',             13),
    ('M',  'Lain-Lain',                       14),
    ('N',  'No KANBAN Plan',                  15),
    ('O',  'DPMR',                            16)
on conflict (kode) do nothing;


-- ---------------------------------------------------------------------
-- 6. VIEW LAPORAN (format mirip sheet lama, jam dalam WIB)
--    Bisa di-export CSV dari Table Editor atau dibaca Looker Studio/Excel.
-- ---------------------------------------------------------------------

create or replace view public.v_laporan_proses with (security_invoker = true) as
select
    p.id,
    p.tanggal                                                         as "Tanggal",
    p.nama                                                            as "Nama",
    p.nik                                                             as "NIK",
    p.part_no                                                         as "Part_No",
    p.part_name                                                       as "Part_Name",
    p.model                                                           as "Model",
    p.line                                                            as "Line",
    p.urutan_proses                                                   as "Urutan_Proses",
    p.actual_line                                                     as "Actual_Line",
    p.condition                                                       as "Condition",
    p.sec_pcs                                                         as "Sec_Pcs",
    to_char(p.actual_time_start  at time zone 'Asia/Jakarta', 'HH24:MI:SS') as "actual_time_start",
    to_char(p.actual_time_finish at time zone 'Asia/Jakarta', 'HH24:MI:SS') as "actual_time_finish",
    p.act                                                             as "ACT",
    p.ng                                                              as "NG",
    case when p.status = 'START' then null
         when p.persen_prod is null then 'N/A'
         else to_char(p.persen_prod, 'FM999990.00') || '%' end        as "%_Prod",
    p.total_istirahat                                                 as "Total Istirahat",
    case when p.status = 'START' then null
         when p.rasio_ng is null then 'N/A'
         else to_char(p.rasio_ng, 'FM999990.00') || '%' end           as "Rasio_NG",
    p.total_jam                                                       as "Total_Jam",
    p.status                                                          as "Status"
from public.proses p
order by p.actual_time_start desc;

create or replace view public.v_laporan_waktu_kerja with (security_invoker = true) as
select
    w.id,
    w.tanggal                                                         as "Tanggal",
    w.nama                                                            as "Nama",
    w.nik                                                             as "NIK",
    to_char(w.check_in  at time zone 'Asia/Jakarta', 'HH24:MI:SS')   as "Check-In",
    to_char(w.check_out at time zone 'Asia/Jakarta', 'HH24:MI:SS')   as "Check-Out",
    w.total_jam                                                       as "Total_Jam",
    w.aktivitas                                                       as "Aktivitas"
from public.waktu_kerja w
order by w.check_in desc;

create or replace view public.v_laporan_abnormal with (security_invoker = true) as
select
    a.id,
    a.tanggal          as "Tanggal",
    a.jam_input        as "Jam_Input",
    a.mesin            as "Mesin",
    a.part_no          as "Part_No",
    a.model            as "Model",
    a.part_name        as "Part_Name",
    a.urutan_proses    as "Urutan_Proses",
    a.operator         as "Operator",
    a.kode_abnormal    as "Kode_Abnormal",
    a.uraian_abnormal  as "Uraian_Abnormal",
    a.total_waktu      as "Total_Waktu",
    a.keterangan       as "Keterangan"
from public.abnormal a
order by a.tanggal desc, a.jam_input desc;


-- ---------------------------------------------------------------------
-- 7. KEAMANAN (Row Level Security)
--    RLS aktif tanpa policy = kunci publik (anon/publishable) TIDAK bisa
--    membaca/menulis apa pun. Aplikasi Streamlit berjalan di server dan
--    memakai SECRET key (atau service_role legacy) dari st.secrets,
--    yang memang melewati RLS. Jangan pernah taruh secret key di kode/GitHub.
-- ---------------------------------------------------------------------

alter table public.master_karyawan      enable row level security;
alter table public.master_line          enable row level security;
alter table public.master_kode_abnormal enable row level security;
alter table public.main_data            enable row level security;
alter table public.waktu_kerja          enable row level security;
alter table public.proses               enable row level security;
alter table public.abnormal             enable row level security;
