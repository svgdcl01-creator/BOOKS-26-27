# -*- coding: utf-8 -*-
"""
ஒரே ஒரு முறை run செய்ய வேண்டிய script:
  1. உங்கள் தற்போதைய master_data.xlsx-ஐ Postgres 'books' table-க்கு copy செய்யும்
  2. central_number / branch_number counters-ஐ சரியாக initialize செய்யும்
  3. Admin + 2 Staff accounts உருவாக்கும்

இயக்கும் முறை:
    python migrate_excel_to_db.py --excel /path/to/master_data.xlsx
"""
import argparse
import os
import pandas as pd
from werkzeug.security import generate_password_hash
from db import DBConn

DEFAULT_LIB_START_NO = {
    "TNDPL00765": 172914, "TNDPL00766": 27264, "TNDPL00767": 48060,
    "TNDPL00768": 38088, "TNDPL00769": 39466, "TNDPL00770": 33286,
    "TNDPL00771": 61381, "TNDPL00772": 33786, "TNDPL00773": 57067,
    "TNDPL00774": 50176, "TNDPL00775": 43555, "TNDPL00776": 44538,
    "TNDPL00777": 41463, "TNDPL00778": 57798, "TNDPL00779": 37000,
    "TNDPL00780": 20610, "TNDPL00781": 21058, "TNDPL00782": 26706,
    "TNDPL00783": 31031, "TNDPL00784": 24050, "TNDPL00785": 23742,
    "TNDPL00786": 21041, "TNDPL00787": 26021, "TNDPL00788": 30832,
    "TNDPL00789": 20080, "TNDPL00790": 29316, "TNDPL00791": 28979,
    "TNDPL00792": 27527, "TNDPL00793": 21462, "TNDPL00794": 26051,
    "TNDPL00795": 25021, "TNDPL00796": 32476, "TNDPL00797": 18092,
    "TNDPL00798": 29222, "TNDPL00799": 30803, "TNDPL00800": 24513,
    "TNDPL00801": 21742, "TNDPL00802": 27820, "TNDPL00803": 24165,
    "TNDPL00804": 33691, "TNDPL00805": 26867, "TNDPL00806": 24143,
    "TNDPL00807": 28491, "TNDPL00808": 30445, "TNDPL00809": 30379,
    "TNDPL00810": 20139, "TNDPL00811": 23168, "TNDPL00812": 23223,
    "TNDPL00813": 32804, "TNDPL00814": 33014, "TNDPL00815": 27366,
    "TNDPL00816": 33436, "TNDPL00817": 26493, "TNDPL00818": 19120,
    "TNDPL00819": 14494, "TNDPL00820": 13518, "TNDPL00821": 14762,
    "TNDPL00822": 16808, "TNDPL00823": 16592, "TNDPL00824": 14902,
    "TNDPL00825": 15231, "TNDPL00826": 19227, "TNDPL00827": 20760,
    "TNDPL00828": 14457, "TNDPL00829": 16934, "TNDPL00830": 8955,
    "TNDPL00831": 10412, "TNDPL00832": 9060, "TNDPL00833": 10371,
    "TNDPL00834": 10277, "TNDPL00835": 8404, "TNDPL00836": 11231,
    "TNDPL00837": 10680, "TNDPL00838": 12985, "TNDPL00839": 13154,
    "TNDPL00840": 5243, "TNDPL00841": 11553, "TNDPL00842": 12842,
    "TNDPL00843": 8832, "TNDPL00844": 9731, "TNDPL00845": 11386,
    "TNDPL00846": 8564, "TNDPL00847": 12647, "TNDPL00848": 10501,
    "TNDPL00849": 6364, "TNDPL00850": 5641, "TNDPL00851": 14798,
    "TNDPL00852": 10458, "TNDPL00853": 11604, "TNDPL00854": 13499,
    "TNDPL00855": 13772, "TNDPL00856": 13629, "TNDPL00857": 12459,
    "TNDPL00858": 11870, "TNDPL00859": 10760, "TNDPL00860": 13416,
    "TNDPL00861": 13072, "TNDPL00862": 9805, "TNDPL00863": 12053,
    "TNDPL00864": 8267, "TNDPL00865": 9521, "TNDPL00866": 9011,
    "TNDPL00867": 6300, "TNDPL00868": 10846, "TNDPL00869": 11285,
    "TNDPL00870": 10725, "TNDPL00871": 6274, "TNDPL00872": 9727,
    "TNDPL00873": 10174, "TNDPL00874": 9224, "TNDPL00875": 9849,
    "TNDPL00876": 9460, "TNDPL00877": 8819, "TNDPL00878": 8445,
    "TNDPL00879": 7805, "TNDPL00880": 12345, "TNDPL00881": 4350,
    "TNDPL00882": 9046, "TNDPL00883": 18389, "TNDPL00884": 5151,
    "TNDPL00885": 6055, "TNDPL00886": 9926, "TNDPL00887": 9531,
    "TNDPL00888": 10664, "TNDPL00889": 8823, "TNDPL00890": 5639,
    "TNDPL00891": 12155, "TNDPL00892": 12491, "TNDPL00893": 13328,
    "TNDPL00894": 11418, "TNDPL00895": 13314, "TNDPL00896": 9583,
    "TNDPL00897": 14873, "TNDPL00898": 10357, "TNDPL00899": 11171,
    "TNDPL00900": 16881, "TNDPL00901": 14549, "TNDPL00902": 9297,
    "TNDPL00903": 12976, "TNDPL00904": 10835, "TNDPL00905": 11794,
    "TNDPL00906": 5113, "TNDPL00907": 2572, "TNDPL00908": 10048,
    "TNDPL00909": 11904, "TNDPL00910": 3685, "TNDPL00911": 9268,
    "TNDPL00912": 8432, "TNDPL00913": 7295, "TNDPL00914": 3959,
    "TNDPL00915": 4198, "TNDPL00916": 3658, "TNDPL00917": 1883
}
DEFAULT_CENTRAL_NUMBER_START = 425335


