# -*- coding: utf-8 -*-
"""
ஒரே ஒரு முறை run செய்ய வேண்டிய script:
  book_covers table-ல் ஏற்கனவே சேமிக்கப்பட்டுள்ள (compress செய்யாத, big-size)
  படங்கள் அனைத்தையும் படித்து, சிறிதாக்கி (resize + JPEG compress), அதே
  row-ல் மறுபடியும் update செய்யும். இதனால் Neon storage-ல் கணிசமாக
  இடம் மிச்சமாகும் (எ.கா 142 MB -> சுமார் 15-30 MB, படங்களைப் பொறுத்து).

  தேவை: requirements.txt-ல் Pillow சேர்க்கப்பட்டிருக்கணும்
        (pip install -r requirements.txt)

இயக்கும் முறை:
    python compress_existing_covers.py

    --dry-run கொடுத்தால், எதுவும் update செய்யாமல் எவ்வளவு
    மிச்சமாகும் என்று மட்டும் காட்டும்:
    python compress_existing_covers.py --dry-run
"""
import argparse
from io import BytesIO

import psycopg2.extras
from PIL import Image

from db import DBConn

MAX_DIMENSION = 800
QUALITY = 72


def compress(image_bytes, max_dimension=MAX_DIMENSION, quality=QUALITY):
    img = Image.open(BytesIO(image_bytes))
    img = img.convert("RGB")
    img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    out = BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def main(dry_run=False):
    with DBConn() as (conn, cur):
        cur.execute("SELECT book_id, image FROM book_covers ORDER BY book_id")
        rows = cur.fetchall()

    print(f"மொத்தம் {len(rows)} book cover படங்கள் கிடைத்தன.\n")

    total_before = 0
    total_after = 0
    updates = []

    for row in rows:
        book_id = row["book_id"]
        original = bytes(row["image"])
        before_size = len(original)
        try:
            compressed = compress(original)
        except Exception as e:
            print(f"  [தவிர்க்கப்பட்டது] {book_id}: படத்தை படிக்க முடியவில்லை ({e})")
            continue
        after_size = len(compressed)
        total_before += before_size
        total_after += after_size
        updates.append((book_id, compressed))
        print(f"  {book_id}: {before_size/1024:.0f} KB -> {after_size/1024:.0f} KB")

    print(f"\nமொத்தம்: {total_before/1024/1024:.1f} MB -> {total_after/1024/1024:.1f} MB")
    saved = total_before - total_after
    print(f"மிச்சமாகும் இடம்: {saved/1024/1024:.1f} MB\n")

    if dry_run:
        print("(--dry-run என்பதால் DB-ல் எதுவும் மாற்றப்படவில்லை)")
        return

    with DBConn() as (conn, cur):
        for book_id, compressed in updates:
            cur.execute(
                "UPDATE book_covers SET image = %s, content_type = 'image/jpeg' WHERE book_id = %s",
                (psycopg2.Binary(compressed), book_id)
            )

    print(f"{len(updates)} படங்கள் DB-ல் compress செய்யப்பட்டு update ஆயின.")
    print("\nகுறிப்பு: Postgres-ல் row update ஆனாலும், பழைய dead-space உடனே")
    print("physically குறையாது. Neon dashboard-ல் storage உடனே குறையாவிட்டால்")
    print("சில மணி நேரம் காத்திருக்கவும் (Neon auto-vacuum பண்ணும்), அல்லது")
    print("Neon SQL Editor-ல் இதை ஒரு முறை run செய்யவும்: VACUUM FULL book_covers;")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="update செய்யாமல் preview மட்டும் காட்டும்")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
