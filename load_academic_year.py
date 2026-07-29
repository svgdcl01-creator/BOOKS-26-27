# -*- coding: utf-8 -*-
"""
ஒரு குறிப்பிட்ட academic year-க்கான master_data Excel-ஐ முழுமையாக (fresh)
DB-ல் ஏற்ற இந்த script-ஐ பயன்படுத்தவும்.

migrate_excel_to_db.py-ஐ விட வித்தியாசம்:
  - migrate_excel_to_db.py   → "books" table முழுவதையும் TRUNCATE செய்துவிட்டு
                                ஏற்றும் (வேறு ஆண்டு data இருந்தாலும் எல்லாம் அழிந்துவிடும்)
  - load_academic_year.py    → --year-ல் கொடுத்த ஆண்டுக்கு சொந்தமான rows-ஐ மட்டும்
                                DELETE செய்துவிட்டு, அதே ஆண்டுக்கான Excel-ஐ INSERT
                                செய்யும். வேறு ஆண்டு data தொடப்படாது.

இயக்கும் முறை (இரண்டு ஆண்டுகளையும் தனித்தனியாக run செய்யவும்):
    python load_academic_year.py --excel /path/to/2024_2025.xlsx --year "2024-2025"
    python load_academic_year.py --excel /path/to/2025_2026.xlsx --year "2025-2026"

முதல் முறை DB அமைக்கும்போது மட்டும் --create-users கொடுக்கவும்
(admin/staff கணக்குகள் உருவாக்க). இரண்டாவது ஆண்டை ஏற்றும்போது இது தேவையில்லை.

⚠️ app.py-ல் உள்ள BASE_YEAR = "2024-2025" என்பதை இந்த script-உம் பின்பற்றுகிறது:
   - 2024-2025-க்கு central_number/branch counters *year-suffix இல்லாத* பழைய key
     பயன்படுத்தும் (central_number, branch:<LIBRARIAN_ID>).
   - மற்ற ஆண்டுகளுக்கு (2025-2026, 2026-2027, ...) தனி key
     (central_number:<YEAR>, branch:<LIBRARIAN_ID>:<YEAR>) பயன்படுத்தி, எண்கள்
     1-ல் இருந்து தொடங்கும் — app.py-ன் _counter_key() logic-உடன் இது பொருந்துகிறது.
"""
import argparse
import pandas as pd
from db import DBConn

BASE_YEAR = "2024-2025"

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


def _counter_key(base_key, year):
    """app.py-ன் _counter_key()-உடன் பொருந்தும் அதே logic."""
    if year == BASE_YEAR:
        return base_key
    return f"{base_key}:{year}"


def load_year(excel_path, year):
    print(f"Excel படிக்கிறது: {excel_path}  (academic_year = {year})")
    df = pd.read_excel(excel_path)

    rename_map = {
        'librarianId': 'LIBRARIAN_ID', 'Library Name': 'LIBRARY_NAME',
        'BRANCH NUMBER': 'BRANCH_NUMBER', 'WORK STATUS': 'WORK_STATUS',
        'SENT DETAILS': 'SENT_DETAILS',
    }
    df = df.rename(columns=rename_map, errors='ignore')
    print("Excel-ல் உள்ள columns:", list(df.columns))

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
            year,
        ))

    with DBConn() as (conn, cur):
        # இந்த ஆண்டுக்கு சொந்தமான rows மட்டும் அழி — வேறு ஆண்டு data தொடப்படாது
        cur.execute("DELETE FROM books WHERE academic_year = %s", (year,))
        deleted = cur.rowcount
        print(f"🗑  பழைய {year} rows ({deleted:,}) அழிக்கப்பட்டன (மற்ற ஆண்டுகள் தொடப்படவில்லை).")

        args_str = ",".join(
            cur.mogrify(
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", r
            ).decode("utf-8") for r in rows
        )
        cur.execute(
            "INSERT INTO books (title, price, author, vendor_name, library_type, "
            "library_name_tm, library_name, librarian_id, central_number, branch_number, "
            "set_number, work_status, sent_details, date, state_acc_number, year_pub, accepted_price, "
            "book_id, isbn, publication_name, state_acc_number_1, academic_year) "
            "VALUES " + args_str
        )
    print(f"✅ {len(rows):,} rows ({year}) சேர்க்கப்பட்டன.")


def init_counters(year):
    with DBConn() as (conn, cur):
        # central_number counter
        cur.execute("SELECT MAX(central_number) AS m FROM books WHERE academic_year = %s", (year,))
        current_max = cur.fetchone()["m"]
        if current_max:
            next_central = current_max + 1
        else:
            next_central = DEFAULT_CENTRAL_NUMBER_START if year == BASE_YEAR else 1
        ckey = _counter_key("central_number", year)
        cur.execute(
            "INSERT INTO counters (key, next_value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET next_value = EXCLUDED.next_value",
            (ckey, next_central)
        )
        print(f"   counter '{ckey}' → {next_central}")

        # branch_number counters (library-வாரியாக)
        cur.execute(
            "SELECT librarian_id, MAX(branch_number) AS m FROM books "
            "WHERE librarian_id IS NOT NULL AND academic_year = %s GROUP BY librarian_id",
            (year,)
        )
        existing = {r["librarian_id"]: r["m"] for r in cur.fetchall()}
        all_lib_ids = set(existing) | (set(DEFAULT_LIB_START_NO) if year == BASE_YEAR else set())
        for lib_id in all_lib_ids:
            if existing.get(lib_id):
                nxt = existing[lib_id] + 1
            elif year == BASE_YEAR:
                nxt = DEFAULT_LIB_START_NO.get(lib_id, 1)
            else:
                nxt = 1
            bkey = _counter_key(f"branch:{lib_id}", year)
            cur.execute(
                "INSERT INTO counters (key, next_value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET next_value = EXCLUDED.next_value",
                (bkey, nxt)
            )
    print(f"✅ {year}-க்கான counters initialize ஆனது.")


def create_users():
    from werkzeug.security import generate_password_hash
    print("⚠️  users.py-ல் password மாற்றாமல் இதை run செய்யாதீர்கள் — "
          "கீழே உள்ள placeholder passwords-ஐ முதலில் script-ல் நேரடியாக edit செய்யவும்.")
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
    print("✅ Users உருவாக்கப்பட்டனர்: admin, staff1, staff2")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True, help="அந்த academic year-க்கான master_data Excel path")
    ap.add_argument("--year", required=True, help='academic year, எ.கா. "2024-2025" அல்லது "2025-2026"')
    ap.add_argument("--create-users", action="store_true", help="admin/staff கணக்குகள் உருவாக்க (முதல் run-ல் மட்டும்)")
    args = ap.parse_args()

    year = args.year.strip()
    load_year(args.excel, year)
    init_counters(year)
    if args.create_users:
        create_users()
    print(f"\n🎉 {year} academic year data முழுமையாக ஏற்றப்பட்டது!")