def migrate_books(excel_path):
    print(f"Excel படிக்கிறது: {excel_path}")
    df = pd.read_excel(excel_path)

    rename_map = {
        'librarianId': 'LIBRARIAN_ID', 'Library Name': 'LIBRARY_NAME',
        'BRANCH NUMBER': 'BRANCH_NUMBER', 'WORK STATUS': 'WORK_STATUS',
        'SENT DETAILS': 'SENT_DETAILS',
    }
    df = df.rename(columns=rename_map, errors='ignore')

    col_map = {
        'title': 'TITLE', 'price': 'PRICE', 'author': 'AUTHOR',
        'vendor_name': 'VENDOR_NAME', 'library_type': 'LIBRARY_TYPE',
        'library_name_tm': 'LIBRARY_NAME_TM', 'library_name': 'LIBRARY_NAME',
        'librarian_id': 'LIBRARIAN_ID', 'central_number': 'CENTRAL_NUMBER',
        'branch_number': 'BRANCH_NUMBER', 'set_number': 'SET_NUMBER',
        'work_status': 'WORK_STATUS', 'sent_details': 'SENT_DETAILS',
        'date': 'DATE',
    }

    def col(df, name, default=None):
        return df[name] if name in df.columns else pd.Series([default] * len(df))

    rows = []
    for i in range(len(df)):
        row = df.iloc[i]
        def val(colname):
            v = row.get(colname)
            if pd.isna(v):
                return None
            return str(v).strip()
        def intval(colname):
            v = row.get(colname)
            try:
                if pd.isna(v):
                    return None
                return int(float(v))
            except Exception:
                return None
        rows.append((
            val('TITLE'), val('PRICE'), val('AUTHOR'), val('VENDOR_NAME'),
            val('LIBRARY_TYPE'), val('LIBRARY_NAME_TM'), val('LIBRARY_NAME'),
            val('LIBRARIAN_ID'), intval('CENTRAL_NUMBER'), intval('BRANCH_NUMBER'),
            val('SET_NUMBER'), val('WORK_STATUS'), val('SENT_DETAILS'), val('DATE'),
            val('STATE ACCESSION NUMBER') or val('STATE_ACC') or val('STATE ACC'),
            val('YEAR_PUB') or val('YEAR OF PUBLICATION') or val('Year of Publication'),
            val('ACCEPTED_PRICE') or val('ACCEPTED PRICE') or val('Accepted Price'),
            val('BOOK_ID'), val('Isbn') or val('ISBN'),
            val('Publication Name') or val('PUBLICATION_NAME'),
            val('STATE ACCESSIONNUMBER.1') or val('STATE ACCESSION NUMBER.1'),
        ))

    print(f"{len(rows):,} rows insert செய்கிறது...")
    with DBConn() as (conn, cur):
        # ஏற்கனவே data இருந்தால் காலி செய் (idempotent re-run)
        cur.execute("TRUNCATE books RESTART IDENTITY;")
        args_str = ",".join(
            cur.mogrify(
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", r
            ).decode("utf-8") for r in rows
        )
        cur.execute(
            "INSERT INTO books (title, price, author, vendor_name, library_type, "
            "library_name_tm, library_name, librarian_id, central_number, branch_number, "
            "set_number, work_status, sent_details, date, state_acc_number, year_pub, accepted_price, "
            "book_id, isbn, publication_name, state_acc_number_1) "
            "VALUES " + args_str
        )
    print("✅ books table migration முடிந்தது.")


