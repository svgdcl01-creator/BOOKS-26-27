-- ==========================================================
-- BOOKPURCHASE — PostgreSQL Schema
-- master_data.xlsx -> books table (ஒவ்வொரு புத்தக பிரதிக்கும் ஒரு row)
-- ==========================================================

CREATE TABLE IF NOT EXISTS books (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT,
    price           TEXT,
    author          TEXT,
    vendor_name     TEXT,
    library_type    TEXT,
    library_name_tm TEXT,
    library_name    TEXT,
    librarian_id    TEXT,
    central_number  INTEGER,
    branch_number   INTEGER,
    set_number      TEXT,
    work_status     TEXT,     -- assign செய்த தேதி (dd/mm/yyyy)
    sent_details    TEXT,     -- 'sent' / NULL
    date            TEXT,     -- அனுப்பிய தேதி
    state_acc_number TEXT,    -- மாநிலப் பதிவெண் (Report 5/7-க்கு)
    year_pub        TEXT,     -- பதிப்பு ஆண்டு
    accepted_price  TEXT,     -- ஏற்பு விலை
    locked_by       TEXT,     -- staff username, temporary assign-lock
    locked_at       TIMESTAMPTZ
);

-- ==========================================================
-- ஏற்கனவே schema.sql run செய்திருந்தால், இந்த ALTER வரிகளை மட்டும் Run செய்யவும்
-- (இது Report 5/7-க்கு தேவையான புதிய columns சேர்க்கும், data-வை தொடாது)
-- ==========================================================
ALTER TABLE books ADD COLUMN IF NOT EXISTS state_acc_number TEXT;
ALTER TABLE books ADD COLUMN IF NOT EXISTS year_pub TEXT;
ALTER TABLE books ADD COLUMN IF NOT EXISTS accepted_price TEXT;
CREATE INDEX IF NOT EXISTS idx_books_title       ON books (title);
CREATE INDEX IF NOT EXISTS idx_books_title_price ON books (title, price);
CREATE INDEX IF NOT EXISTS idx_books_unassigned  ON books (set_number) WHERE set_number IS NULL OR set_number = '';
CREATE INDEX IF NOT EXISTS idx_books_librarian   ON books (librarian_id);
CREATE INDEX IF NOT EXISTS idx_books_set_number  ON books (set_number);

-- ==========================================================
-- master_data.xlsx-ல் இருந்த மேலும் சில columns — பிரிக்க/அனுப்ப வேலைக்கு
-- பயன்படாது, ஆனாலும் Admin Excel Download-ல் master_data.xlsx-ன் அதே
-- format முழுமையாக கிடைக்க இங்கே சேமிக்கப்படுகிறது (பிற்கால தேவைக்கு)
-- ==========================================================
ALTER TABLE books ADD COLUMN IF NOT EXISTS book_id TEXT;              -- BOOK_ID
ALTER TABLE books ADD COLUMN IF NOT EXISTS isbn TEXT;                 -- Isbn
ALTER TABLE books ADD COLUMN IF NOT EXISTS publication_name TEXT;     -- Publication Name
ALTER TABLE books ADD COLUMN IF NOT EXISTS state_acc_number_1 TEXT;   -- STATE ACCESSIONNUMBER.1 (testing-க்காக காலியாக அப்லோட் செய்யப்பட்டது)

-- ==========================================================
-- 2024-2025 / 2025-2026 — இரண்டு ஆண்டு தரவுகளையும் ஒரே table-ல்
-- வேறுபடுத்தி காட்ட. இருக்கும் 78,000 rows எல்லாம் 2024-2025-க்கு
-- சொந்தமானவை என்பதால், இந்த UPDATE ஒரே முறை (deploy செய்த பின்) run செய்யவும்:
--     ALTER TABLE books ADD COLUMN IF NOT EXISTS academic_year TEXT;
--     UPDATE books SET academic_year = '2024-2025' WHERE academic_year IS NULL;
-- ==========================================================
ALTER TABLE books ADD COLUMN IF NOT EXISTS academic_year TEXT;
CREATE INDEX IF NOT EXISTS idx_books_academic_year ON books (academic_year);

