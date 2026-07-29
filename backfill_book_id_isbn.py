# -*- coding: utf-8 -*-
"""
இருக்கும் books rows-ஐ TRUNCATE செய்யாமல் (assign/send work அழியாமல்),
BOOK_ID / Isbn / Publication Name / STATE ACCESSIONNUMBER.1 மதிப்புகளை
மட்டும் UPDATE செய்யும் script.

STATE ACCESSION NUMBER (state_acc_number) unique key-ஆக பயன்படுத்தி
match செய்யப்படுகிறது.

⚠️ இதை master_data.xlsx (முதலில் migrate செய்த file) மற்றும் பிறகு
   Append new batch.py மூலம் சேர்த்த batch file(கள்) — இரண்டையும் இதே script-ஐ
   ஒவ்வொரு file-க்கும் ஒருமுறை run செய்யவும், எல்லா rows-உம் நிரம்ப.

இயக்கும் முறை:
    python backfill_book_id_isbn.py --excel /path/to/master_data.xlsx
"""
import argparse
import pandas as pd
from db import DBConn


def backfill(excel_path):
    print(f"Excel படிக்கிறது: {excel_path}")
    df = pd.read_excel(excel_path)
    print("Excel-ல் உள்ள columns:", list(df.columns))

    def val(row, colname):
        v = row.get(colname)
        if pd.isna(v):
            return None
        return str(v).strip()

    updates = []
    for i in range(len(df)):
        row = df.iloc[i]
        state_acc = val(row, 'STATE ACCESSION NUMBER') or val(row, 'STATE_ACC') or val(row, 'STATE ACC')
        if not state_acc:
            continue
        updates.append((
            val(row, 'BOOK_ID'),
            val(row, 'Isbn') or val(row, 'ISBN'),
            val(row, 'Publication Name') or val(row, 'PUBLICATION_NAME'),
            val(row, 'STATE ACCESSIONNUMBER.1') or val(row, 'STATE ACCESSION NUMBER.1'),
            state_acc,
        ))

    print(f"{len(updates):,} rows update செய்கிறது (state_acc_number match மூலம்)...")
    matched = 0
    with DBConn() as (conn, cur):
        for book_id, isbn, pub_name, state_acc_1, state_acc in updates:
            cur.execute(
                "UPDATE books SET book_id=%s, isbn=%s, publication_name=%s, state_acc_number_1=%s "
                "WHERE state_acc_number=%s",
                (book_id, isbn, pub_name, state_acc_1, state_acc)
            )
            matched += cur.rowcount

    print(f"✅ {matched:,} rows-ல் BOOK_ID/Isbn/Publication Name நிரப்பப்பட்டது.")
    if matched < len(updates):
        print(f"⚠️ {len(updates) - matched:,} rows match ஆகவில்லை "
              f"(அந்த STATE ACCESSION NUMBER-கள் DB-ல் இல்லை போலும்).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True, help="master_data.xlsx அல்லது batch xlsx path")
    args = ap.parse_args()
    backfill(args.excel)
    print("\n🎉 Backfill முடிந்தது!")