def init_counters():
    with DBConn() as (conn, cur):
        cur.execute("SELECT MAX(central_number) AS m FROM books;")
        current_max = cur.fetchone()["m"]
        next_central = (current_max + 1) if current_max else DEFAULT_CENTRAL_NUMBER_START
        cur.execute(
            "INSERT INTO counters (key, next_value) VALUES ('central_number', %s) "
            "ON CONFLICT (key) DO UPDATE SET next_value = EXCLUDED.next_value",
            (next_central,)
        )

        cur.execute(
            "SELECT librarian_id, MAX(branch_number) AS m FROM books "
            "WHERE librarian_id IS NOT NULL GROUP BY librarian_id;"
        )
        existing = {r["librarian_id"]: r["m"] for r in cur.fetchall()}
        all_lib_ids = set(existing) | set(DEFAULT_LIB_START_NO)
        for lib_id in all_lib_ids:
            if existing.get(lib_id):
                nxt = existing[lib_id] + 1
            else:
                nxt = DEFAULT_LIB_START_NO.get(lib_id, 1)
            cur.execute(
                "INSERT INTO counters (key, next_value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET next_value = EXCLUDED.next_value",
                (f"branch:{lib_id}", nxt)
            )
    print("✅ counters initialize ஆனது.")


def create_users():
    """
    முதல் run-ல் மட்டும் இதை uncomment செய்து password மாற்றி இயக்கவும்.
    பிறகு பாதுகாப்புக்காக இந்த function-ஐ comment செய்யவும் (password hash மட்டும்
    DB-ல் இருக்கும், plaintext எங்குமே save ஆகாது).
    """
    users = [
        ("admin",  "இங்கே-உங்கள்-admin-password",  "admin"),
        ("staff1", "இங்கே-staff1-password",        "staff"),
        ("staff2", "இங்கே-staff2-password",        "staff"),
    ]
    with DBConn() as (conn, cur):
        for username, password, role in users:
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s) "
                "ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash, role=EXCLUDED.role",
                (username, generate_password_hash(password), role)
            )
    print("✅ Users உருவாக்கப்பட்டனர்: admin, staff1, staff2 (passwords-ஐ இப்போதே மாற்றிக்கொள்ளுங்கள்!)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True, help="master_data.xlsx path")
    ap.add_argument("--skip-users", action="store_true", help="users creation skip செய்ய")
    args = ap.parse_args()

    migrate_books(args.excel)
    init_counters()
    if not args.skip_users:
        create_users()
    print("\n🎉 Migration முழுவதும் முடிந்தது!")