-- ==========================================================
-- Atomic counters — central number மற்றும் library-வாரியான branch number
-- assign நேரத்தில் race condition/duplicate வராமல் இருக்க
-- ==========================================================
CREATE TABLE IF NOT EXISTS counters (
    key         TEXT PRIMARY KEY,   -- 'central_number' அல்லது 'branch:<LIBRARIAN_ID>'
    next_value  INTEGER NOT NULL
);

-- ==========================================================
-- Settings (district name, lib start numbers) — JSON files-க்கு பதிலாக
-- ==========================================================
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ==========================================================
-- Users — Admin (நீங்கள்) + 2 Staff members
-- ==========================================================
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'staff'))
);

-- ==========================================================
-- Generated Reports — அறிக்கைகள் HTML ஆக உருவாக்கப்பட்டு இங்கே
-- தற்காலிகமாக சேமிக்கப்படும் (browser new-tab-ல் திறக்க)
-- ==========================================================
CREATE TABLE IF NOT EXISTS generated_reports (
    id          BIGSERIAL PRIMARY KEY,
    title       TEXT,
    html        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- ==========================================================
-- Backups metadata (renumber/restore செய்யும்முன் snapshot)
-- ==========================================================
CREATE TABLE IF NOT EXISTS backups (
    id          BIGSERIAL PRIMARY KEY,
    filename    TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    data        JSONB NOT NULL   -- affected rows-ன் snapshot (renumber/restore-க்கு)
);

-- ==========================================================
-- "தவறான பதிவு நீக்கம்" (Reclaim) — தவறாக பிரிக்க/அனுப்ப செய்த புத்தகங்களை
-- மீண்டும் unassigned நிலைக்கு கொண்டுவரும்போது, விடுவிக்கப்படும்
-- central/branch எண்கள் இங்கே "pool"-ஆக சேமிக்கப்பட்டு, அடுத்த Assign
-- நேரத்தில் மீண்டும் பயன்படுத்த வழங்கப்படும்.
-- ==========================================================
CREATE TABLE IF NOT EXISTS reclaimed_central (
    central_number  INTEGER PRIMARY KEY,
    reclaimed_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reclaimed_branch (
    id             BIGSERIAL PRIMARY KEY,
    librarian_id   TEXT NOT NULL,
    branch_number  INTEGER NOT NULL,
    reclaimed_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (librarian_id, branch_number)
);
CREATE INDEX IF NOT EXISTS idx_reclaimed_branch_lib ON reclaimed_branch (librarian_id);

-- ==========================================================
-- 2025-2026 முதல் ஒவ்வொரு ஆண்டும் central/branch எண் 1-ல் இருந்து
-- மீண்டும் தொடங்குவதால், reclaim pool-ல் ஆண்டு சேர்க்க வேண்டும் —
-- இல்லையெனில் "central_number=1" 2024-25 மற்றும் 2025-26 இரண்டிலும்
-- reclaim ஆனால் PK conflict வரும். ஒரே முறை (deploy செய்த பின்) இதை run செய்யவும்:
-- ==========================================================
ALTER TABLE reclaimed_central ADD COLUMN IF NOT EXISTS academic_year TEXT;
UPDATE reclaimed_central SET academic_year = '2024-2025' WHERE academic_year IS NULL;
ALTER TABLE reclaimed_central DROP CONSTRAINT IF EXISTS reclaimed_central_pkey;
ALTER TABLE reclaimed_central DROP CONSTRAINT IF EXISTS reclaimed_central_year_num_key;
ALTER TABLE reclaimed_central ADD CONSTRAINT reclaimed_central_year_num_key UNIQUE (academic_year, central_number);

ALTER TABLE reclaimed_branch ADD COLUMN IF NOT EXISTS academic_year TEXT;
UPDATE reclaimed_branch SET academic_year = '2024-2025' WHERE academic_year IS NULL;
ALTER TABLE reclaimed_branch DROP CONSTRAINT IF EXISTS reclaimed_branch_librarian_id_branch_number_key;
ALTER TABLE reclaimed_branch DROP CONSTRAINT IF EXISTS reclaimed_branch_year_key;
ALTER TABLE reclaimed_branch ADD CONSTRAINT reclaimed_branch_year_key UNIQUE (academic_year, librarian_id, branch_number);
