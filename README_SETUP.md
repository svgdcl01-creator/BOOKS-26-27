# BOOKPURCHASE — Online பதிப்பு: Setup வழிமுறை

## இந்த கட்டத்தில் தயார் ஆனவை
- Login (Admin + 2 Staff)
- Search, Book Detail, Libraries-for-type
- **Assign** — 2 staff ஒரே நேரத்தில் வேலை செய்தாலும் duplicate ஆகாது

## அடுத்த கட்டத்தில் வரும் (இன்னும் migrate ஆகவில்லை)
Renumber, Backup/Restore, Reports 1-7, Send/Mark sent — இவை Admin-only routes,
இதை உறுதி செய்தபின் அடுத்து சேர்க்கிறேன்.

---

## படி 1: Database உருவாக்கு (Neon.tech — Free)

1. https://neon.tech போய் Sign up செய்யவும் (Google/GitHub login போதும்)
2. "Create a project" → பெயர்: `bookpurchase`
3. Dashboard-ல் **Connection String** copy செய்யவும் — இது இப்படி இருக்கும்:
   `postgresql://user:pass@ep-xxxx.neon.tech/neondb?sslmode=require`
4. Neon-ன் **SQL Editor**-ல் `schema.sql` கோப்பின் content-ஐ முழுவதும் paste செய்து Run செய்யவும்
   (இது books, counters, settings, users, backups tables உருவாக்கும்)

## படி 2: Local-ல் Migration இயக்கு (உங்கள் கணினியில் ஒரே ஒரு முறை)

```bash
cd webapp
pip install -r requirements.txt

# Terminal/CMD-ல்:
set DATABASE_URL=postgresql://user:pass@ep-xxxx.neon.tech/neondb     (Windows)
export DATABASE_URL=postgresql://user:pass@ep-xxxx.neon.tech/neondb  (Mac/Linux)

python migrate_excel_to_db.py --excel "C:\path\to\master_data.xlsx"
```

⚠️ **இயக்கும் முன்:**
- `migrate_excel_to_db.py`-ல் உள்ள `DEFAULT_LIB_START_NO` dictionary-ல் உங்கள்
  main.py-ல் இருந்த **அனைத்து 917 library entries**-ஐயும் copy-paste செய்யவும்
  (நான் இங்கே சுருக்கமாக 3 மட்டும் வைத்திருக்கிறேன்)
- `create_users()` function-ல் Admin/Staff-1/Staff-2 passwords-ஐ மாற்றவும்

## படி 3: Server Deploy செய் (Render.com — Free)

1. https://render.com Sign up செய்யவும்
2. இந்த `webapp` folder-ஐ ஒரு **GitHub repository**-ல் upload செய்யவும்
   (GitHub Desktop app எளிதாக இருக்கும் — கோப்புகளை drag செய்தால் போதும்)
3. Render Dashboard → "New" → "Web Service" → உங்கள் GitHub repo select செய்
4. அமைப்புகள்:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Environment Variables:**
     - `DATABASE_URL` = (Neon connection string)
     - `SECRET_KEY` = (ஏதேனும் random 32-character string)
5. "Create Web Service" — சில நிமிடங்களில் ஒரு public URL கிடைக்கும்
   (எ.கா. `https://bookpurchase.onrender.com`)
6. அந்த URL-ஐ Staff 1, Staff 2-க்கும் அனுப்பலாம் — அவர்கள் phone/laptop எதிலிருந்தும் login செய்யலாம்

## படி 4: சோதனை

- 3 பேரும் வெவ்வேறு devices-ல் login செய்யவும்
- ஒரே title/price/library-ஐ 2 staff ஒரே நேரத்தில் assign செய்ய முயற்சி செய்யவும் —
  ஒருவருக்கு success, மற்றவருக்கு "ஏற்கனவே assign ஆகியிருக்கலாம்" error வர வேண்டும்
  (இதுவே duplicate-proof வேலை செய்கிறது என்பதற்கான confirmation)

---

## கவனிக்க வேண்டியவை
- Render free tier சில நிமிடம் idle ஆனால் "sleep" ஆகும் — முதல் request-ல் 30 வினாடி
  தாமதம் இருக்கலாம். இது பிரச்சனை என்றால் paid tier (~$7/மாதம்) மேம்படும்.
- Neon free tier 0.5 GB storage தருகிறது — 78,000 rows-க்கு இது நிறைய போதும்.
