# -*- coding: utf-8 -*-
"""
புதிய Book Purchase batch-ஐ (எ.கா. 5000 புதிய rows) இருக்கும் data-வை
அழிக்காமல் Database-ல் ADD செய்ய இந்த script-ஐ பயன்படுத்தவும்.

migrate_excel_to_db.py-ஐ விட வித்தியாசம்:
  - migrate_excel_to_db.py  → table-ஐ காலி செய்துவிட்டு புதிதாக load செய்யும் (முதல் முறை மட்டும்)
  - append_new_batch.py     → இருக்கும் rows-ஐ தொடாமல், புதிய rows-ஐ மட்டும் சேர்க்கும்

இயக்கும் முறை:
    py append_new_batch.py --excel "C:\\path\\to\\new_batch.xlsx"

⚠️ கவனிக்க: --excel-ல் கொடுக்கும் Excel கோப்பில் **புதிய rows மட்டும்** இருக்க வேண்டும்
   (பழைய 4700 rows மீண்டும் இருக்கக்கூடாது, இல்லையெனில் duplicate ஆகிவிடும்)
"""
import argparse
import pandas as pd
from db import DBConn


def append_books(excel_path):
    print(f"Excel படிக்கிறது: {excel_path}")
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
        ))

    print(f"{len(rows):,} புதிய rows சேர்க்கிறது (இருக்கும் data தொடப்படாது)...")
    with DBConn() as (conn, cur):
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
        cur.execute("SELECT COUNT(*) AS c FROM books")
        total_now = cur.fetchone()["c"]

    print(f"✅ {len(rows):,} rows சேர்க்கப்பட்டன. Database-ல் இப்போது மொத்தம்: {total_now:,} rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True, help="புதிய batch Excel file path")
    args = ap.parse_args()
    append_books(args.excel)
    print("\n🎉 புதிய batch சேர்க்கப்பட்டது! (central_number/branch_number counters தானாகவே தொடரும்)")
