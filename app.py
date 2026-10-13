# -*- coding: utf-8 -*-
"""
BOOKPURCHASE — Online (Multi-user) பதிப்பு
Original main.py-ன் Excel/pandas logic-ஐ PostgreSQL-க்கு migrate செய்யப்பட்டது.

இந்த கட்டத்தில் தயார்: Login, Search, Book Detail, Assign (duplicate-proof).
அடுத்த கட்டம்: Renumber, Backup/Restore, Reports 1-7, Send/Mark (Admin routes).
"""
import os
import re
import time
import threading
import tempfile
import uuid
import itertools
from urllib.parse import quote
from collections import defaultdict
from datetime import datetime
from io import BytesIO
import pandas as pd
import psycopg2.extras
from PIL import Image as PILImage
from flask import Flask, request, jsonify, session, redirect, make_response, send_file
from werkzeug.security import generate_password_hash, check_password_hash

from db import DBConn
from auth import login_required, admin_required, staff_or_admin_required, verify_login

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DISTRICT_NAME = "சிவகங்கை"
REPORT_COMMON_HEAD = """
@page{size:Letter portrait;margin:18mm 15mm 18mm 15mm;}
body{font-family:'Nirmala UI','Noto Sans Tamil',Arial,sans-serif;font-size:12pt;color:#000;margin:0;}
.rt{text-align:center;margin-bottom:6px;}
.rt p{margin:2px 0;}
.t1{font-size:14pt;font-weight:bold;}
.t2{font-size:13pt;font-weight:bold;}
.t3{font-size:12pt;font-weight:bold;}
.t4{font-size:12pt;}
.t5{font-size:11pt;}
table{width:100%;border-collapse:collapse;margin-top:14px;margin-bottom:10px;}
th,td{border:1.5px solid #000;padding:6px 8px;text-align:center;font-size:10.5pt;}
th{background:#e0e0e0;font-weight:bold;}
.sig{margin-top:40px;text-align:right;font-size:11pt;line-height:1.8;}
.section-title{font-size:11pt;font-weight:700;margin:12px 0 4px;}
"""

with open(os.path.join(BASE_DIR, "main_html_content.html"), encoding="utf-8") as f:
    MAIN_HTML = f.read()
with open(os.path.join(BASE_DIR, "app_js_content.js"), encoding="utf-8") as f:
    APP_JS = f.read()
with open(os.path.join(BASE_DIR, "librarian_html_content.html"), encoding="utf-8") as f:
    LIBRARIAN_HTML = f.read()

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ta"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>உள்நுழைவு — BOOKPURCHASE</title>
<style>
  body{font-family:'Noto Sans Tamil',sans-serif;background:#0b3d3d;display:flex;
       align-items:center;justify-content:center;min-height:100vh;margin:0;padding:16px;box-sizing:border-box;}
  .box{background:white;padding:44px 34px;border-radius:18px;box-shadow:0 20px 60px rgba(0,0,0,.3);
       width:100%;max-width:400px;box-sizing:border-box;}
  h2{color:#0b3d3d;margin-top:0;text-align:center;font-size:1.5rem;line-height:1.4;}
  label{display:block;font-size:15px;font-weight:600;color:#0b3d3d;margin:16px 0 7px;}
  select, input{width:100%;padding:14px;border:1px solid #ccc;border-radius:10px;
        font-size:1.05rem;box-sizing:border-box;font-family:'Noto Sans Tamil',sans-serif;}
  button{width:100%;padding:15px;background:#0b3d3d;color:white;border:none;
         border-radius:10px;font-size:1.1rem;font-weight:600;cursor:pointer;margin-top:20px;}
  .err{color:#c0392b;text-align:center;margin-top:10px;font-size:.95rem;}
  #pwdField{display:none;}
  @media (max-width:480px){
    .box{max-width:94vw;padding:36px 24px;}
    h2{font-size:1.35rem;}
    label{font-size:14px;}
    select, input{font-size:1.15rem;padding:15px;}
    button{font-size:1.15rem;padding:16px;}
  }
</style></head>
<body>
<div class="box">
  <h2>📚 மாவட்ட நூலக ஆணைக்குழு, சிவகங்கை</h2>
  <form method="POST" action="/login">
    <label>பயனர் வகை (User)</label>
    <select name="username" id="userSelect" required onchange="togglePwd()">
      <option value="" disabled selected>தேர்ந்தெடுக்கவும்</option>
      <option value="admin">1. Admin</option>
      <option value="dclstaff">2. DCL Staff</option>
      <option value="librarian">3. Librarian</option>
    </select>
    <div id="pwdField">
      <label>Password</label>
      <input type="password" name="password" id="pwdInput" placeholder="Password">
    </div>
    <button type="submit">உள்நுழை</button>
  </form>
  {error}
</div>
<script>
function togglePwd(){
  var v = document.getElementById('userSelect').value;
  var box = document.getElementById('pwdField');
  var inp = document.getElementById('pwdInput');
  if(v === 'librarian'){
    box.style.display = 'none';
    inp.removeAttribute('required');
    inp.value = '';
  } else {
    box.style.display = 'block';
    inp.setAttribute('required', 'required');
  }
}
</script>
</body></html>
"""

# Login-க்கு fixed 3 accounts — role dropdown-க்கு ஒத்துப்போகும்படி.
# Password-கள் "settings" table-ல் (hash ஆக) சேமிக்கப்படும் — Admin
# dashboard-ல் இருந்தே மாற்றலாம் (கீழே change_password API பாருங்கள்).
# அதுவரை/settings-ல் இல்லைன்னா, இந்த DEFAULT மதிப்புகள் பயன்படுத்தப்படும்.
# (librarian-க்கு password தேவையில்லை)
DEFAULT_PASSWORDS = {
    "admin": "9443393428",
    "dclstaff": "12345678",
}
ACCOUNT_ROLES = {
    "admin": "admin",
    "dclstaff": "staff",
    "librarian": "librarian",
}

# ==========================================================
# ஆண்டு-வாரியான தரவு (2024-2025, 2025-2026, ...) — BASE_YEAR என்பது
# இதற்கு முன் இருந்த 78,000 rows-க்கு சொந்தமான ஆண்டு. இதே ஆண்டுக்கு
# central_number/branch_number counters *பழைய* (year-suffix இல்லாத)
# key-களையே தொடர்ந்து பயன்படுத்தும் — இப்போதைய எண்கள் தொடராமல்
# மறு தொடக்கம் ஆகாமல் இருக்க. இதற்கு அடுத்த ஒவ்வொரு புதிய ஆண்டும்
# (2025-2026 முதல்) தனி key (":<ஆண்டு>" suffix) பெற்று 1-ல் இருந்தே
# தொடங்கும்.
# ==========================================================
BASE_YEAR = "2024-2025"


def _counter_key(base_key, year):
    """central_number/branch:<id> போன்ற counter key-க்கு ஆண்டு ஏற்ப suffix.
    BASE_YEAR-க்கு பழைய (suffix இல்லா) key-ஐயே தொடரும்; அடுத்த ஆண்டுகளுக்கு
    தனி key (1 முதல் தொடங்கும்)."""
    year = (year or BASE_YEAR).strip()
    if year == BASE_YEAR:
        return base_key
    return f"{base_key}:{year}"


def _get_setting(key, default=None):
    with DBConn() as (conn, cur):
        cur.execute("SELECT value FROM settings WHERE key=%s", (key,))
        row = cur.fetchone()
    return row["value"] if row and row["value"] not in (None, "") else default


def _set_setting(key, value):
    with DBConn() as (conn, cur):
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value)
        )
    return True


def _get_password_hash(username):
    """settings table-ல் இருந்து இந்த account-ன் password hash-ஐ படிக்கும்.
    இல்லைன்னா DEFAULT_PASSWORDS-ஐ hash பண்ணி திருப்பும்."""
    with DBConn() as (conn, cur):
        cur.execute("SELECT value FROM settings WHERE key=%s", (f"pwd_{username}",))
        row = cur.fetchone()
    if row and row["value"]:
        return row["value"]
    default_pwd = DEFAULT_PASSWORDS.get(username)
    return generate_password_hash(default_pwd) if default_pwd else None


def _set_password_hash(username, new_password):
    pwd_hash = generate_password_hash(new_password)
    with DBConn() as (conn, cur):
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (f"pwd_{username}", pwd_hash)
        )
    return True


def _verify_admin_password(password):
    """Master Data (Restore / Clear / Assigning Data Clear) — மூன்று
    option-க்கும் Admin password (தற்போது settings-ல் / DEFAULT_PASSWORDS-ல்
    உள்ளது — Dlodgl@789) சரிபார்க்க பயன்படும்."""
    pwd_hash = _get_password_hash("admin")
    return bool(pwd_hash and password and check_password_hash(pwd_hash, password))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return LOGIN_HTML.replace("{error}", "")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    role = ACCOUNT_ROLES.get(username)
    if not role:
        return LOGIN_HTML.replace("{error}", '<div class="err">தவறான தேர்வு</div>')

    if role == "librarian":
        # librarian — password தேவையில்லை
        session["username"] = username
        session["role"] = role
        return redirect("/")

    pwd_hash = _get_password_hash(username)
    if pwd_hash and check_password_hash(pwd_hash, password):
        session["username"] = username
        session["role"] = role
        return redirect("/")

    return LOGIN_HTML.replace("{error}", '<div class="err">தவறான password</div>')


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
@login_required
def index():
    if session.get("role") == "librarian":
        html_content = LIBRARIAN_HTML.replace("{{DISTRICT_NAME}}", DISTRICT_NAME)
        resp = make_response(html_content)
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp

    html_content = MAIN_HTML.replace("{{DISTRICT_NAME}}", DISTRICT_NAME)
    # staff-க்கு renumber/settings பட்டன்கள் மறைக்க ஒரு simple flag frontend-க்கு அனுப்பப்படுகிறது
    html_content = html_content.replace(
        "</head>",
        f'<script>window.CURRENT_ROLE="{session.get("role")}";'
        f'window.CURRENT_USER="{session.get("username")}";</script></head>'
    )
    resp = make_response(html_content)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


@app.route("/appjs")
@login_required
def serve_app_js():
    resp = make_response(APP_JS)
    resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


@app.route("/favicon.ico")
def favicon():
    return "", 204


# ==========================================================
# FUZZY DUPLICATE DETECTION — original main.py-ன் findFuzzyDuplicateGroups()
# அடிப்படையிலான algorithm அப்படியே port செய்யப்பட்டது (85% similarity)
# ==========================================================
def _normalize_title_for_fuzzy(t):
    s = str(t).lower()
    s = re.sub(r'[-–]\s*rs\.?\s*\d+(\.\d+)?', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\(\s*rs\.?\s*\d+(\.\d+)?\s*\)', '', s, flags=re.IGNORECASE)
    s = re.sub(r"[\u2018\u2019\u201A\u201B\u2032\u0060\u00B4]", "'", s)
    s = re.sub(r"[^\w\s']", ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _titles_are_similar(a, b):
    if a == b:
        return True
    la, lb = len(a), len(b)
    if la < 3 or lb < 3:
        return False
    if min(la, lb) / max(la, lb) < 0.4:
        return False
    char_match = la >= 5 and lb >= 5 and a[:5] == b[:5]
    wa, wb = a.split(), b.split()
    word_match = len(wa) >= 2 and len(wb) >= 2 and wa[:2] == wb[:2]
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        for j in range(1, lb + 1):
            curr[j] = prev[j - 1] if a[i - 1] == b[j - 1] else 1 + min(prev[j], curr[j - 1], prev[j - 1])
        prev = curr
    lev = 1.0 - prev[lb] / max(la, lb)
    if lev >= 0.80:
        return True
    if (char_match or word_match) and lev >= 0.65:
        return True
    return False


_fuzzy_cache = {}            # academic_year -> clusters list
_fuzzy_cache_status = {}      # academic_year -> idle | running | done
_fuzzy_cache_progress = {}    # academic_year -> 0-100


def _build_fuzzy_cache(app_ctx, year):
    global _fuzzy_cache, _fuzzy_cache_status, _fuzzy_cache_progress
    _fuzzy_cache_status[year] = "running"
    _fuzzy_cache_progress[year] = 0
    try:
        with app_ctx.app_context():
            with DBConn() as (conn, cur):
                cur.execute(
                    "SELECT title, price FROM books "
                    "WHERE title IS NOT NULL AND LENGTH(TRIM(title)) > 3 AND academic_year = %s",
                    (year,)
                )
                all_rows = cur.fetchall()

            title_prices = defaultdict(set)
            title_counts = defaultdict(int)
            for r in all_rows:
                t = r["title"].strip()
                title_prices[t].add(str(r["price"]))
                title_counts[t] += 1
            unique_titles = list(title_prices.keys())

            norm_keys = [_normalize_title_for_fuzzy(t) for t in unique_titles]
            n = len(norm_keys)
            prefix_idx = defaultdict(list)
            for i, k in enumerate(norm_keys):
                prefix_idx[k[:3]].append(i)

            visited = [False] * n
            clusters = []
            for i in range(n):
                if visited[i]:
                    continue
                ki = norm_keys[i]
                group_idx = [i]
                visited[i] = True
                candidates = set(prefix_idx.get(ki[:3], []))
                candidates.discard(i)
                for j in candidates:
                    if j <= i or visited[j]:
                        continue
                    if _titles_are_similar(ki, norm_keys[j]):
                        group_idx.append(j)
                        visited[j] = True
                if len(group_idx) > 1:
                    titles_in_group = [unique_titles[x] for x in group_idx]
                    all_prices = list({p for t in titles_in_group for p in title_prices.get(t, [])})
                    total_count = sum(title_counts.get(t, 0) for t in titles_in_group)
                    clusters.append({
                        "canonical": titles_in_group[0], "variants": titles_in_group,
                        "allPrices": all_prices, "count": total_count
                    })
                _fuzzy_cache_progress[year] = int((i + 1) / n * 100) if n else 100

            # கவனிக்க தாவலில் காட்டும் தலைப்புகள் A-Z வரிசையில் (canonical title அடிப்படையில்)
            clusters.sort(key=lambda c: c["canonical"].lower())

            _fuzzy_cache[year] = clusters
            _fuzzy_cache_status[year] = "done"
            _fuzzy_cache_progress[year] = 100
    except Exception as e:
        print(f"Fuzzy cache build error: {e}")
        _fuzzy_cache_status[year] = "idle"
        _fuzzy_cache_progress[year] = 0


def _start_fuzzy_cache_if_needed(year):
    global _fuzzy_cache_status
    if _fuzzy_cache_status.get(year, "idle") == "idle":
        _fuzzy_cache_status[year] = "running"
        threading.Thread(target=_build_fuzzy_cache, args=(app, year), daemon=True).start()


# ==========================================================
# ஆண்டு (Academic Year) — Settings
#   - /api/years/available   : books table-ல் இருக்கும் ஆண்டுகள் பட்டியல்
#                               (dropdown-க்கு) — புதியது முதலில்.
#   - /api/years/librarian_view (GET)  : நூலகர் login-க்கு admin வைத்த ஆண்டு
#   - /api/years/librarian_view (POST) : admin மட்டும் — நூலகர் பார்வைக்கான
#                                          ஆண்டை மாற்ற
# ==========================================================
@app.route("/api/years/available")
@login_required
def api_years_available():
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT academic_year FROM books "
            "WHERE academic_year IS NOT NULL AND academic_year != '' "
            "ORDER BY academic_year DESC"
        )
        years = [r["academic_year"] for r in cur.fetchall()]
    if not years:
        years = [BASE_YEAR]
    return jsonify({"years": years, "default": years[0]})


@app.route("/api/years/librarian_view", methods=["GET"])
@login_required
def api_years_librarian_view_get():
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT academic_year FROM books "
            "WHERE academic_year IS NOT NULL AND academic_year != '' "
            "ORDER BY academic_year DESC"
        )
        years = [r["academic_year"] for r in cur.fetchall()] or [BASE_YEAR]
    active = _get_setting("active_academic_year", years[0])
    return jsonify({"active_year": active, "years": years})


@app.route("/api/years/librarian_view", methods=["POST"])
@admin_required
def api_years_librarian_view_set():
    year = (request.json or {}).get("year", "").strip()
    if not year:
        return jsonify({"error": "ஆண்டு தேர்ந்தெடுக்கவும்"}), 400
    _set_setting("active_academic_year", year)
    return jsonify({"success": True, "active_year": year})


# ==========================================================
#   - /api/years/staff_view (GET)  : dclstaff-க்கு Admin வைத்த ஆண்டு
#                                      (dclstaff-க்கு selector காட்டப்படாது;
#                                      Admin main ஆண்டு dropdown-ல் மாற்றும்போதே
#                                      இதுவும் தானாக புதுப்பிக்கப்படும்)
#   - /api/years/staff_view (POST) : admin மட்டும் — dclstaff பார்வைக்கான
#                                      ஆண்டை மாற்ற
# ==========================================================
@app.route("/api/years/staff_view", methods=["GET"])
@login_required
def api_years_staff_view_get():
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT academic_year FROM books "
            "WHERE academic_year IS NOT NULL AND academic_year != '' "
            "ORDER BY academic_year DESC"
        )
        years = [r["academic_year"] for r in cur.fetchall()] or [BASE_YEAR]
    active = _get_setting("active_staff_year", years[0])
    if active not in years:
        active = years[0]
    return jsonify({"active_year": active, "years": years})


@app.route("/api/years/staff_view", methods=["POST"])
@admin_required
def api_years_staff_view_set():
    year = (request.json or {}).get("year", "").strip()
    if not year:
        return jsonify({"error": "ஆண்டு தேர்ந்தெடுக்கவும்"}), 400
    _set_setting("active_staff_year", year)
    return jsonify({"success": True, "active_year": year})


# ==========================================================
# DASHBOARD — Live ticker + multi-price banner
# ==========================================================
@app.route("/api/ticker_data")
@login_required
def api_ticker_data():
    today_str = datetime.now().strftime("%d/%m/%Y")
    year = request.args.get("year") or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE set_number IS NOT NULL AND set_number != '') AS assigned, "
            f"COUNT(*) FILTER (WHERE {_SENT_SQL}) AS sent, "
            "COUNT(*) FILTER (WHERE work_status = %s) AS today_assigned "
            "FROM books WHERE academic_year = %s",
            (today_str, year)
        )
        row = cur.fetchone()
    total = row["total"]
    assigned = row["assigned"]
    return jsonify({
        "status": "success",
        "received": total,
        "assigned": assigned,
        "sent": row["sent"],
        "unassigned": total - assigned,
        "todayAssigned": row["today_assigned"],
        "today": today_str,
        "year": year
    })


@app.route("/api/multi_price_titles")
@login_required
def api_multi_price_titles():
    year = request.args.get("year") or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT MIN(title) AS title, "
            "ARRAY_AGG(DISTINCT price ORDER BY price) AS prices "
            "FROM books "
            "WHERE (set_number IS NULL OR set_number = '') "
            "AND title IS NOT NULL AND TRIM(title) != '' "
            "AND academic_year = %s "
            f"GROUP BY {_NORM_TITLE_SQL} "
            "HAVING COUNT(DISTINCT price) > 1",
            (year,)
        )
        rows = cur.fetchall()
    return jsonify([
        {"title": (r["title"] or "")[:100], "prices": r["prices"]}
        for r in rows
    ])


@app.route("/api/multi_isbn_titles")
@login_required
def api_multi_isbn_titles():
    year = request.args.get("year") or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT MIN(title) AS title, "
            "ARRAY_AGG(DISTINCT isbn ORDER BY isbn) AS isbns "
            "FROM books "
            "WHERE (set_number IS NULL OR set_number = '') "
            "AND title IS NOT NULL AND TRIM(title) != '' "
            "AND isbn IS NOT NULL AND TRIM(isbn) != '' "
            "AND academic_year = %s "
            f"GROUP BY {_EXACT_TITLE_SQL} "
            "HAVING COUNT(DISTINCT isbn) > 1",
            (year,)
        )
        rows = cur.fetchall()
    return jsonify([
        {"title": (r["title"] or "")[:100], "isbns": r["isbns"]}
        for r in rows
    ])


@app.route("/api/admin/rename_by_isbn", methods=["POST"])
@admin_required
def api_admin_rename_by_isbn():
    """Multi-ISBN தலைப்பை பிரிக்க அனுமதிக்க — Admin மட்டும் ஒரு ISBN-க்குரிய
    நகல்களின் தலைப்பை (மற்றும்/அல்லது தேவைப்பட்டால் ISBN-ஐயே) மாற்ற இந்த
    endpoint பயன்படுகிறது. இந்த தலைப்பு-மாற்று exact-title ஒப்பீட்டையே
    (ஹைபன் split செய்யாமல்) பயன்படுத்துவதால், தலைப்பில் "-" இருந்தாலும்
    பரவாயில்லை — இரண்டு பாகங்களுக்கும் full-text வேறுபடும் வரை போதும்."""
    data = request.json or {}
    year = data.get("year") or BASE_YEAR
    old_isbn = (data.get("old_isbn") or "").strip()
    new_title = data.get("new_title")
    new_isbn = data.get("new_isbn")
    if new_title is not None:
        new_title = new_title.strip()
    if new_isbn is not None:
        new_isbn = new_isbn.strip()

    if not old_isbn:
        return jsonify({"error": "ISBN கொடுக்கப்படவில்லை"}), 400
    if not new_title and not new_isbn:
        return jsonify({"error": "புதிய தலைப்பு அல்லது புதிய ISBN — ஏதேனும் ஒன்றை கொடுக்கவும்"}), 400

    with DBConn() as (conn, cur):
        try:
            cur.execute(
                "SELECT COUNT(*) AS c FROM books WHERE isbn=%s AND academic_year=%s",
                (old_isbn, year)
            )
            if cur.fetchone()["c"] == 0:
                return jsonify({"error": f"ISBN '{old_isbn}' கொண்ட புத்தகம் இந்த ஆண்டில் இல்லை"}), 404

            set_parts = []
            params = []
            if new_title:
                set_parts.append("title=%s")
                params.append(new_title)
            if new_isbn:
                set_parts.append("isbn=%s")
                params.append(new_isbn)
            params.extend([old_isbn, year])

            cur.execute(
                f"UPDATE books SET {', '.join(set_parts)} "
                "WHERE isbn=%s AND academic_year=%s",
                tuple(params)
            )
            updated = cur.rowcount
            conn.commit()
        except Exception as e:
            conn.rollback()
            return jsonify({"error": f"பிழை: {e}"}), 500

    return jsonify({
        "success": True,
        "message": f"{updated} பதிவுகள் புதுப்பிக்கப்பட்டன",
        "updated": updated
    })


@app.route("/api/isbn_info")
@login_required
def api_isbn_info():
    """ISBN மாற்று Modal-ல் காட்ட — பதிப்பகம் (vendor_name) மற்றும்
    பதிப்பு விலை (price) ஆகியவற்றை படிக்க-மட்டும் (not editable) திரும்பும்."""
    isbn = (request.args.get("isbn") or "").strip()
    year = request.args.get("year") or BASE_YEAR
    if not isbn:
        return jsonify({"error": "ISBN கொடுக்கப்படவில்லை"}), 400
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT vendor_name, price, author FROM books WHERE isbn=%s AND academic_year=%s "
            "AND vendor_name IS NOT NULL AND TRIM(vendor_name) != '' LIMIT 1",
            (isbn, year)
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "SELECT vendor_name, price, author FROM books WHERE isbn=%s AND academic_year=%s LIMIT 1",
                (isbn, year)
            )
            row = cur.fetchone()
    return jsonify({
        "vendor_name": (row["vendor_name"] if row else "") or "",
        "price": (row["price"] if row else "") or "",
        "author": (row["author"] if row else "") or ""
    })


@app.route("/api/fuzzy_alert_titles")
@login_required
def api_fuzzy_alert_titles():
    year = request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    status = _fuzzy_cache_status.get(year, "idle")
    if status == "idle":
        _start_fuzzy_cache_if_needed(year)
        return jsonify({"status": "running", "clusters": [], "progress": 0})
    if status == "running":
        return jsonify({"status": "running", "clusters": [], "progress": _fuzzy_cache_progress.get(year, 0)})
    return jsonify({"status": "done", "clusters": _fuzzy_cache.get(year, []), "progress": 100})


@app.route("/api/fuzzy_reset", methods=["POST"])
@staff_or_admin_required
def api_fuzzy_reset():
    year = (request.json or {}).get("year") or request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    _fuzzy_cache.pop(year, None)
    _fuzzy_cache_status[year] = "idle"
    _fuzzy_cache_progress[year] = 0
    _start_fuzzy_cache_if_needed(year)
    return jsonify({"success": True})


@app.route("/api/_debug_check")
@admin_required
def api_debug_check():
    """
    தற்காலிக diagnostic route — நூலகங்கள் காட்டாத பிரச்சனையை கண்டுபிடிக்க.
    (இதை /login பக்கத்தில் admin-ஆக login செய்தபின் browser-ல் நேரடியாக
     https://உங்கள்-site.onrender.com/api/_debug_check என்று திறந்தால் தகவல் காட்டும்)
    """
    with DBConn() as (conn, cur):
        cur.execute("SELECT COUNT(*) AS c FROM books")
        total = cur.fetchone()["c"]
        cur.execute("SELECT DISTINCT library_type FROM books WHERE library_type IS NOT NULL LIMIT 20")
        lib_types = [r["library_type"] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) AS c FROM books WHERE library_name_tm IS NOT NULL AND library_name_tm != ''")
        has_lib_name = cur.fetchone()["c"]
        cur.execute("SELECT title, price, library_type, library_name_tm, set_number FROM books LIMIT 5")
        sample = cur.fetchall()
    return jsonify({
        "total_rows": total,
        "distinct_library_types": lib_types,
        "rows_with_library_name_tm": has_lib_name,
        "sample_rows": sample
    })


# ==========================================================
# SEND BOOKS — assign ஆன ஆனால் இன்னும் அனுப்பப்படாத sets/libraries
# unsent = SENT_DETAILS != 'sent' (case-insensitive) மற்றும் DATE காலியாக இருக்க வேண்டும்
# ==========================================================
_UNSENT_SQL = (
    "(sent_details IS NULL OR LOWER(TRIM(sent_details)) != 'sent') "
    "AND (date IS NULL OR LOWER(TRIM(date)) IN ('', 'nan', 'none', 'nat', '<na>'))"
)
# sent = unsent-ன் நேர் மறுதலை (NOT). இதனால் 'Sent' என App எழுதியவையும்,
# 'Sent to Library' போன்று பழைய Excel-ல் இருந்து migrate ஆன மதிப்புகளும்
# (date field-ல் மதிப்பு இருப்பதால்) இரண்டுமே சரியாக "அனுப்பப்பட்டது" என recognize ஆகும்.
_SENT_SQL = f"(NOT ({_UNSENT_SQL}))"

# ==========================================================
# தமிழ் / ஆங்கிலப் புத்தகப் பிரிப்பு — புதிய column தேவையில்லை.
# title-ல் தமிழ் யுனிகோட் எழுத்து (U+0B80–U+0BFF) இருந்தால் "தமிழ்ப் புத்தகம்",
# இல்லையென்றால் (title முழுவதும் ஆங்கிலம்/மற்றவை) "ஆங்கிலப் புத்தகம்" எனக்
# கருதப்படும். இருக்கும் தரவுக்கும் புதிதாக வரும் தரவுக்கும் தானாகவே பொருந்தும்.
# ==========================================================
_TAMIL_TITLE_SQL = "title ~ '[\u0B80-\u0BFF]'"

# ==========================================================
# NORMALIZED TITLE — "ஒரே தலைப்பில் வேறு வேறு விலைகள்" (dashboard, Report 8,
# unassigned isMultiPrice flag, assign-time warning) மற்றும் Report 9
# (நூலகத்தில் நகல் தலைப்புகள்) — இவை அனைத்திலும் இதே normalization:
#   1. ஒற்றை/இரட்டை மேற்கோள் குறிகள் (' " ' ' " ") நீக்கப்படும்
#   2. இடைவெளிகள் ஒன்றாக சுருக்கப்படும்
#   3. பெரிய/சிறிய எழுத்து வேறுபாடு பொருட்படுத்தப்படாது
#   4. "-" (ஹைபன்) இருந்தால், அதற்குப் பின் இருக்கும் பகுதியைப் பொறுத்து:
#      a) ஒன்றுமே இல்லை (காலி) என்றால் (எ.கா. "இந்தியா-")
#         → split செய்யப்படும் (ஹைபனுக்கு முந்தைய பகுதி மட்டும்)
#      b) ஆங்கில எழுத்துகள் (A-Z) இருந்தால் (எ.கா. "-Price.Rs.99",
#         "-PRICE-300") → split செய்யப்படும் (identity suffix)
#      c) தமிழ் எழுத்துகள் இருந்தால் (எ.கா. "அண்ணல் அம்பேத்கர்- ஜெகதா")
#         → split செய்யப்படும் (ஆசிரியர்/பதிப்பகம் பெயர் — identity suffix,
#         2026-09 முதல்: இதுவும் நீக்கப்படும்)
#      d) வெறும் எண்கள்/அடைப்புக்குறி மட்டும் இருந்தால், ஆங்கில/தமிழ்
#         எழுத்து ஏதுமில்லாமல் (எ.கா. "பாகம்-1" vs "பாகம்-2",
#         "Part-1" vs "Part-2") → split வேண்டாம், முழு தலைப்பும்
#         ஒப்பிடப்படும் (இவை Part/பாகம் எண் — வெவ்வேறு தொகுதிகள்,
#         ஒன்றல்ல)
# இதைத் தவிர வேறு எந்த fuzzy match-ம் இங்கு செய்யப்படாது. (85% ஒத்த
# தலைப்புகள் தேவைக்கு தனியான Fuzzy Match feature ஏற்கனவே உள்ளது.)
# ==========================================================
_QUOTE_CHARS_RE = "['\"\u2018\u2019\u201C\u201D]"

_CLEAN_TITLE_SQL = (
    "UPPER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(TRIM(title), "
    "'[''\"\u2018\u2019\u201C\u201D]', '', 'g'), '\\s+', ' ', 'g')))"
)

_NORM_TITLE_SQL = (
    "CASE "
    f"WHEN POSITION('-' IN {_CLEAN_TITLE_SQL}) = 0 THEN {_CLEAN_TITLE_SQL} "
    "WHEN TRIM(SUBSTRING("
    f"{_CLEAN_TITLE_SQL} FROM POSITION('-' IN {_CLEAN_TITLE_SQL}) + 1"
    ")) = '' "
    f"THEN TRIM(SPLIT_PART({_CLEAN_TITLE_SQL}, '-', 1)) "
    "WHEN TRIM(SUBSTRING("
    f"{_CLEAN_TITLE_SQL} FROM POSITION('-' IN {_CLEAN_TITLE_SQL}) + 1"
    ")) ~ '[A-Za-z\u0B80-\u0BFF]' "
    f"THEN TRIM(SPLIT_PART({_CLEAN_TITLE_SQL}, '-', 1)) "
    f"ELSE {_CLEAN_TITLE_SQL} "
    "END"
)

# அறிக்கை 11-க்கு மட்டும்: quote/space-clean, hyphen-suffix rule எதுவும்
# இல்லாமல் — வெறும் UPPER+TRIM (case-insensitive exact match) மட்டும்.
_NORM_TITLE_SIMPLE_SQL = "UPPER(TRIM(title))"


def _norm_title(t):
    """Python-side equivalent of _NORM_TITLE_SQL — frontend இல்லாத ஒப்பீடுகளுக்கு."""
    t = re.sub(_QUOTE_CHARS_RE, '', (t or ''))
    t = re.sub(r'\s+', ' ', t.strip()).upper()
    if '-' not in t:
        return t
    before, _, after = t.partition('-')
    after = after.strip()
    if after == '' or re.search('[A-Za-z\u0B80-\u0BFF]', after):
        return before.strip()
    return t


# ==========================================================
# EXACT TITLE (ஹைபன் split செய்யாமல்) — MULTI-ISBN குழுவாக்கத்திற்கு மட்டும்.
# _NORM_TITLE_SQL ஹைபனுக்குப் பின்னதை புறக்கணிப்பதால், "தமிழியல் நூல்கள் -
# X" மற்றும் "தமிழியல் நூல்கள் - Y" போன்ற இரு தனித்தனி தலைப்புகளையும் ஒரே
# தலைப்பாக தவறாக group செய்துவிடும் (இங்கு "-" என்பது ஒரு series-க்குள்
# பல்வேறு subtitle-களை பிரிக்கும் தலைப்பின் இயல்பான பகுதி, நீக்க வேண்டிய
# noise அல்ல). MULTI-ISBN check-க்கு நாம் "ஒரே தலைப்பு exact-ஆக இருந்தும்
# 2 வெவ்வேறு ISBN" உள்ள நிலையை மட்டுமே கண்டறிய வேண்டும் என்பதால், இங்கு
# இடைவெளி/எழுத்துரு வேறுபாடு மட்டும் தள்ளுபடி செய்யப்படும் — ஹைபன் split
# செய்யப்படாது.
# ==========================================================
_EXACT_TITLE_SQL = (
    "UPPER(TRIM(REGEXP_REPLACE(TRIM(title), '\\\\s+', ' ', 'g')))"
)


def _exact_norm_title(t):
    """Python-side equivalent of _EXACT_TITLE_SQL — ஹைபன் split செய்யாது."""
    t = re.sub(r'\s+', ' ', (t or '').strip())
    return t.upper()


# ==========================================================
# MULTI-ISBN GUARD — ஒரே (exact) தலைப்பில் 2+ வெவ்வேறு ISBN இருந்தால்
# (உதா: ஒரு புத்தகத்தின் பாகம்-1, பாகம்-2 ஒரே தலைப்பில் upload ஆகியிருக்கலாம்)
# அதை பிரிக்க அனுமதிக்கக் கூடாது — Admin தலைப்பை/ISBN-ஐ மாற்றியபின்னரே பிரிக்க முடியும்.
# ==========================================================
def _isbns_for_title(cur, title, year):
    """கொடுக்கப்பட்ட (exact) தலைப்பின் unassigned நகல்களில் உள்ள
    distinct, non-empty ISBN-களின் பட்டியலைத் தரும்."""
    norm = _exact_norm_title(title)
    cur.execute(
        f"SELECT DISTINCT isbn FROM books "
        f"WHERE {_EXACT_TITLE_SQL} = %s "
        "AND (set_number IS NULL OR set_number = '') "
        "AND academic_year = %s "
        "AND isbn IS NOT NULL AND TRIM(isbn) != '' "
        "ORDER BY isbn",
        (norm, year)
    )
    return [r["isbn"] for r in cur.fetchall()]


def _multi_isbn_block_message(isbns):
    n = len(isbns)
    return (
        f"இந்த தலைப்புக்கு {n} ISBN எண்கள் உள்ளன — எனவே இந்த தலைப்பு "
        "பாகங்களாக இருக்கலாம். Admin-ஐ அணுகி தலைப்பை மாற்றியபின்னரே பிரிக்க இயலும்."
    )


@app.route("/api/send/sets")
@login_required
def api_send_sets():
    year = request.args.get("year") or BASE_YEAR
    wage_centers = _get_wage_centers_param()
    with DBConn() as (conn, cur):
        if wage_centers:
            placeholders = ",".join(["%s"] * len(wage_centers))
            cur.execute(
                "SELECT set_number, COUNT(*) AS c FROM books "
                "WHERE central_number IS NOT NULL "
                "AND set_number IS NOT NULL AND set_number != '' "
                f"AND {_UNSENT_SQL} AND academic_year = %s "
                f"AND TRIM(state_acc_number_1) IN ({placeholders}) "
                "GROUP BY set_number ORDER BY set_number",
                (year, *wage_centers)
            )
        else:
            cur.execute(
                "SELECT set_number, COUNT(*) AS c FROM books "
                "WHERE central_number IS NOT NULL "
                "AND set_number IS NOT NULL AND set_number != '' "
                f"AND {_UNSENT_SQL} AND academic_year = %s "
                "GROUP BY set_number ORDER BY set_number",
                (year,)
            )
        rows = cur.fetchall()
    return jsonify([{"set": r["set_number"], "count": r["c"]} for r in rows])


@app.route("/api/send/libraries")
@login_required
def api_send_libraries():
    set_number = request.args.get("set", "")
    year = request.args.get("year") or BASE_YEAR
    wage_centers = _get_wage_centers_param()
    with DBConn() as (conn, cur):
        if wage_centers:
            placeholders = ",".join(["%s"] * len(wage_centers))
            cur.execute(
                "SELECT library_name_tm, MIN(library_type) AS library_type, COUNT(*) AS c FROM books "
                "WHERE set_number = %s AND central_number IS NOT NULL "
                f"AND {_UNSENT_SQL} AND academic_year = %s "
                f"AND TRIM(state_acc_number_1) IN ({placeholders}) "
                "GROUP BY library_name_tm",
                (set_number, year, *wage_centers)
            )
            rows = cur.fetchall()
            rows.sort(key=lambda r: (_lib_type_rank(r["library_type"]), r["library_name_tm"] or ""))
            cur.execute(
                "SELECT COUNT(*) AS c FROM books "
                "WHERE set_number = %s AND central_number IS NOT NULL "
                f"AND {_UNSENT_SQL} AND academic_year = %s "
                f"AND TRIM(state_acc_number_1) IN ({placeholders})",
                (set_number, year, *wage_centers)
            )
            total = cur.fetchone()["c"]
        else:
            cur.execute(
                "SELECT library_name_tm, COUNT(*) AS c FROM books "
                "WHERE set_number = %s AND central_number IS NOT NULL "
                f"AND {_UNSENT_SQL} AND academic_year = %s "
                "GROUP BY library_name_tm ORDER BY library_name_tm",
                (set_number, year)
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) AS c FROM books "
                "WHERE set_number = %s AND central_number IS NOT NULL "
                f"AND {_UNSENT_SQL} AND academic_year = %s",
                (set_number, year)
            )
            total = cur.fetchone()["c"]
    return jsonify({
        "libraries": [{"lib": r["library_name_tm"], "count": r["c"]} for r in rows],
        "total": total
    })


@app.route("/api/send/mark", methods=["POST"])
@staff_or_admin_required
def api_send_mark():
    data = request.json or {}
    set_number = data.get("set_number")
    selected_libs = data.get("libraries", [])
    year = data.get("year") or BASE_YEAR
    if not selected_libs:
        return jsonify({"error": "நூலகம் தேர்வு செய்யவும்"}), 400

    today = datetime.now().strftime("%d/%m/%Y")
    with DBConn() as (conn, cur):
        cur.execute(
            "UPDATE books SET sent_details='Sent', date=%s "
            "WHERE set_number=%s AND central_number IS NOT NULL "
            f"AND {_UNSENT_SQL} AND library_name_tm = ANY(%s) AND academic_year = %s",
            (today, set_number, selected_libs, year)
        )
        updated = cur.rowcount
    if not updated:
        return jsonify({"error": "பதிவு செய்ய எதுவும் இல்லை"}), 400
    return jsonify({
        "success": True,
        "message": f"{updated} புத்தகங்கள் அனுப்பப்பட்டதாக பதிவு செய்யப்பட்டன!\nதேதி: {today}"
    })


# ==========================================================
# RENUMBER — Admin மட்டும். Renumber செய்யும் முன் பாதிக்கப்படும் rows-ன்
# பழைய மதிப்புகள் 'backups' table-ல் snapshot ஆக சேமிக்கப்படும் (undo-க்கு).
# ==========================================================
def _make_backup(backup_type, rows, counter_key=None, counter_old_value=None, label_prefix="backup"):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{label_prefix}_{ts}"
    data = {
        "type": backup_type,
        "rows": rows,
        "counter_key": counter_key,
        "counter_old_value": counter_old_value,
    }
    with DBConn() as (conn, cur):
        cur.execute(
            "INSERT INTO backups (filename, data) VALUES (%s, %s) RETURNING id",
            (filename, psycopg2.extras.Json(data))
        )
        backup_id = cur.fetchone()["id"]
    return filename, backup_id


@app.route("/api/renumber/library_names")
@admin_required
def api_renumber_library_names():
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT library_name_tm FROM books "
            "WHERE branch_number IS NOT NULL AND library_name_tm IS NOT NULL "
            "AND library_name_tm != '' ORDER BY library_name_tm"
        )
        rows = cur.fetchall()
    return jsonify([r["library_name_tm"] for r in rows])


@app.route("/api/renumber/central", methods=["POST"])
@admin_required
def api_renumber_central():
    data = request.json or {}
    try:
        new_start = int(data.get("new_start"))
    except Exception:
        return jsonify({"error": "சரியான எண் பதிவிடவும்"}), 400
    apply_existing = bool(data.get("apply_existing"))
    year = data.get("year") or BASE_YEAR
    ckey = _counter_key("central_number", year)

    backup_name = None
    renumbered_count = 0
    with DBConn() as (conn, cur):
        if apply_existing:
            cur.execute(
                "SELECT id, central_number FROM books "
                "WHERE central_number IS NOT NULL AND academic_year = %s "
                "ORDER BY central_number FOR UPDATE",
                (year,)
            )
            rows = cur.fetchall()
            if rows:
                backup_rows = [{"id": r["id"], "old_central": r["central_number"]} for r in rows]
                cur.execute(
                    "INSERT INTO counters (key, next_value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO NOTHING",
                    (ckey, 1)
                )
                cur.execute("SELECT next_value FROM counters WHERE key=%s FOR UPDATE", (ckey,))
                old_counter = cur.fetchone()["next_value"]
                backup_name, _ = _make_backup(
                    "central", backup_rows, ckey, old_counter, "central_renumber"
                )
                new_val = new_start
                for r in rows:
                    cur.execute("UPDATE books SET central_number=%s WHERE id=%s", (new_val, r["id"]))
                    new_val += 1
                renumbered_count = len(rows)
                cur.execute(
                    "UPDATE counters SET next_value=%s WHERE key=%s",
                    (new_val, ckey)
                )
        else:
            cur.execute(
                "INSERT INTO counters (key, next_value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET next_value=EXCLUDED.next_value",
                (ckey, new_start)
            )

    msg = f"{year} ஆண்டுக்கான மையப் பதிவெண் தொடக்க மதிப்பு {new_start} ஆக சேவ் செய்யப்பட்டது."
    if apply_existing and renumbered_count:
        msg += f"\n{renumbered_count} புத்தகங்களின் மையப்பதிவெண் {new_start}-ல் இருந்து மீண்டும் வரிசைப்படுத்தப்பட்டது."
    return jsonify({
        "success": True, "backup_file": backup_name,
        "renumbered_count": renumbered_count, "message": msg
    })


def _renumber_branch_core(cur, library_name, new_start, year=None):
    """ஒரே ஒரு நூலகத்தின் கிளைப் பதிவெண்களை renumber செய்யும் பகிரப்பட்ட logic.
    single மற்றும் bulk endpoints இரண்டும் இதையே பயன்படுத்தும். year கொடுக்கப்பட்டால்
    அந்த ஆண்டுக்குரிய புத்தகங்கள் மட்டும் தொடப்படும், அந்த ஆண்டுக்கான தனி counter
    (BASE_YEAR-க்கு பழைய key, மற்றவற்றுக்கு year-suffix key) பயன்படுத்தப்படும்.

    - அந்த நூலகத்திற்கு ஏற்கனவே 'பிரிக்க' (assign) செய்யப்பட்ட புத்தகங்கள் (branch_number
      NOT NULL) இருந்தால் — அவற்றை new_start-ல் இருந்து மீண்டும் வரிசைப்படுத்தி, counter-ஐ
      அதற்கேற்ப புதுப்பிக்கும் (பழைய behavior, மாறவில்லை).
    - இன்னும் எந்த புத்தகமும் பிரிக்கப்படாத நூலகமாக இருந்தால் (branch_number எதுவும்
      இல்லை) — புத்தகங்கள் எதையும் தொடாமல், அந்த நூலகத்தின் அடுத்த 'பிரிக்க' counter-ஐ
      மட்டும் new_start ஆக சேமிக்கும் (மையப்பதிவெண்-ஐ போலவே தொடக்க எண் மட்டும் set செய்தல்).

    திரும்பும் மதிப்பு: (backup_rows, counter_olds, count) — இந்த நூலகமே இல்லை எனில்
    மட்டும் (None, None, 0)."""
    year = year or BASE_YEAR
    # இந்த நூலகத்தின் librarian_id(கள்) — புத்தகம் பிரிக்கப்பட்டதா இல்லையா என்பதைப்
    # பொருட்படுத்தாமல், அந்த ஆண்டு அப்லோட் செய்யப்பட்ட அனைத்து புத்தகங்களிலிருந்தும் கண்டறியப்படும்.
    cur.execute(
        "SELECT DISTINCT librarian_id FROM books "
        "WHERE library_name_tm = %s AND librarian_id IS NOT NULL AND academic_year = %s",
        (library_name, year)
    )
    lib_id_rows = cur.fetchall()
    if not lib_id_rows:
        return None, None, 0

    lib_ids = sorted({str(r["librarian_id"]).strip() for r in lib_id_rows})

    cur.execute(
        "SELECT id, branch_number FROM books "
        "WHERE branch_number IS NOT NULL AND library_name_tm = %s AND academic_year = %s "
        "ORDER BY branch_number FOR UPDATE",
        (library_name, year)
    )
    rows = cur.fetchall()

    counter_keys = {lib_id: _counter_key(f"branch:{lib_id}", year) for lib_id in lib_ids}
    counter_olds = {}
    for lib_id, ckey in counter_keys.items():
        cur.execute("SELECT next_value FROM counters WHERE key=%s FOR UPDATE", (ckey,))
        row = cur.fetchone()
        counter_olds[lib_id] = row["next_value"] if row else None

    backup_rows = [{"id": r["id"], "old_branch": r["branch_number"]} for r in rows]

    new_val = new_start
    for r in rows:
        cur.execute("UPDATE books SET branch_number=%s WHERE id=%s", (new_val, r["id"]))
        new_val += 1

    # புத்தகங்கள் ஏதும் இருந்தால் அவற்றுக்கு அடுத்த எண்ணை counter-ஆக வைக்கும்;
    # ஏதும் இல்லை என்றால் new_start-ஐயே தொடக்க counter ஆக வைக்கும்.
    final_counter_val = new_val if rows else new_start
    for lib_id, ckey in counter_keys.items():
        cur.execute(
            "INSERT INTO counters (key, next_value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET next_value=EXCLUDED.next_value",
            (ckey, final_counter_val)
        )
    return backup_rows, counter_olds, len(rows)


@app.route("/api/renumber/branch", methods=["POST"])
@admin_required
def api_renumber_branch():
    data = request.json or {}
    library_name = str(data.get("library_name", "")).strip()
    try:
        new_start = int(data.get("new_start"))
    except Exception:
        return jsonify({"error": "சரியான எண் பதிவிடவும்"}), 400
    if not library_name:
        return jsonify({"error": "நூலகம் தேர்வு செய்யவும்"}), 400
    year = data.get("year") or BASE_YEAR

    with DBConn() as (conn, cur):
        backup_rows, counter_olds, count = _renumber_branch_core(cur, library_name, new_start, year)
        if backup_rows is None:
            return jsonify({"error": "இந்த பெயரில் நூலகமே கிடைக்கவில்லை (master data-ல் இல்லை)"}), 400

        backup_name, _ = _make_backup(
            "branch", backup_rows, "branch:" + ",".join(sorted(counter_olds.keys())) + f":{year}",
            counter_olds, "branch_renumber"
        )

    return jsonify({
        "success": True, "backup_file": backup_name, "renumbered_count": count,
        "message": (
            f"'{library_name}' நூலகத்தின் {count} கிளைப் பதிவெண்கள் ({year}) "
            f"{new_start}-ல் இருந்து மீண்டும் வரிசைப்படுத்தப்பட்டன."
            if count else
            f"'{library_name}' நூலகத்திற்கு {year}-ல் இன்னும் புத்தகங்கள் எதுவும் பிரிக்கப்படவில்லை. "
            f"அடுத்து 'பிரிக்க' செய்யும்போது கிளைப் பதிவெண் {new_start}-ல் இருந்து தொடங்கும்."
        )
    })


@app.route("/api/renumber/branch/library_list")
@admin_required
def api_renumber_branch_library_list():
    """150 நூலகங்களையும் pagination-உடன் திருப்பும் (10/பக்கம், 15 பக்கங்கள்), தேர்ந்தெடுத்த ஆண்டுக்கு மட்டும்."""
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = max(1, min(2000, int(request.args.get("page_size", 10))))
    except Exception:
        page, page_size = 1, 10
    year = request.args.get("year") or BASE_YEAR

    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT COUNT(DISTINCT library_name_tm) AS c FROM books "
            "WHERE library_name_tm IS NOT NULL AND library_name_tm != '' AND academic_year = %s",
            (year,)
        )
        total = cur.fetchone()["c"]

        cur.execute(
            "SELECT library_name_tm, "
            "MIN(branch_number) AS min_branch, MAX(branch_number) AS max_branch, "
            "COUNT(branch_number) AS book_count "
            "FROM books "
            "WHERE library_name_tm IS NOT NULL AND library_name_tm != '' AND academic_year = %s "
            "GROUP BY library_name_tm ORDER BY library_name_tm "
            "LIMIT %s OFFSET %s",
            (year, page_size, (page - 1) * page_size)
        )
        rows = cur.fetchall()

    total_pages = max(1, (total + page_size - 1) // page_size)
    libraries = []
    for i, r in enumerate(rows):
        if r["min_branch"] is None:
            current_label = "பதிவு இல்லை"
        elif r["min_branch"] == r["max_branch"]:
            current_label = str(r["min_branch"])
        else:
            current_label = f"{r['min_branch']} - {r['max_branch']}"
        libraries.append({
            "serial": (page - 1) * page_size + i + 1,
            "library_name": r["library_name_tm"],
            "current_label": current_label,
            "book_count": r["book_count"]
        })

    return jsonify({
        "libraries": libraries, "page": page, "page_size": page_size,
        "total": total, "total_pages": total_pages
    })


@app.route("/api/renumber/branch/bulk_save", methods=["POST"])
@admin_required
def api_renumber_branch_bulk_save():
    """பல நூலகங்களின் கிளைப் பதிவெண்களை ஒரே request-ல் renumber செய்யும்.
    items: [{library_name, new_start}, ...] — காலியாக விட்டவை skip ஆகும்."""
    data = request.json or {}
    items = data.get("items", [])
    year = data.get("year") or BASE_YEAR
    if not items:
        return jsonify({"error": "எந்த நூலகத்திற்கும் புதிய எண் கொடுக்கப்படவில்லை"}), 400

    results, errors = [], []
    combined_rows, combined_counter_olds = [], {}
    renumbered_total = 0

    with DBConn() as (conn, cur):
        for item in items:
            library_name = str(item.get("library_name", "")).strip()
            if not library_name:
                continue
            try:
                new_start = int(item.get("new_start"))
            except Exception:
                errors.append(f"'{library_name}': சரியான எண் இல்லை")
                continue

            backup_rows, counter_olds, count = _renumber_branch_core(cur, library_name, new_start, year)
            if backup_rows is None:
                errors.append(f"'{library_name}': இந்த பெயரில் நூலகமே கிடைக்கவில்லை")
                continue

            combined_rows.extend(backup_rows)
            combined_counter_olds.update(counter_olds)
            renumbered_total += count
            results.append({"library_name": library_name, "new_start": new_start, "count": count})

        backup_name = None
        if combined_rows:
            backup_name, _ = _make_backup(
                "branch", combined_rows, "branch:" + ",".join(sorted(combined_counter_olds.keys())) + f":{year}",
                combined_counter_olds, "branch_bulk_renumber"
            )

    started_only = sum(1 for r in results if r["count"] == 0)
    msg = f"{year} ஆண்டுக்கு {len(results)} நூலகங்களுக்கு புதிய கிளைப் பதிவெண் அமைக்கப்பட்டது ({renumbered_total} புத்தகங்கள் மீண்டும் வரிசைப்படுத்தப்பட்டன)."
    if started_only:
        msg += f"\n({started_only} நூலகங்களுக்கு இன்னும் புத்தகம் பிரிக்கப்படாததால், அடுத்த 'பிரிக்க'-ல் இருந்து புதிய எண் தொடங்கும்.)"
    if errors:
        msg += "\n\nதவிர்க்கப்பட்டவை:\n" + "\n".join(errors)

    return jsonify({
        "success": True, "backup_file": backup_name,
        "results": results, "errors": errors, "message": msg
    })


@app.route("/api/admin/change_password", methods=["POST"])
@admin_required
def api_change_password():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    new_password = data.get("new_password") or ""

    if username not in ("admin", "dclstaff"):
        return jsonify({"error": "இந்த account-க்கு password மாற்ற முடியாது"}), 400
    if len(new_password) < 6:
        return jsonify({"error": "Password குறைந்தது 6 எழுத்துக்கள் இருக்க வேண்டும்"}), 400

    _set_password_hash(username, new_password)
    label = "Admin" if username == "admin" else "DCL Staff"
    return jsonify({"success": True, "message": f"{label}-ன் password வெற்றிகரமாக மாற்றப்பட்டது!"})


@app.route("/api/backups/list")
@admin_required
def api_backups_list():
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT id, filename, created_at, jsonb_array_length(data->'rows') AS row_count, "
            "data->>'type' AS type FROM backups ORDER BY created_at DESC LIMIT 50"
        )
        rows = cur.fetchall()
    type_label = {"central": "மையப்பதிவெண் Renumber", "branch": "கிளைப்பதிவெண் Renumber"}
    return jsonify([{
        "id": r["id"], "filename": r["filename"],
        "created_at": r["created_at"].strftime("%d/%m/%Y %H:%M:%S"),
        "row_count": r["row_count"], "type": r["type"],
        "label": f"{r['created_at'].strftime('%d/%m/%Y %H:%M:%S')} — "
                 f"{type_label.get(r['type'], r['type'])} ({r['row_count']} rows)"
    } for r in rows])


@app.route("/api/backups/restore", methods=["POST"])
@admin_required
def api_backups_restore():
    data = request.json or {}
    filename = data.get("filename") or data.get("id")
    password = data.get("password") or ""
    if not _verify_admin_password(password):
        return jsonify({"error": "தவறான password"}), 403
    if not filename:
        return jsonify({"error": "backup தேர்வு செய்யவும்"}), 400
    with DBConn() as (conn, cur):
        cur.execute("SELECT filename, data FROM backups WHERE filename=%s OR id::text=%s", (filename, str(filename)))
        rec = cur.fetchone()
        if not rec:
            return jsonify({"error": "backup கிடைக்கவில்லை"}), 400
        payload = rec["data"]
        btype = payload.get("type")
        rows = payload.get("rows", [])

        if btype == "central":
            for r in rows:
                cur.execute("UPDATE books SET central_number=%s WHERE id=%s", (r["old_central"], r["id"]))
            if payload.get("counter_key") and payload.get("counter_old_value") is not None:
                cur.execute(
                    "UPDATE counters SET next_value=%s WHERE key=%s",
                    (payload["counter_old_value"], payload["counter_key"])
                )
        elif btype == "branch":
            for r in rows:
                cur.execute("UPDATE books SET branch_number=%s WHERE id=%s", (r["old_branch"], r["id"]))
            counter_olds = payload.get("counter_old_value") or {}
            for lib_id, old_val in counter_olds.items():
                if old_val is not None:
                    cur.execute(
                        "UPDATE counters SET next_value=%s WHERE key=%s",
                        (old_val, f"branch:{lib_id}")
                    )
        else:
            return jsonify({"error": "இந்த வகை backup restore செய்ய முடியாது"}), 400

    return jsonify({"success": True, "message": f"'{rec['filename']}' கொண்டு மீட்டமைக்கப்பட்டது."})


# ==========================================================
# MASTER DATA CLEAR — Admin மட்டும், password கட்டாயம்.
# தேர்ந்தெடுக்கப்பட்ட ஆண்டுக்கு மட்டும் books/counters/reclaimed_central/
# reclaimed_branch/அந்த ஆண்டுக்குரிய renumber backups அழிக்கப்படும் — மற்ற
# ஆண்டுகளின் தரவு பாதிக்கப்படாது. இதன் பின் migrate_excel_to_db.py /
# load_academic_year.py மூலம் cmd prompt-ல் இருந்து புதிதாக ஏற்றலாம்.
# users/settings (login, passwords, active year) தொடப்படாது.
# ==========================================================
@app.route("/api/admin/master_data/clear", methods=["POST"])
@admin_required
def api_master_data_clear():
    data = request.json or {}
    password = data.get("password") or ""
    year = (data.get("year") or _get_setting("active_academic_year", BASE_YEAR) or BASE_YEAR).strip()
    if not _verify_admin_password(password):
        return jsonify({"error": "தவறான password"}), 403

    central_ckey = _counter_key("central_number", year)
    with DBConn() as (conn, cur):
        cur.execute("DELETE FROM books WHERE academic_year=%s", (year,))
        book_count = cur.rowcount

        cur.execute("DELETE FROM reclaimed_central WHERE academic_year=%s", (year,))
        cur.execute("DELETE FROM reclaimed_branch WHERE academic_year=%s", (year,))

        cur.execute("DELETE FROM counters WHERE key=%s", (central_ckey,))
        if year == BASE_YEAR:
            cur.execute("DELETE FROM counters WHERE key LIKE 'branch:%' AND key NOT LIKE 'branch:%:%'")
        else:
            cur.execute("DELETE FROM counters WHERE key LIKE %s", (f"branch:%:{year}",))

        # இந்த ஆண்டுக்குரிய renumber backups (central/branch) மட்டும் நீக்கு —
        # பிற ஆண்டுகளின் backups தொடப்படாது.
        cur.execute(
            "DELETE FROM backups WHERE "
            "(data->>'type' = 'central' AND data->>'counter_key' = %s) "
            "OR (data->>'type' = 'branch' AND data->>'counter_key' LIKE %s)",
            (central_ckey, f"%:{year}")
        )

    # in-memory fuzzy-title cache-ம் இந்த ஆண்டுக்கு பழைய தரவை சுட்டிக்காட்டும் என்பதால் அழி
    _fuzzy_cache.pop(year, None)
    _fuzzy_cache_status.pop(year, None)
    _fuzzy_cache_progress.pop(year, None)

    return jsonify({
        "success": True,
        "message": f"{year} ஆண்டுக்கான Master Data முழுவதும் அழிக்கப்பட்டது ({book_count} பதிவுகள் நீக்கப்பட்டன). "
                   "மற்ற ஆண்டுகளின் தரவு பாதிக்கப்படவில்லை. இப்போது இந்த ஆண்டுக்கு cmd prompt மூலம் "
                   "(migrate_excel_to_db.py அல்லது load_academic_year.py பயன்படுத்தி) புதிதாக தரவு ஏற்றலாம்."
    })


# ==========================================================
# MASTER PUBLISHER CLEAR — Admin மட்டும், password கட்டாயம்.
# தேர்ந்தெடுக்கப்பட்ட ஆண்டில், தேர்ந்தெடுக்கப்பட்ட பதிப்பகத்திற்கு (vendor_name)
# சொந்தமான அனைத்து புத்தகங்களையும் master data-ல் இருந்து முழுமையாக நீக்கும்.
# மற்ற பதிப்பகங்கள் / மற்ற ஆண்டுகள் பாதிக்கப்படாது. ஏற்கனவே central_number /
# branch_number கொடுக்கப்பட்டிருந்தாலும், அந்த எண்கள் reclaim pool-க்கு
# அனுப்பப்படாமல் நேரடியாக நீக்கப்படும் (எண்கள் மீண்டும் பயன்படுத்தப்படாது).
# ==========================================================
@app.route("/api/admin/master_publisher_clear/count")
@admin_required
def api_master_publisher_clear_count():
    vendor = (request.args.get("vendor") or "").strip()
    year = (request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR) or BASE_YEAR).strip()
    if not vendor:
        return jsonify({"error": "பதிப்பகம் கொடுக்கப்படவில்லை"}), 400
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS c FROM books WHERE TRIM(vendor_name)=%s AND academic_year=%s",
            (vendor, year)
        )
        count = cur.fetchone()["c"]
    return jsonify({"vendor": vendor, "year": year, "count": count})


@app.route("/api/admin/master_publisher_clear", methods=["POST"])
@admin_required
def api_master_publisher_clear():
    data = request.json or {}
    vendor = (data.get("vendor") or "").strip()
    password = data.get("password") or ""
    year = (data.get("year") or _get_setting("active_academic_year", BASE_YEAR) or BASE_YEAR).strip()
    if not vendor:
        return jsonify({"error": "பதிப்பகம் கொடுக்கப்படவில்லை"}), 400
    if not _verify_admin_password(password):
        return jsonify({"error": "தவறான password"}), 403

    with DBConn() as (conn, cur):
        cur.execute(
            "DELETE FROM books WHERE TRIM(vendor_name)=%s AND academic_year=%s",
            (vendor, year)
        )
        book_count = cur.rowcount

    if book_count == 0:
        return jsonify({"error": f'"{vendor}" பதிப்பகத்திற்கு {year} ஆண்டில் புத்தகங்கள் இல்லை'}), 400

    return jsonify({
        "success": True,
        "message": f'"{vendor}" பதிப்பகத்தின் {year} ஆண்டுக்குரிய {book_count} புத்தகங்களும் '
                   "master data-ல் இருந்து நீக்கப்பட்டன. மற்ற பதிப்பகங்கள் / ஆண்டுகள் பாதிக்கப்படவில்லை."
    })


# ==========================================================
# MASTER TITLE CHANGE — Admin மட்டும், password கட்டாயம்.
# தேர்ந்தெடுக்கப்பட்ட ஆண்டில், தேர்ந்தெடுக்கப்பட்ட (exact) தலைப்பு + பதிப்பகம்
# இணைவில் உள்ள அனைத்து பிரதிகளின் (10 பிரதிகள் இருந்தாலும் 10-ம்) தலைப்பையும்
# ஒரே நேரத்தில் புதிய தலைப்புக்கு மாற்றும். ஒரே தலைப்பை வெவ்வேறு பதிப்பகங்கள்
# கொடுத்திருந்தால், பதிப்பகத்தை தேர்ந்தெடுத்த பின்னரே மாற்றம் நடக்கும் —
# மற்ற பதிப்பகங்களின் அதே தலைப்பு பாதிக்கப்படாது.
# ==========================================================
@app.route("/api/title_vendors")
@admin_required
def api_title_vendors():
    """தேர்ந்தெடுத்த தலைப்பில் (exact), எந்தெந்த பதிப்பகங்கள் (vendor_name)
    புத்தகங்களை கொடுத்துள்ளன என்பதன் பட்டியலை, ஒவ்வொன்றின் பிரதிகள்
    எண்ணிக்கையுடன் திரும்பும்."""
    title = (request.args.get("title") or "").strip()
    year = (request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR) or BASE_YEAR).strip()
    if not title:
        return jsonify({"error": "தலைப்பு கொடுக்கப்படவில்லை"}), 400
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT COALESCE(NULLIF(TRIM(vendor_name), ''), '(பதிப்பகம் இல்லை)') AS vendor_name, COUNT(*) AS c "
            "FROM books WHERE TRIM(title)=%s AND academic_year=%s "
            "GROUP BY 1 ORDER BY 1",
            (title, year)
        )
        rows = cur.fetchall()
    return jsonify([{"vendor_name": r["vendor_name"], "count": r["c"]} for r in rows])


@app.route("/api/admin/master_title_change/count")
@admin_required
def api_master_title_change_count():
    title = (request.args.get("title") or "").strip()
    vendor = (request.args.get("vendor") or "").strip()
    book_id = (request.args.get("book_id") or "").strip()
    year = (request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR) or BASE_YEAR).strip()
    if not title:
        return jsonify({"error": "தலைப்பு கொடுக்கப்படவில்லை"}), 400
    if not vendor:
        return jsonify({"error": "பதிப்பகம் கொடுக்கப்படவில்லை"}), 400

    no_vendor = (vendor == "(பதிப்பகம் இல்லை)")
    with DBConn() as (conn, cur):
        # ஒரே title+vendor+year குழுவில் Book Id வாரியாக பிரிக்கப்பட்ட எண்ணிக்கை.
        # ஒரே title+publisher-ல் வெவ்வேறு Book Id (விலை variant) இருந்தால், அவை
        # தனித்தனியாகவே காட்டப்பட வேண்டும் — சேர்த்து காட்டக்கூடாது.
        base_where = "TRIM(title)=%s AND academic_year=%s AND (vendor_name IS NULL OR TRIM(vendor_name) = '')" if no_vendor \
            else "TRIM(title)=%s AND TRIM(vendor_name)=%s AND academic_year=%s"
        base_params = (title, year) if no_vendor else (title, vendor, year)

        cur.execute(
            f"SELECT COALESCE(NULLIF(TRIM(book_id), ''), NULL) AS bid, COUNT(*) AS c "
            f"FROM books WHERE {base_where} GROUP BY 1 ORDER BY 1 NULLS LAST",
            base_params
        )
        rows = cur.fetchall()
        book_ids = [{"book_id": r["bid"], "count": r["c"]} for r in rows]
        total_count = sum(r["c"] for r in rows)

        if book_id:
            # ஒரு குறிப்பிட்ட Book Id தேர்ந்தெடுக்கப்பட்டிருந்தால், அதற்குரிய எண்ணிக்கை மட்டும்.
            cur.execute(
                f"SELECT COUNT(*) AS c FROM books WHERE {base_where} AND TRIM(book_id)=%s",
                base_params + (book_id,)
            )
            count = cur.fetchone()["c"]
        elif len(book_ids) <= 1:
            count = total_count
        else:
            count = None  # Admin இன்னும் Book Id தேர்ந்தெடுக்கவில்லை

    return jsonify({
        "title": title, "vendor": vendor, "year": year,
        "count": count, "total_count": total_count, "book_ids": book_ids
    })


@app.route("/api/admin/master_title_change", methods=["POST"])
@admin_required
def api_master_title_change():
    data = request.json or {}
    old_title = (data.get("old_title") or "").strip()
    vendor = (data.get("vendor") or "").strip()
    book_id = (data.get("book_id") or "").strip()
    new_title = (data.get("new_title") or "").strip()
    password = data.get("password") or ""
    year = (data.get("year") or _get_setting("active_academic_year", BASE_YEAR) or BASE_YEAR).strip()
    if not old_title:
        return jsonify({"error": "தற்போதைய தலைப்பு கொடுக்கப்படவில்லை"}), 400
    if not vendor:
        return jsonify({"error": "பதிப்பகம் கொடுக்கப்படவில்லை"}), 400
    if not new_title:
        return jsonify({"error": "புதிய தலைப்பு கொடுக்கப்படவில்லை"}), 400
    if not _verify_admin_password(password):
        return jsonify({"error": "தவறான password"}), 403

    no_vendor = (vendor == "(பதிப்பகம் இல்லை)")
    with DBConn() as (conn, cur):
        try:
            # ஒரே title+vendor குழுவில் ஒன்றுக்கும் மேற்பட்ட Book Id இருந்தால், Admin
            # ஒரு Book Id-ஐ தேர்ந்தெடுத்திருக்க வேண்டும் — இல்லையெனில் தடுக்கப்படும்
            # (அனைத்து Book Id-களும் சேர்த்து தவறாக update ஆகாமல் இருக்க).
            base_where = "TRIM(title)=%s AND academic_year=%s AND (vendor_name IS NULL OR TRIM(vendor_name) = '')" if no_vendor \
                else "TRIM(title)=%s AND TRIM(vendor_name)=%s AND academic_year=%s"
            base_params = (old_title, year) if no_vendor else (old_title, vendor, year)

            if not book_id:
                cur.execute(f"SELECT COUNT(DISTINCT NULLIF(TRIM(book_id), '')) AS c FROM books WHERE {base_where}", base_params)
                distinct_book_ids = cur.fetchone()["c"]
                if distinct_book_ids > 1:
                    conn.rollback()
                    return jsonify({"error": "இந்த தலைப்பில் ஒன்றுக்கும் மேற்பட்ட Book Id உள்ளது — எந்த Book Id-க்கு மாற்ற வேண்டும் என தேர்ந்தெடுக்கவும்"}), 400
                cur.execute(f"UPDATE books SET title=%s WHERE {base_where}", (new_title,) + base_params)
            else:
                cur.execute(f"UPDATE books SET title=%s WHERE {base_where} AND TRIM(book_id)=%s", (new_title,) + base_params + (book_id,))
            updated = cur.rowcount
            conn.commit()
        except Exception as e:
            conn.rollback()
            return jsonify({"error": f"பிழை: {e}"}), 500

    if updated == 0:
        return jsonify({"error": f'"{old_title}" தலைப்பில் ({vendor}) {year} ஆண்டில் புத்தகங்கள் இல்லை'}), 400

    bid_note = f' (Book Id: {book_id})' if book_id else ''
    return jsonify({
        "success": True,
        "message": f'"{old_title}" தலைப்பில் ({vendor}){bid_note} உள்ள {year} ஆண்டுக்குரிய {updated} பிரதிகளும் '
                   f'"{new_title}" எனப் புதுப்பிக்கப்பட்டன. மற்ற Book Id / பதிப்பகங்களின் அதே தலைப்பு பாதிக்கப்படவில்லை.'
    })


# ==========================================================
# MASTER ASSIGNING DATA CLEAR — Admin மட்டும், password கட்டாயம்.
# கொடுக்கப்பட்ட ஆண்டுக்கு இதுவரை 'பிரிக்க'(assign)/'அனுப்பு'(send) செய்யப்பட்ட
# அனைத்தையும் அழித்து, புத்தகங்களை மீண்டும் unassigned நிலைக்கு கொண்டுவரும்.
# "தவறான பதிவு நீக்கம்" (Reclaim) போலல்லாமல் — விடுவிக்கப்படும் central/branch
# எண்கள் reclaim pool-க்கு அனுப்பப்படாது; மாறாக அந்த ஆண்டுக்கான pool
# (reclaimed_central/reclaimed_branch, ஏற்கனவே ஏதேனும் இருந்தாலும்) மற்றும்
# counters முழுவதுமாக அழிக்கப்பட்டு, அடுத்த பிரிப்பு 1-ல் இருந்தே புதிதாக தொடங்கும்.
# ==========================================================
@app.route("/api/admin/master_data/assign_clear", methods=["POST"])
@admin_required
def api_master_data_assign_clear():
    data = request.json or {}
    password = data.get("password") or ""
    year = (data.get("year") or _get_setting("active_academic_year", BASE_YEAR) or BASE_YEAR).strip()
    if not _verify_admin_password(password):
        return jsonify({"error": "தவறான password"}), 403

    central_ckey = _counter_key("central_number", year)
    with DBConn() as (conn, cur):
        cur.execute(
            "UPDATE books SET set_number=NULL, central_number=NULL, branch_number=NULL, "
            "work_status=NULL, sent_details=NULL, date=NULL, locked_by=NULL, locked_at=NULL "
            "WHERE academic_year=%s",
            (year,)
        )
        cleared_books = cur.rowcount

        cur.execute("DELETE FROM reclaimed_central WHERE academic_year=%s", (year,))
        cur.execute("DELETE FROM reclaimed_branch WHERE academic_year=%s", (year,))

        cur.execute("DELETE FROM counters WHERE key=%s", (central_ckey,))
        if year == BASE_YEAR:
            cur.execute("DELETE FROM counters WHERE key LIKE 'branch:%' AND key NOT LIKE 'branch:%:%'")
        else:
            cur.execute("DELETE FROM counters WHERE key LIKE %s", (f"branch:%:{year}",))

    return jsonify({
        "success": True,
        "message": f"{year} ஆண்டுக்கான assign/send தரவு முழுவதும் அழிக்கப்பட்டது "
                   f"({cleared_books} புத்தகங்கள் மீண்டும் 'பிரிக்க' நிலைக்கு வந்தன). "
                   "Central Number / Branch Number spool-ம் காலி செய்யப்பட்டது — "
                   "அடுத்த பிரிப்பு 1-ல் இருந்தே புதிதாக தொடங்கும்."
    })


# ==========================================================
# EXCEL பதிவிறக்கம் — Admin மட்டும் (staff/librarian-க்கு அனுமதி இல்லை)
#   type=assigned       → பிரிக்க மட்டும் செய்த (இன்னும் அனுப்பாத) நூல்கள்
#   type=assigned_sent  → பிரிக்க + அனுப்ப இரண்டும் முடிந்த நூல்கள்
#   type=total          → அப்லோட் செய்த மொத்த தரவும் (தற்போதைய நிலையுடன்,
#                          assign-send ஆகாதவை உட்பட)
# மூன்று வகையிலும் rows, Excel-ல் எப்படி அப்லோட்/append செய்யப்பட்டதோ
# அதே வரிசையில் (id ASC) வரும்.
# ==========================================================
# master_data.xlsx-ல் இருந்த அதே column பெயர்கள் + அதே வரிசை (Admin download-க்கு).
# (db_column, excel_header) — SELECT-லும் இதே வரிசை, DataFrame-லும் இதே வரிசை.
_EXCEL_COLUMNS = [
    ("state_acc_number", "STATE ACCESSION NUMBER"),
    ("book_id", "BOOK_ID"),
    ("title", "TITLE"),
    ("author", "AUTHOR"),
    ("isbn", "Isbn"),
    ("publication_name", "Publication Name"),
    ("vendor_name", "VENDOR_NAME"),
    ("library_type", "LIBRARY_TYPE"),
    ("librarian_id", "LIBRARIAN_ID"),
    ("library_name", "Library Name"),
    ("year_pub", "YEAR OF PUBLICATION"),
    ("library_name_tm", "LIBRARY_NAME_TM"),
    ("price", "PRICE"),
    ("set_number", "SET_NUMBER"),
    ("central_number", "CENTRAL_NUMBER"),
    ("sent_details", "SENT_DETAILS"),
    ("date", "DATE"),
    ("branch_number", "BRANCH_NUMBER"),
    ("accepted_price", "ACCEPTED PRICE"),
    ("state_acc_number_1", "STATE ACCESSIONNUMBER.1"),
    ("work_status", "WORK_STATUS"),
]

# ==========================================================
# மாநிலப் பதிவெண் (state_acc_number) மட்டும் Bulk Update செய்ய —
# Download template-ல் ID கட்டாயம் இருக்க வேண்டும் (Upload-ல் இதை
# வைத்தே UPDATE செய்யப்படும், புதிய rows INSERT ஆகாது).
# பிரித்த/பிரிக்காத அனைத்து புத்தகங்களும் இதில் இடம்பெறும்.
# ==========================================================
_STATE_ACC_TEMPLATE_COLUMNS = [
    ("id", "ID"),
    ("state_acc_number", "STATE ACCESSION NUMBER"),
    ("title", "TITLE"),
    ("author", "AUTHOR"),
    ("vendor_name", "VENDOR_NAME"),
    ("library_name_tm", "LIBRARY_NAME_TM"),
    ("central_number", "CENTRAL_NUMBER"),
    ("branch_number", "BRANCH_NUMBER"),
]


# ==========================================================
# EXCEL UPLOAD (Admin) — master_data_2025-2026.xlsx போன்று பெயரிட்டு
# அப்லோட் செய்தால், பெயரில் இருந்தே ஆண்டு (YYYY-YYYY) தானாக கண்டறியப்பட்டு
# அந்த rows அந்த ஆண்டுக்கே சேரும். இருக்கும் data தொடப்படாது (append மட்டும்).
# பெயரில் ஆண்டு பொருந்தவில்லை என்றால், form-ல் "year" அனுப்ப வேண்டும்.
# ==========================================================
_YEAR_FROM_FILENAME_RE = re.compile(r"(20\d{2}-20\d{2})")


@app.route("/api/admin/upload_excel/detect_year", methods=["POST"])
@admin_required
def api_upload_excel_detect_year():
    filename = (request.json or {}).get("filename", "")
    m = _YEAR_FROM_FILENAME_RE.search(filename)
    return jsonify({"year": m.group(1) if m else None})


@app.route("/api/admin/upload_excel", methods=["POST"])
@admin_required
def api_admin_upload_excel():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Excel கோப்பு தேர்ந்தெடுக்கவும்"}), 400

    year = (request.form.get("year") or "").strip()
    if not year:
        m = _YEAR_FROM_FILENAME_RE.search(f.filename)
        if m:
            year = m.group(1)
    if not year:
        return jsonify({"error": "கோப்பு பெயரில் இருந்து ஆண்டு கண்டறிய முடியவில்லை — ஆண்டைத் தேர்ந்தெடுக்கவும்"}), 400

    try:
        df = pd.read_excel(f)
    except Exception as e:
        return jsonify({"error": f"Excel படிக்க முடியவில்லை: {e}"}), 400

    rename_map = {
        'librarianId': 'LIBRARIAN_ID', 'Library Name': 'LIBRARY_NAME',
        'BRANCH NUMBER': 'BRANCH_NUMBER', 'WORK STATUS': 'WORK_STATUS',
        'SENT DETAILS': 'SENT_DETAILS',
    }
    df = df.rename(columns=rename_map, errors='ignore')

    def _val(row, colname):
        v = row.get(colname)
        if pd.isna(v):
            return None
        return str(v).strip()

    def _intval(row, colname):
        v = row.get(colname)
        try:
            if pd.isna(v):
                return None
            return int(float(v))
        except Exception:
            return None

    rows = []
    for i in range(len(df)):
        row = df.iloc[i]
        rows.append((
            _val(row, 'TITLE'), _val(row, 'PRICE'), _val(row, 'AUTHOR'), _val(row, 'VENDOR_NAME'),
            _val(row, 'LIBRARY_TYPE'), _val(row, 'LIBRARY_NAME_TM'), _val(row, 'LIBRARY_NAME'),
            _val(row, 'LIBRARIAN_ID'), _intval(row, 'CENTRAL_NUMBER'), _intval(row, 'BRANCH_NUMBER'),
            _val(row, 'SET_NUMBER'), _val(row, 'WORK_STATUS'), _val(row, 'SENT_DETAILS'), _val(row, 'DATE'),
            _val(row, 'STATE ACCESSION NUMBER') or _val(row, 'STATE_ACC') or _val(row, 'STATE ACC'),
            _val(row, 'YEAR_PUB') or _val(row, 'YEAR OF PUBLICATION') or _val(row, 'Year of Publication'),
            _val(row, 'ACCEPTED_PRICE') or _val(row, 'ACCEPTED PRICE') or _val(row, 'Accepted Price'),
            _val(row, 'BOOK_ID'), _val(row, 'Isbn') or _val(row, 'ISBN'),
            _val(row, 'Publication Name') or _val(row, 'PUBLICATION_NAME'),
            _val(row, 'STATE ACCESSIONNUMBER.1') or _val(row, 'STATE ACCESSION NUMBER.1'),
            year,
        ))

    if not rows:
        return jsonify({"error": "Excel-ல் rows எதுவும் இல்லை"}), 400

    with DBConn() as (conn, cur):
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

    return jsonify({
        "success": True,
        "year": year,
        "count": len(rows),
        "message": f"{len(rows):,} புத்தகங்கள் {year} ஆண்டுக்கு சேர்க்கப்பட்டன. (இருக்கும் data தொடப்படவில்லை)"
    })


# ==========================================================
# மாநிலப் பதிவெண் (state_acc_number) Bulk UPDATE — Admin மட்டும்.
# "மாநிலப் பதிவெண் Template" Excel-ஐ (ID + STATE ACCESSION NUMBER)
# அப்லோட் செய்தால், ID வைத்து UPDATE மட்டும் செய்யப்படும் — புதிய
# rows INSERT ஆகாது, duplicate வராது. காலியான rows தவிர்க்கப்படும்.
# ==========================================================
@app.route("/api/admin/upload_state_acc_update", methods=["POST"])
@admin_required
def api_admin_upload_state_acc_update():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Excel கோப்பு தேர்ந்தெடுக்கவும்"}), 400

    try:
        df = pd.read_excel(f)
    except Exception as e:
        return jsonify({"error": f"Excel படிக்க முடியவில்லை: {e}"}), 400

    df = df.rename(columns={c: str(c).strip().upper() for c in df.columns})

    id_col = "ID" if "ID" in df.columns else None
    state_col = None
    for cand in ("STATE ACCESSION NUMBER", "STATE_ACC_NUMBER", "STATE ACC NUMBER", "STATE ACC"):
        if cand in df.columns:
            state_col = cand
            break

    if not id_col or not state_col:
        return jsonify({"error": "Excel-ல் 'ID' மற்றும் 'STATE ACCESSION NUMBER' column-கள் கட்டாயம் இருக்க வேண்டும் — 'மாநிலப் பதிவெண் Template' Download செய்து அதையே பயன்படுத்தவும்."}), 400

    updates = []
    skipped_blank = 0
    skipped_bad_id = 0
    for i in range(len(df)):
        row = df.iloc[i]
        raw_id = row.get(id_col)
        raw_val = row.get(state_col)
        if pd.isna(raw_id):
            continue
        try:
            book_id = int(float(raw_id))
        except Exception:
            skipped_bad_id += 1
            continue
        if pd.isna(raw_val) or str(raw_val).strip() == "":
            skipped_blank += 1
            continue
        updates.append((book_id, str(raw_val).strip()))

    if not updates:
        return jsonify({"error": "புதுப்பிக்க தகுதியான rows எதுவும் இல்லை — 'STATE ACCESSION NUMBER' column காலியாக உள்ளது"}), 400

    updated = 0
    CHUNK = 2000
    with DBConn() as (conn, cur):
        for i in range(0, len(updates), CHUNK):
            batch = updates[i:i + CHUNK]
            values_str = ",".join(
                cur.mogrify("(%s,%s)", r).decode("utf-8") for r in batch
            )
            cur.execute(
                "UPDATE books AS b SET state_acc_number = v.val "
                f"FROM (VALUES {values_str}) AS v(id, val) "
                "WHERE b.id = v.id"
            )
            updated += cur.rowcount

    msg = f"{updated:,} புத்தகங்களுக்கு மாநிலப் பதிவெண் புதுப்பிக்கப்பட்டது."
    extra = []
    if skipped_blank:
        extra.append(f"{skipped_blank:,} rows காலியாக இருந்ததால் தவிர்க்கப்பட்டன")
    if skipped_bad_id:
        extra.append(f"{skipped_bad_id:,} rows-ல் தவறான ID இருந்ததால் தவிர்க்கப்பட்டன")
    if extra:
        msg += " (" + ", ".join(extra) + ")"

    return jsonify({"success": True, "updated": updated, "skipped_blank": skipped_blank,
                     "skipped_bad_id": skipped_bad_id, "message": msg})


_excel_export_jobs = {}   # (dtype, year) -> {"status": running|done|error, "path": str, "fname": str, "error": str}


def _build_excel_export_job(app_ctx, dtype, year, where, fname_prefix, columns=None):
    key = (dtype, year)
    _excel_export_jobs[key] = {"status": "running"}
    try:
        with app_ctx.app_context():
            from openpyxl import Workbook
            from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

            def _clean(v):
                # 2024-2025 legacy data (migrated from the old Excel sheets) has
                # control characters in some title/author cells that are invalid
                # in XML — openpyxl throws IllegalCharacterError on these.
                if isinstance(v, str):
                    return ILLEGAL_CHARACTERS_RE.sub('', v)
                return v

            cols = columns or _EXCEL_COLUMNS
            db_col_names = [c for c, _ in cols]
            # id பாஜினேஷனுக்கு கட்டாயம் தேவை — column list-ல் ஏற்கனவே இல்லையென்றால் தனியாக சேர்க்கவும்
            select_cols = db_col_names if "id" in db_col_names else (["id"] + db_col_names)
            db_cols = ", ".join(select_cols)
            excel_headers = [h for _, h in cols]

            wb = Workbook(write_only=True)
            ws = wb.create_sheet("Data")
            ws.append(excel_headers)

            # Keyset pagination (id > last_id) instead of one big fetchall() —
            # keeps memory bounded even for the 78,000+ row 2024-2025 dataset.
            CHUNK = 5000
            last_id = 0
            with DBConn() as (conn, cur):
                while True:
                    cur.execute(
                        f"SELECT {db_cols} FROM books WHERE {where} AND id > %s "
                        f"ORDER BY id ASC LIMIT %s",
                        (year, last_id, CHUNK)
                    )
                    batch = cur.fetchall()
                    if not batch:
                        break
                    for r in batch:
                        ws.append([_clean(r.get(c)) for c in db_col_names])
                    last_id = batch[-1]["id"]

            ts = datetime.now().strftime("%d-%m-%Y_%H-%M")
            fname = f"{fname_prefix}_{year}_{ts}.xlsx"
            tmp_path = os.path.join(tempfile.gettempdir(), f"excel_export_{uuid.uuid4().hex}.xlsx")
            wb.save(tmp_path)
            _excel_export_jobs[key] = {"status": "done", "path": tmp_path, "fname": fname}
    except Exception as e:
        print(f"download_excel error ({dtype}, {year}): {e}")
        _excel_export_jobs[key] = {"status": "error", "error": str(e)}


def _excel_export_where(dtype):
    if dtype == "assigned":
        return f"(set_number IS NOT NULL AND TRIM(set_number) != '') AND {_UNSENT_SQL} AND academic_year = %s", "assigned_only"
    elif dtype == "assigned_sent":
        return f"(set_number IS NOT NULL AND TRIM(set_number) != '') AND {_SENT_SQL} AND academic_year = %s", "assigned_and_sent"
    elif dtype == "total":
        return "academic_year = %s", "total_data"
    elif dtype == "state_acc_template":
        # பிரித்த/பிரிக்காத அத்தனை புத்தகங்களும் — மாநிலப் பதிவெண் Bulk Update-க்கு
        return "academic_year = %s", "state_acc_template"
    return None, None


@app.route("/api/admin/download_excel/start")
@admin_required
def api_admin_download_excel_start():
    dtype = (request.args.get("type") or "total").strip().lower()
    year = request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    where, fname_prefix = _excel_export_where(dtype)
    if where is None:
        return jsonify({"error": "தவறான வகை"}), 400

    key = (dtype, year)
    status = _excel_export_jobs.get(key, {}).get("status")
    if status == "running":
        return jsonify({"status": "running"})
    columns = _STATE_ACC_TEMPLATE_COLUMNS if dtype == "state_acc_template" else None
    # "done"/"error" state-ஐயும் மீண்டும் build செய்யும் — தரவு மாறியிருக்கலாம்
    threading.Thread(target=_build_excel_export_job, args=(app, dtype, year, where, fname_prefix, columns), daemon=True).start()
    return jsonify({"status": "running"})


@app.route("/api/admin/download_excel/status")
@admin_required
def api_admin_download_excel_status():
    dtype = (request.args.get("type") or "total").strip().lower()
    year = request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    job = _excel_export_jobs.get((dtype, year), {"status": "idle"})
    if job.get("status") == "error":
        return jsonify({"status": "error", "error": job.get("error")})
    if job.get("status") == "done":
        return jsonify({"status": "done"})
    return jsonify({"status": job.get("status", "idle")})


@app.route("/api/admin/download_excel/file")
@admin_required
def api_admin_download_excel_file():
    dtype = (request.args.get("type") or "total").strip().lower()
    year = request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    job = _excel_export_jobs.get((dtype, year))
    if not job or job.get("status") != "done" or not os.path.exists(job.get("path", "")):
        return jsonify({"error": "கோப்பு இன்னும் தயார் இல்லை"}), 400
    return send_file(
        job["path"],
        as_attachment=True,
        download_name=job["fname"],
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ==========================================================
# REPORTS — HTML அறிக்கை server memory-ல் தற்காலிகமா (in-memory, DB-ல்
# இல்லை) வெச்சு, Frontend அதை புதிய tab-ல் திறக்கும் (பயனர் Ctrl+P →
# Save as PDF செய்யலாம்). Neon storage-ஐ சேமிக்க DB-ல் இனி save ஆகாது;
# ஒரு குறிப்பிட்ட நேரத்துக்கு (REPORT_TTL_SECONDS) மேல் தானாகவே அழிந்துவிடும்.
# ==========================================================
_reports_cache = {}
_reports_cache_lock = threading.Lock()
_report_id_counter = itertools.count(1)
REPORT_TTL_SECONDS = 2 * 60 * 60  # 2 மணி நேரம் — அதுக்குள் பார்த்துக்கணும்


def _cleanup_old_reports():
    cutoff = time.time() - REPORT_TTL_SECONDS
    expired = [rid for rid, r in _reports_cache.items() if r["created_at"] < cutoff]
    for rid in expired:
        _reports_cache.pop(rid, None)


def _save_report(html, title):
    with _reports_cache_lock:
        _cleanup_old_reports()
        rid = next(_report_id_counter)
        _reports_cache[rid] = {"html": html, "title": title, "created_at": time.time()}
    return rid


@app.route("/reports/view/<int:report_id>")
@login_required
def view_report(report_id):
    with _reports_cache_lock:
        row = _reports_cache.get(report_id)
    if not row:
        return "அறிக்கை கிடைக்கவில்லை (அல்லது 2 மணி நேரம் கடந்து காலாவதியானது — மீண்டும் generate செய்யவும்)", 404
    return row["html"]


# ==========================================================
# அறிக்கை HTML-ஐ Excel (.xlsx) ஆக மாற்றும் generic (பொதுவான) helper
# ==========================================================
class _ReportError(Exception):
    def __init__(self, message, status=200):
        super().__init__(message)
        self.message = message
        self.status = status


from html.parser import HTMLParser as _HTMLParser
import html as _html_lib


class _ReportTableParser(_HTMLParser):
    """report HTML-ல் இருக்கும் .t1..t5 தலைப்பு வரிகளையும், <table> உள் <tr>
    வரிசைகளையும் (thead/tbody வேறுபாடு + rowspan/colspan உடன்) பிரித்தெடுக்கும்."""
    def __init__(self):
        super().__init__()
        self.titles = []
        self.rows = []  # list of (cells, is_header); cells: list of dict(text, rowspan, colspan)
        self._in_thead = False
        self._row = None
        self._cell = None
        self._title_capture = False
        self._title_buf = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = d.get('class', '')
        if tag == 'thead':
            self._in_thead = True
        elif tag == 'tr':
            self._row = []
        elif tag in ('td', 'th'):
            try:
                rs = int(d.get('rowspan', 1) or 1)
            except ValueError:
                rs = 1
            try:
                cs = int(d.get('colspan', 1) or 1)
            except ValueError:
                cs = 1
            self._cell = {'text': '', 'rowspan': rs, 'colspan': cs}
        elif tag == 'p' and cls in ('t1', 't2', 't3', 't4', 't5'):
            self._title_capture = True
            self._title_buf = ''
        elif tag == 'br' and self._cell is not None:
            self._cell['text'] += ' '

    def handle_endtag(self, tag):
        if tag == 'thead':
            self._in_thead = False
        elif tag in ('td', 'th') and self._cell is not None:
            self._row.append(self._cell)
            self._cell = None
        elif tag == 'tr' and self._row is not None:
            self.rows.append((self._row, self._in_thead))
            self._row = None
        elif tag == 'p' and self._title_capture:
            t = _html_lib.unescape(self._title_buf).strip()
            if t:
                self.titles.append(t)
            self._title_capture = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell['text'] += data
        elif self._title_capture:
            self._title_buf += data


def _flatten_report_rows(rows):
    """rowspan/colspan-ஐ grid ஆக விரிக்கிறது. Returns list of (dict(col->text), is_header)."""
    grid_rows = []
    carry = {}  # col -> [remaining_rows, text]
    for cells, is_header in rows:
        grid = {}
        col = 0
        ci = 0
        n = len(cells)
        while ci < n or col <= max(carry.keys(), default=-1):
            if col in carry:
                remaining, text = carry[col]
                grid[col] = text
                if remaining - 1 <= 0:
                    del carry[col]
                else:
                    carry[col] = [remaining - 1, text]
                col += 1
                continue
            if ci >= n:
                break
            c = cells[ci]
            ci += 1
            text = re.sub(r'\s+', ' ', _html_lib.unescape(c['text']).strip())
            grid[col] = text
            if c['rowspan'] > 1:
                carry[col] = [c['rowspan'] - 1, text]
            for extra in range(1, c['colspan']):
                grid[col + extra] = ''
            col += c['colspan']
        grid_rows.append((grid, is_header))
    return grid_rows


def _write_report_sheet(ws, titles, grid_rows):
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter
    max_col = max([max(g.keys(), default=-1) for g, _ in grid_rows] + [0]) + 1
    r = 1
    for t in titles:
        ws.cell(row=r, column=1, value=t).font = Font(bold=True, size=12)
        if max_col > 1:
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=max_col)
        r += 1
    if titles:
        r += 1
    header_fill = PatternFill(start_color="D0E8FF", end_color="D0E8FF", fill_type="solid")
    for grid, is_header in grid_rows:
        for c in range(max_col):
            val = grid.get(c, '')
            cell = ws.cell(row=r, column=c + 1, value=val)
            if is_header:
                cell.font = Font(bold=True)
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            else:
                cell.alignment = Alignment(horizontal='left' if c <= 1 else 'center', vertical='center')
        r += 1
    for c in range(1, max_col + 1):
        ws.column_dimensions[get_column_letter(c)].width = 22 if c <= 2 else 14


def _report_html_to_workbook(html_sections):
    """html_sections: list of (sheet_title, html) — ஒரு sheet-க்கு ஒரு (title, html)."""
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    used_titles = set()
    for sheet_title, html in html_sections:
        st = (sheet_title or "Report")[:31] or "Report"
        base, n = st, 2
        while st in used_titles:
            st = f"{base[:28]}_{n}"
            n += 1
        used_titles.add(st)
        parser = _ReportTableParser()
        parser.feed(html)
        grid_rows = _flatten_report_rows(parser.rows)
        ws = wb.create_sheet(title=st)
        _write_report_sheet(ws, parser.titles, grid_rows)
    return wb


def _workbook_response(wb, filename):
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(
        bio, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ==========================================================
# REPORTS — HTML அறிக்கை உருவாக்கி DB-ல் சேமிக்கப்பட்டு, Frontend அதை
# புதிய tab-ல் திறக்கும் (பயனர் Ctrl+P → Save as PDF செய்யலாம்)
# ==========================================================
def _build_report_html(num, year, rtype=None):
    """அறிக்கை HTML-ஐ உருவாக்கி string ஆக திருப்பும். data இல்லை என்றால் _ReportError raise செய்யும்."""
    today_str = datetime.now().strftime("%d/%m/%Y")
    with DBConn() as (conn, cur):
            if num == 1:
                cur.execute(
                    "SELECT work_status AS ws, "
                    "COUNT(DISTINCT NULLIF(TRIM(vendor_name),'')) AS vendor_count, "
                    "COUNT(*) AS book_count FROM books "
                    "WHERE work_status IS NOT NULL AND work_status != '' AND academic_year = %s "
                    "GROUP BY work_status "
                    "ORDER BY TO_DATE(work_status, 'DD/MM/YYYY')",
                    (year,)
                )
                rows = cur.fetchall()
                if not rows:
                    raise _ReportError("இன்னும் எந்த பணியும் பதிவு செய்யப்படவில்லை")
                table_rows = "".join(
                    f"<tr><td>{i}</td><td>{r['ws']}</td><td>{r['vendor_count']}</td><td>{r['book_count']}</td></tr>"
                    for i, r in enumerate(rows, 1)
                )
                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 1 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p><p class="t2">மாவட்ட மைய நூலகம்</p>
<p class="t3">2026-2027 புதிய நூல்கள் பகிர்மானப் பணி</p><p class="t4">தேதி வாரியாக பணியாளர்கள் பணி செய்த விவரம்</p>
<p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th>வ.எண்</th><th>தேதி</th><th>பிரிக்கப்பட்ட பதிப்பகங்கள்</th><th>பிரிக்கப்பட்ட நூல்கள்</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""

            elif num == 2:
                _CNT2_SQL = (
                    "SELECT COUNT(*) AS c, COUNT(DISTINCT NULLIF(TRIM(vendor_name),'')) AS v, "
                    f"COUNT(*) FILTER (WHERE {_TAMIL_TITLE_SQL}) AS tc "
                    "FROM books "
                )
                cur.execute(_CNT2_SQL + "WHERE academic_year = %s", (year,))
                total = cur.fetchone()
                cur.execute(
                    _CNT2_SQL + "WHERE (set_number IS NOT NULL AND set_number != '') AND academic_year = %s",
                    (year,)
                )
                assigned = cur.fetchone()
                cur.execute(
                    _CNT2_SQL + "WHERE (set_number IS NULL OR set_number = '') AND academic_year = %s",
                    (year,)
                )
                pending = cur.fetchone()
                cur.execute(
                    _CNT2_SQL + f"WHERE ({_SENT_SQL}) AND academic_year = %s",
                    (year,)
                )
                sent = cur.fetchone()
                pending_send = assigned["c"] - sent["c"]
                pending_send_tm = assigned["tc"] - sent["tc"]
                pending_send_en = pending_send - pending_send_tm
                # (label, vendor_count, tamil_count, english_count)
                rows = [
                    ("பெறப்பட்டது", total["v"], total["tc"], total["c"] - total["tc"]),
                    ("பிரிக்கப்பட்டது", assigned["v"], assigned["tc"], assigned["c"] - assigned["tc"]),
                    ("பிரிக்கப்பட வேண்டியது", pending["v"], pending["tc"], pending["c"] - pending["tc"]),
                    ("அனுப்பப்பட்டது", sent["v"], sent["tc"], sent["c"] - sent["tc"]),
                    ("அனுப்ப வேண்டியது", "-", pending_send_tm, pending_send_en),
                ]
                tr = "".join(
                    f"<tr><td>{i}</td><td style='text-align:left'>{l}</td><td>{vc}</td><td>{tmc}</td><td>{enc}</td><td>{tmc + enc}</td></tr>"
                    for i, (l, vc, tmc, enc) in enumerate(rows, 1)
                )
                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 2 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p><p class="t2">மாவட்ட மைய நூலகம்</p>
<p class="t3">2026-2027 புதிய நூல்கள் — மொத்த நிலை விவரம்</p><p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th>வ.எண்</th><th>விவரம்</th><th>பதிப்பகங்கள்</th><th>தமிழ்</th><th>ஆங்கிலம்</th><th>மொத்தம்</th></tr></thead>
<tbody>{tr}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""

            elif num == 3:
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(library_type),''), 'பிற') AS lt,
                           COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),''), 'தெரியாத நூலகம்') AS ln,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE {_TAMIL_TITLE_SQL}) AS total_tm,
                           COUNT(*) FILTER (WHERE set_number IS NOT NULL AND set_number != '') AS assigned,
                           COUNT(*) FILTER (WHERE (set_number IS NOT NULL AND set_number != '') AND {_TAMIL_TITLE_SQL}) AS assigned_tm,
                           COUNT(*) FILTER (WHERE {_SENT_SQL}) AS sent,
                           COUNT(*) FILTER (WHERE ({_SENT_SQL}) AND {_TAMIL_TITLE_SQL}) AS sent_tm
                    FROM books WHERE academic_year = %s GROUP BY lt, ln
                """, (year,))
                lib_rows = cur.fetchall()
                lt_order = []
                for r in lib_rows:
                    if r["lt"] not in lt_order:
                        lt_order.append(r["lt"])

                def _split15(total, total_tm, assigned, assigned_tm, sent, sent_tm):
                    # வரிசை: பெறப்பட்டது(த,ஆ,மொ), பிரிக்கப்பட்டது(த,ஆ,மொ), மீதம்(த,ஆ,மொ),
                    #        அனுப்பப்பட்டது(த,ஆ,மொ), அனுப்ப வேண்டியது(த,ஆ,மொ)
                    pending, pending_tm = total - assigned, total_tm - assigned_tm
                    ps, ps_tm = assigned - sent, assigned_tm - sent_tm
                    return (
                        total_tm, total - total_tm, total,
                        assigned_tm, assigned - assigned_tm, assigned,
                        pending_tm, pending - pending_tm, pending,
                        sent_tm, sent - sent_tm, sent,
                        ps_tm, ps - ps_tm, ps,
                    )

                t1_rows, g1 = [], [0] * 15
                for sno, lt in enumerate(lt_order, 1):
                    sub = [r for r in lib_rows if r["lt"] == lt]
                    vals = _split15(
                        sum(r["total"] for r in sub), sum(r["total_tm"] for r in sub),
                        sum(r["assigned"] for r in sub), sum(r["assigned_tm"] for r in sub),
                        sum(r["sent"] for r in sub), sum(r["sent_tm"] for r in sub),
                    )
                    t1_rows.append((sno, lt) + vals)
                    for k in range(15):
                        g1[k] += vals[k]
                t1_html = "".join(
                    f"<tr><td>{r[0]}</td><td style='text-align:left'>{r[1]}</td>"
                    + "".join(f"<td>{v}</td>" for v in r[2:]) + "</tr>" for r in t1_rows
                )
                t1_html += (
                    "<tr style='background:#d0e8ff;font-weight:800;'><td></td>"
                    "<td style='text-align:left'>மொத்தம்</td>" + "".join(f"<td>{v}</td>" for v in g1) + "</tr>"
                )

                t2_html, sno2, g2 = "", 0, [0] * 15
                for lt in lt_order:
                    t2_html += (f"<tr style='background:#0d5c63;color:#fff;font-weight:800;'>"
                                f"<td colspan='17' style='text-align:left'>▌ {lt}</td></tr>")
                    sub = sorted([r for r in lib_rows if r["lt"] == lt], key=lambda r: r["ln"])
                    for r in sub:
                        sno2 += 1
                        vals = _split15(r["total"], r["total_tm"], r["assigned"], r["assigned_tm"], r["sent"], r["sent_tm"])
                        for k, v in enumerate(vals):
                            g2[k] += v
                        t2_html += (
                            f"<tr><td>{sno2}</td><td style='text-align:left'>{r['ln']}</td>"
                            + "".join(f"<td>{v}</td>" for v in vals) + "</tr>"
                        )
                t2_html += (
                    "<tr style='background:#d0e8ff;font-weight:800;'><td></td>"
                    "<td style='text-align:left'>மொத்தம்</td>" + "".join(f"<td>{v}</td>" for v in g2) + "</tr>"
                )

                _rep3_thead = """<tr><th rowspan='2'>வ.எண்</th><th rowspan='2'>{name_col}</th>
<th colspan='3'>பெறப்பட்டது</th><th colspan='3'>பிரிக்கப்பட்டது</th><th colspan='3'>மீதம்</th>
<th colspan='3'>அனுப்பப்பட்டது</th><th colspan='3'>அனுப்ப வேண்டியது</th></tr>
<tr><th>தமிழ்</th><th>ஆங்கிலம்</th><th>மொத்தம்</th><th>தமிழ்</th><th>ஆங்கிலம்</th><th>மொத்தம்</th>
<th>தமிழ்</th><th>ஆங்கிலம்</th><th>மொத்தம்</th><th>தமிழ்</th><th>ஆங்கிலம்</th><th>மொத்தம்</th>
<th>தமிழ்</th><th>ஆங்கிலம்</th><th>மொத்தம்</th></tr>"""

                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 3 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}
@page{{size:A4 landscape;margin:10mm 8mm 10mm 8mm;}}
.rep3-tbl{{font-size:7.2pt;}}
.rep3-tbl th,.rep3-tbl td{{padding:2px 3px;}}
</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p><p class="t2">மாவட்ட மைய நூலகம்</p>
<p class="t3">2026-2027 புதிய நூல்கள் பகிர்மானப் பணி நடைபெற்ற விவரம்</p><p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<p class="section-title">நூலக வகை வாரிய விவரம்</p>
<table class="rep3-tbl"><thead>{_rep3_thead.format(name_col='நூலகம் வகை')}</thead><tbody>{t1_html}</tbody></table>
<p class="section-title">நூலகம் வாரிய விவரம்</p>
<table class="rep3-tbl"><thead>{_rep3_thead.format(name_col='நூலகம் பெயர்')}</thead><tbody>{t2_html}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""

            elif num == 4:
                if rtype == "received":
                    filt_sql = "TRUE"
                    heading = "2026-2027 ல் பெறப்பட்ட அனைத்து பதிப்பகங்கள் மற்றும் நூல்கள் விவரம் (பிரிக்கப்பட்டது + பிரிக்கப்படாதது)"
                elif rtype == "split":
                    filt_sql = f"(set_number IS NOT NULL AND TRIM(set_number) != '') AND ({_SENT_SQL})"
                    heading = "2026-2027 ல் பிரிக்கப்பட்டு அனுப்பப்பட்ட பதிப்பகங்கள் மற்றும் நூல்கள் விவரம்"
                else:
                    rtype = "unsplit"
                    filt_sql = "(set_number IS NULL OR set_number = '')"
                    heading = "2026-2027 ல் இதுவரை பிரிக்கப்படாத பதிப்பகங்கள் மற்றும் நூல்கள் விவரம்"
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(vendor_name),''), 'தெரியாத பதிப்பகம்') AS vendor,
                           COUNT(DISTINCT TRIM(title)) AS title_count,
                           COUNT(DISTINCT TRIM(title)) FILTER (WHERE {_TAMIL_TITLE_SQL}) AS title_count_tm,
                           COUNT(*) AS copy_count,
                           COUNT(*) FILTER (WHERE {_TAMIL_TITLE_SQL}) AS copy_count_tm
                    FROM books WHERE ({filt_sql}) AND academic_year = %s
                    GROUP BY vendor ORDER BY vendor
                """, (year,))
                rows = cur.fetchall()
                if not rows:
                    raise _ReportError("இந்த வகையில் புத்தகங்கள் எதுவும் இல்லை")
                rows_html, tt_tm, tt_en, tc_tm, tc_en = "", 0, 0, 0, 0
                for i, r in enumerate(rows, 1):
                    title_tm = r["title_count_tm"]
                    title_en = r["title_count"] - title_tm
                    copy_tm = r["copy_count_tm"]
                    copy_en = r["copy_count"] - copy_tm
                    rows_html += (f"<tr><td>{i}</td><td style='text-align:left'>{r['vendor']}</td>"
                                  f"<td>{title_tm}</td><td>{title_en}</td><td>{title_tm + title_en}</td>"
                                  f"<td>{copy_tm}</td><td>{copy_en}</td><td>{copy_tm + copy_en}</td></tr>")
                    tt_tm += title_tm
                    tt_en += title_en
                    tc_tm += copy_tm
                    tc_en += copy_en
                rows_html += (f"<tr style='background:#d0e8ff;font-weight:800;'><td></td>"
                              f"<td style='text-align:left'>மொத்தம்</td>"
                              f"<td>{tt_tm}</td><td>{tt_en}</td><td>{tt_tm + tt_en}</td>"
                              f"<td>{tc_tm}</td><td>{tc_en}</td><td>{tc_tm + tc_en}</td></tr>")
                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 4 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட மைய நூலகம், {DISTRICT_NAME}</p>
<p class="t3">{heading}</p>
<p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th rowspan='2'>வ.எண்</th><th rowspan='2'>பதிப்பகம் பெயர்</th>
<th colspan='3'>மொத்த தலைப்புகள்</th><th colspan='3'>மொத்தப் படிகள்</th></tr>
<tr><th>தமிழ்</th><th>ஆங்கிலம்</th><th>மொத்தம்</th><th>தமிழ்</th><th>ஆங்கிலம்</th><th>மொத்தம்</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""
            elif num == 8:
                # அனுப்பப்பட்ட புத்தகங்களில் ஒரே தலைப்புக்கு வேறு வேறு விலைகள் —
                # ஒவ்வொரு விலைக்கும் அனுப்பப்பட்ட நூலகங்கள் (ஒரே ஒரு நூலகத்திற்கு
                # மட்டும் சென்றிருந்தாலும் சேர்க்கப்படும்) ஒரே செல்-ல் பட்டியலாக.
                cur.execute(f"""
                    SELECT {_NORM_TITLE_SQL} AS norm_title
                    FROM books
                    WHERE ({_SENT_SQL})
                      AND title IS NOT NULL AND TRIM(title) != '' AND academic_year = %s
                    GROUP BY norm_title
                    HAVING COUNT(DISTINCT price) > 1
                """, (year,))
                multi_price_norm_titles = {r["norm_title"] for r in cur.fetchall()}

                if not multi_price_norm_titles:
                    raise _ReportError("அனுப்பப்பட்ட புத்தகங்களில் ஒரே தலைப்பில் வேறு வேறு விலைகள் எதுவும் இல்லை")

                cur.execute(f"""
                    SELECT {_NORM_TITLE_SQL} AS norm_title,
                           MIN(title) AS title,
                           price,
                           COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),''), 'தெரியாத நூலகம்') AS lib
                    FROM books
                    WHERE ({_SENT_SQL}) AND academic_year = %s
                    GROUP BY norm_title, price, lib
                    ORDER BY norm_title, price, lib
                """, (year,))
                detail_rows = [r for r in cur.fetchall() if r["norm_title"] in multi_price_norm_titles]

                # norm_title -> title, {price -> [lib, lib, ...] (distinct)}
                grouped = {}
                title_display = {}
                for r in detail_rows:
                    nt = r["norm_title"]
                    grouped.setdefault(nt, {}).setdefault(r["price"], []).append(r["lib"])
                    title_display.setdefault(nt, r["title"])

                body_rows = ""
                sno_title = 0
                total_titles = len(grouped)
                for nt, price_map in grouped.items():
                    sno_title += 1
                    title_txt = title_display[nt]
                    prices_sorted = sorted(price_map.keys(), key=lambda p: (p is None, p))
                    rowspan = len(prices_sorted)
                    for i, price in enumerate(prices_sorted):
                        price_disp = price if price not in (None, "") else "—"
                        libs = price_map[price]
                        libs_txt = ", ".join(f"கி{idx:02d}.{lib}" for idx, lib in enumerate(libs, 1))
                        if i == 0:
                            body_rows += (
                                f"<tr><td rowspan='{rowspan}'>{sno_title}</td>"
                                f"<td rowspan='{rowspan}' style='text-align:left'>{title_txt}</td>"
                                f"<td>{price_disp}</td><td style='text-align:left'>{libs_txt}</td></tr>"
                            )
                        else:
                            body_rows += f"<tr><td>{price_disp}</td><td style='text-align:left'>{libs_txt}</td></tr>"

                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 8 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p><p class="t2">மாவட்ட மைய நூலகம்</p>
<p class="t3">அனுப்பப்பட்ட நூல்களில் ஒரே தலைப்புக்கு வேறு வேறு விலைகள் உள்ள விவரம்</p>
<p class="t4">மொத்தம் {total_titles} தலைப்புகளில் வேறுபட்ட விலைகள் காணப்படுகின்றன</p>
<p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th>வ.எண்</th><th>தலைப்பு</th><th>விலை</th><th>நூலகங்கள்</th></tr></thead>
<tbody>{body_rows}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""

            elif num == 9:
                # ஒரு நூலகத்திற்குள் ஒரே தலைப்பில் 2 அல்லது அதற்கு மேற்பட்ட பிரதிகள் —
                # தலைப்பு ஒப்பீடு _NORM_TITLE_SQL பயன்படுத்துகிறது (quote/space/case
                # புறக்கணிப்பு + ஹைபனுக்குப் பின் தமிழ் இல்லாத identity suffix
                # புறக்கணிப்பு — multi-price feature-ல் உள்ள அதே normalization).
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),''), 'தெரியாத நூலகம்') AS lib,
                           {_NORM_TITLE_SQL} AS norm_ttl
                    FROM books
                    WHERE title IS NOT NULL AND TRIM(title) != '' AND academic_year = %s
                    GROUP BY lib, norm_ttl
                    HAVING COUNT(*) >= 2
                """, (year,))
                dup_pairs = {(r["lib"], r["norm_ttl"]) for r in cur.fetchall()}

                if not dup_pairs:
                    raise _ReportError("எந்த நூலகத்திலும் ஒரே தலைப்பில் 2 அல்லது அதற்கு மேற்பட்ட பிரதிகள் உள்ள நூல்கள் இல்லை")

                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),''), 'தெரியாத நூலகம்') AS lib,
                           {_NORM_TITLE_SQL} AS norm_ttl,
                           title, author, vendor_name, state_acc_number, central_number, branch_number,
                           year_pub, price
                    FROM books
                    WHERE title IS NOT NULL AND TRIM(title) != '' AND academic_year = %s
                    ORDER BY lib, norm_ttl, central_number NULLS LAST, branch_number NULLS LAST
                """, (year,))
                all_rows = [r for r in cur.fetchall() if (r["lib"], r["norm_ttl"]) in dup_pairs]

                lib_groups = {}
                for r in all_rows:
                    # display-க்கு அந்த group-ல் முதலில் வந்த title-ஐ பயன்படுத்துகிறோம்
                    lib_groups.setdefault(r["lib"], {}).setdefault(r["norm_ttl"], {"title": r["title"], "rows": []})
                    lib_groups[r["lib"]][r["norm_ttl"]]["rows"].append(r)

                body_rows, sno_lib, total_titles, total_copies = "", 0, 0, 0
                for lib in sorted(lib_groups.keys()):
                    titles_map = lib_groups[lib]
                    sno_lib += 1
                    body_rows += (
                        f"<tr style='background:#0d5c63;color:#fff;font-weight:800;'>"
                        f"<td colspan='9' style='text-align:left'>▌ {sno_lib}. {lib} — {len(titles_map)} தலைப்புகளில் நகல் பிரதிகள்</td></tr>"
                    )
                    for sno_title, (norm_ttl, group) in enumerate(titles_map.items(), 1):
                        rows = group["rows"]
                        display_title = group["title"]
                        total_titles += 1
                        total_copies += len(rows)
                        rowspan = len(rows)
                        distinct_prices = {r.get('price') for r in rows}
                        same_price = len(distinct_prices) == 1
                        row_style = " style='background:#d1fae5;'" if same_price else ""
                        badge = " <span style='background:#059669;color:#fff;font-size:0.75em;padding:1px 6px;border-radius:8px;'>ஒரே விலை</span>" if same_price else ""
                        for i, r in enumerate(rows, 1):
                            common = (
                                f"<td>{r.get('state_acc_number') or '—'}</td>"
                                f"<td>{_fmt_whole(r.get('central_number')) or '—'}</td>"
                                f"<td>{_fmt_whole(r.get('branch_number')) or '—'}</td>"
                                f"<td style='text-align:left'>{r.get('author') or '—'}</td>"
                                f"<td style='text-align:left'>{r.get('vendor_name') or '—'}</td>"
                                f"<td>{r.get('year_pub') or '—'}</td>"
                                f"<td>{_fmt_price(r.get('price')) or '—'}</td>"
                            )
                            if i == 1:
                                body_rows += (
                                    f"<tr{row_style}><td rowspan='{rowspan}'>{sno_title}</td>"
                                    f"<td rowspan='{rowspan}' style='text-align:left'>{display_title}{badge}</td>{common}</tr>"
                                )
                            else:
                                body_rows += f"<tr{row_style}>{common}</tr>"

                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 9 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p><p class="t2">மாவட்ட மைய நூலகம்</p>
<p class="t3">நூலகம் வாரியாக ஒரே தலைப்பில் 2 அல்லது அதற்கு மேற்பட்ட பிரதிகள் உள்ள நூல்கள் விவரம்</p>
<p class="t4">(capital/small letters, space, quote-குறிகள், ஹைபன் identity suffix புறக்கணிக்கப்படும்) — {len(lib_groups)} நூலகங்களில் {total_titles} தலைப்புகள், {total_copies} பிரதிகள்</p>
<p class="t4" style="color:#059669;">🟢 பச்சை நிற வரிசைகள் = அந்த தலைப்பின் அனைத்து பிரதிகளும் ஒரே விலையில் உள்ளன</p>
<p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th>வ.எண்</th><th>தலைப்பு</th><th>மாநிலப்<br>பதிவெண்</th><th>மையப்<br>பதிவெண்</th><th>கிளைப்<br>பதிவெண்</th>
<th>எழுதியவர்</th><th>பதிப்பகம்</th><th>பதிப்பு<br>ஆண்டு</th><th>விலை</th></tr></thead>
<tbody>{body_rows}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""

            elif num == 10:
                # அறிக்கை 9-ல் உள்ள தலைப்புகள் மட்டுமே (ஒரு நூலகத்தில் 2+ பிரதிகள்
                # உள்ள தலைப்புகள்) — அவற்றிற்கு Book Id, தலைப்பு, விலை, முகப்புப்
                # படம் மற்றும் அவை சென்றுள்ள அனைத்து நூலகங்களும் — தலைப்பு A-Z வரிசையில்.
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),''), 'தெரியாத நூலகம்') AS lib,
                           {_NORM_TITLE_SQL} AS norm_ttl
                    FROM books
                    WHERE title IS NOT NULL AND TRIM(title) != '' AND academic_year = %s
                    GROUP BY lib, norm_ttl
                    HAVING COUNT(*) >= 2
                """, (year,))
                dup_pairs = {(r["lib"], r["norm_ttl"]) for r in cur.fetchall()}
                if not dup_pairs:
                    raise _ReportError("அறிக்கை 9-ல் உள்ள (ஒரு நூலகத்தில் 2+ பிரதிகள் உள்ள) தலைப்புகள் எதுவும் இல்லை")
                norm_titles_dup = {n for (_lib, n) in dup_pairs}

                cur.execute(f"""
                    SELECT title, price, NULLIF(TRIM(book_id),'') AS book_id,
                           COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),'')) AS lib,
                           NULLIF(TRIM(librarian_id),'') AS lib_id,
                           {_NORM_TITLE_SQL} AS norm_ttl
                    FROM books
                    WHERE title IS NOT NULL AND TRIM(title) != ''
                      AND academic_year = %s
                      AND COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),'')) IS NOT NULL
                    ORDER BY title, price
                """, (year,))
                all_rows = [r for r in cur.fetchall() if r["norm_ttl"] in norm_titles_dup]
                if not all_rows:
                    raise _ReportError("அறிக்கை 9-ல் உள்ள தலைப்புகளுக்கான நூலக ஒதுக்கீட்டு தரவு கிடைக்கவில்லை")

                groups = {}   # (title, price) -> {"book_ids": set, "libs": set-of-(name,lib_id)}
                for r in all_rows:
                    key = (r["title"], r["price"])
                    g = groups.setdefault(key, {"book_ids": set(), "libs": set()})
                    if r["book_id"]:
                        g["book_ids"].add(r["book_id"])
                    if r["lib"]:
                        g["libs"].add((r["lib"], r["lib_id"] or ""))

                sorted_keys = sorted(groups.keys(), key=lambda k: (k[0] or "", k[1] or ""))

                book_ids_all = set()
                for g in groups.values():
                    book_ids_all |= g["book_ids"]
                covers_present = set()
                if book_ids_all:
                    try:
                        cur.execute(
                            "SELECT book_id FROM book_covers WHERE book_id = ANY(%s)",
                            (list(book_ids_all),)
                        )
                        covers_present = {r["book_id"] for r in cur.fetchall()}
                    except Exception as e:
                        print(f"book_covers lookup skipped (table not ready?): {e}")
                        conn.rollback()

                table_rows = ""
                for i, (title, price) in enumerate(sorted_keys, 1):
                    g = groups[(title, price)]
                    bids = sorted(g["book_ids"])
                    bid_display = ", ".join(bids) if bids else "—"
                    cover_bid = next((b for b in bids if b in covers_present), None)
                    if cover_bid:
                        img_cell = f'<img src="/api/book_cover/{quote(cover_bid)}" style="max-height:70px;max-width:60px;object-fit:contain;border:1px solid #ddd;border-radius:4px;">'
                    else:
                        img_cell = '<span style="color:#9ca3af;font-size:0.8rem;">படம் இல்லை</span>'
                    libs_sorted = sorted(g["libs"], key=lambda t: t[0] or "")
                    libs_display = ", ".join(
                        f"{name} ({lid})" if lid else name
                        for name, lid in libs_sorted
                    ) if libs_sorted else "—"
                    table_rows += (
                        f"<tr><td>{i}</td>"
                        f"<td>{bid_display}</td>"
                        f"<td style='text-align:left'>{title}</td>"
                        f"<td>{_fmt_price(price) or '—'}</td>"
                        f"<td>{img_cell}</td>"
                        f"<td style='text-align:left'>{libs_display}</td></tr>"
                    )

                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 10 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p><p class="t2">மாவட்ட மைய நூலகம்</p>
<p class="t3">அறிக்கை 9-ல் உள்ள (ஒரு நூலகத்தில் 2+ பிரதிகள் உள்ள) தலைப்புகளுக்கான Book Id, விலை, முகப்புப் படம் மற்றும் அவை சென்றுள்ள நூலகங்கள் (தலைப்பு A-Z வரிசையில்)</p>
<p class="t4">மொத்தம் {len(groups)} தலைப்பு/விலை சேர்க்கைகள்</p>
<p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th>வ.எண்</th><th>Book Id</th><th>தலைப்பு</th><th>விலை</th><th>முகப்புப் படம்</th><th>நூலகங்கள்</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""

            elif num == 11:
                # அறிக்கை 9-ல் இருந்து வேறுபாடு: இங்கே தலைப்பு மட்டும் இல்லாமல்
                # விலையும் ஒரே மாதிரி இருக்கணும் — ஒரு நூலகத்திற்குள்ளேயே
                # (100% ஒத்துப்போகும் தலைப்பு + ஒரே விலை) கொண்ட 2 அல்லது
                # அதற்கு மேற்பட்ட பிரதிகள் சென்றிருந்தால் மட்டுமே இங்கு இடம்பெறும்.
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),''), 'தெரியாத நூலகம்') AS lib,
                           {_NORM_TITLE_SIMPLE_SQL} AS norm_title,
                           price
                    FROM books
                    WHERE title IS NOT NULL AND TRIM(title) != ''
                      AND price IS NOT NULL AND TRIM(price) != ''
                      AND academic_year = %s
                    GROUP BY lib, norm_title, price
                    HAVING COUNT(*) >= 2
                """, (year,))
                dup_triples11 = cur.fetchall()
                # (lib, norm_title, price) -- இந்த மூன்றும் சேர்ந்து 2+ இருக்கும்
                # இடத்தை மட்டுமே வைத்துக்கொள்கிறோம் (வேறு நூலகங்களில் இதே
                # தலைப்பு/விலை 1 பிரதி மட்டும் இருந்தால் அது இதில் வராது).
                qualifying_lib_norm_price = {(r["lib"], r["norm_title"], r["price"]) for r in dup_triples11}
                if not qualifying_lib_norm_price:
                    raise _ReportError("ஒரு நூலகத்திற்குள் ஒரே தலைப்பில், ஒரே விலையில் 2+ பிரதிகள் சென்ற நூல்கள் எதுவும் இல்லை")

                cur.execute(f"""
                    SELECT title, price, NULLIF(TRIM(book_id),'') AS book_id,
                           COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),''), 'தெரியாத நூலகம்') AS lib,
                           NULLIF(TRIM(librarian_id),'') AS lib_id,
                           {_NORM_TITLE_SIMPLE_SQL} AS norm_ttl
                    FROM books
                    WHERE title IS NOT NULL AND TRIM(title) != ''
                      AND price IS NOT NULL AND TRIM(price) != ''
                      AND academic_year = %s
                      AND COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),'')) IS NOT NULL
                    ORDER BY title, price
                """, (year,))
                all_rows11 = [r for r in cur.fetchall() if (r["lib"], r["norm_ttl"], r["price"]) in qualifying_lib_norm_price]
                if not all_rows11:
                    raise _ReportError("இந்த தலைப்புகளுக்கான நூலக ஒதுக்கீட்டு தரவு கிடைக்கவில்லை")

                groups11 = {}   # (title, price) -> {"book_ids": set, "libs": set-of-(name,lib_id)}
                for r in all_rows11:
                    key = (r["title"], r["price"])
                    g = groups11.setdefault(key, {"book_ids": set(), "libs": set()})
                    if r["book_id"]:
                        g["book_ids"].add(r["book_id"])
                    if r["lib"]:
                        g["libs"].add((r["lib"], r["lib_id"] or ""))

                sorted_keys11 = sorted(groups11.keys(), key=lambda k: (k[0] or "", k[1] or ""))

                book_ids_all11 = set()
                for g in groups11.values():
                    book_ids_all11 |= g["book_ids"]
                covers_present11 = set()
                if book_ids_all11:
                    try:
                        cur.execute(
                            "SELECT book_id FROM book_covers WHERE book_id = ANY(%s)",
                            (list(book_ids_all11),)
                        )
                        covers_present11 = {r["book_id"] for r in cur.fetchall()}
                    except Exception as e:
                        print(f"book_covers lookup skipped (table not ready?): {e}")
                        conn.rollback()

                table_rows11 = ""
                for i, (title, price) in enumerate(sorted_keys11, 1):
                    g = groups11[(title, price)]
                    bids = sorted(g["book_ids"])
                    bid_display = ", ".join(bids) if bids else "—"
                    cover_bid = next((b for b in bids if b in covers_present11), None)
                    if cover_bid:
                        img_cell = f'<img src="/api/book_cover/{quote(cover_bid)}" style="max-height:70px;max-width:60px;object-fit:contain;border:1px solid #ddd;border-radius:4px;">'
                    else:
                        img_cell = '<span style="color:#9ca3af;font-size:0.8rem;">படம் இல்லை</span>'
                    libs_sorted = sorted(g["libs"], key=lambda t: t[0] or "")
                    libs_display = ", ".join(
                        f"{name} ({lid})" if lid else name
                        for name, lid in libs_sorted
                    ) if libs_sorted else "—"
                    table_rows11 += (
                        f"<tr><td>{i}</td>"
                        f"<td>{bid_display}</td>"
                        f"<td style='text-align:left'>{title}</td>"
                        f"<td>{_fmt_price(price) or '—'}</td>"
                        f"<td>{img_cell}</td>"
                        f"<td style='text-align:left'>{libs_display}</td></tr>"
                    )

                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 11 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p><p class="t2">மாவட்ட மைய நூலகம்</p>
<p class="t3">ஒரு நூலகத்திற்குள்ளேயே ஒரே தலைப்பில் (capital/small letters மட்டும் புறக்கணிக்கப்படும், மற்றபடி exact match), ஒரே விலையில், 2 அல்லது அதற்கு மேற்பட்ட பிரதிகள் சென்றுள்ள நூல்களுக்கான Book Id, விலை, முகப்புப் படம் மற்றும் அவை சென்றுள்ள நூலகங்கள் (தலைப்பு A-Z வரிசையில்)</p>
<p class="t4">மொத்தம் {len(groups11)} தலைப்பு/விலை சேர்க்கைகள்</p>
<p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th>வ.எண்</th><th>Book Id</th><th>தலைப்பு</th><th>விலை</th><th>முகப்புப் படம்</th><th>நூலகங்கள்</th></tr></thead>
<tbody>{table_rows11}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""

            elif num == 12:
                # அறிக்கை 9-ன் அதே duplicate-கண்டறியும் தர்க்கம் (லைப்ரரி +
                # normalized title, விலை பொருட்படுத்தாமல் 2+ பிரதிகள்) —
                # ஆனால் flat, சுருக்கமான வடிவில்: ஒவ்வொரு (நூலகம், தலைப்பு)
                # நகல் இணைக்கும் ஒரே ஒரு வரிசை மட்டும் — வ.எண், நூலகம்,
                # தலைப்பு, பதிப்பகம்.
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),''), 'தெரியாத நூலகம்') AS lib,
                           {_NORM_TITLE_SQL} AS norm_ttl
                    FROM books
                    WHERE title IS NOT NULL AND TRIM(title) != '' AND academic_year = %s
                    GROUP BY lib, norm_ttl
                    HAVING COUNT(*) >= 2
                """, (year,))
                dup_pairs12 = {(r["lib"], r["norm_ttl"]) for r in cur.fetchall()}

                if not dup_pairs12:
                    raise _ReportError("எந்த நூலகத்திலும் ஒரே தலைப்பில் 2 அல்லது அதற்கு மேற்பட்ட பிரதிகள் உள்ள நூல்கள் இல்லை")

                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),''), 'தெரியாத நூலகம்') AS lib,
                           {_NORM_TITLE_SQL} AS norm_ttl,
                           title, vendor_name, NULLIF(TRIM(book_id),'') AS book_id
                    FROM books
                    WHERE title IS NOT NULL AND TRIM(title) != '' AND academic_year = %s
                    ORDER BY lib, norm_ttl
                """, (year,))
                all_rows12 = [r for r in cur.fetchall() if (r["lib"], r["norm_ttl"]) in dup_pairs12]

                groups12 = {}   # (lib, norm_ttl) -> {"title": str, "publishers": set, "book_ids": [str,...]}
                for r in all_rows12:
                    key = (r["lib"], r["norm_ttl"])
                    g = groups12.setdefault(key, {"title": r["title"], "publishers": set(), "book_ids": []})
                    pub = (r.get("vendor_name") or "").strip()
                    if pub:
                        g["publishers"].add(pub)
                    bid = r.get("book_id")
                    if bid and bid not in g["book_ids"]:
                        g["book_ids"].append(bid)

                sorted_keys12 = sorted(groups12.keys(), key=lambda k: (k[0] or "", groups12[k]["title"] or ""))

                table_rows12 = ""
                for i, key in enumerate(sorted_keys12, 1):
                    lib, _norm = key
                    g = groups12[key]
                    pub_display = ", ".join(sorted(g["publishers"])) if g["publishers"] else "—"
                    bid_display = "<br>".join(g["book_ids"]) if g["book_ids"] else "—"
                    table_rows12 += (
                        f"<tr><td>{i}</td>"
                        f"<td style='text-align:left'>{lib}</td>"
                        f"<td style='text-align:left'>{g['title']}</td>"
                        f"<td style='text-align:left'>{bid_display}</td>"
                        f"<td style='text-align:left'>{pub_display}</td></tr>"
                    )

                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 12 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p><p class="t2">மாவட்ட மைய நூலகம்</p>
<p class="t3">ஒரு நூலகத்தில் ஒரே தலைப்புள்ள 2 அல்லது அதற்கு மேற்பட்ட நூல்கள் உள்ள விவரம் (சுருக்கம்)</p>
<p class="t4">மொத்தம் {len(groups12)} நூலகம்/தலைப்பு சேர்க்கைகள்</p>
<p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th>வ.எண்</th><th>நூலகம்</th><th>தலைப்பு</th><th>Book Id</th><th>பதிப்பகம்</th></tr></thead>
<tbody>{table_rows12}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""

            else:
                raise _ReportError("இந்த அறிக்கை இன்னும் தயார் இல்லை (அடுத்த கட்டத்தில் வரும்)", 400)
    return html


@app.route("/api/report/<int:num>")
@login_required
def api_report(num):
    today_str = datetime.now().strftime("%d/%m/%Y")
    year = request.args.get('year') or BASE_YEAR
    rtype = request.args.get('rtype')
    try:
        html = _build_report_html(num, year, rtype)
    except _ReportError as e:
        return jsonify({"error": e.message}), e.status
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    report_id = _save_report(html, f"அறிக்கை {num} - {today_str}")
    return jsonify({
        "success": True,
        "message": f"அறிக்கை {num} புதிய tab-ல் திறக்கப்படும்.\nPDF-ஆக சேமிக்க: Ctrl+P → Save as PDF",
        "url": f"/reports/view/{report_id}"
    })


@app.route("/api/report/<int:num>/excel")
@login_required
def api_report_excel(num):
    year = request.args.get('year') or BASE_YEAR
    rtype = request.args.get('rtype')
    try:
        html = _build_report_html(num, year, rtype)
    except _ReportError as e:
        return jsonify({"error": e.message}), e.status
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    wb = _report_html_to_workbook([(f"அறிக்கை{num}", html)])
    fname = f"அறிக்கை{num}_{datetime.now().strftime('%d%m%Y')}.xlsx"
    return _workbook_response(wb, fname)


# ==========================================================
# REPORT 5 — நூலகம் வாரியான புத்தக விவரம்
# ==========================================================
def _fmt_whole(s):
    if not s:
        return s
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else s
    except (ValueError, TypeError):
        return s


def _fmt_price(s):
    if not s:
        return s
    try:
        return f"{float(s):.2f}"
    except (ValueError, TypeError):
        return s


@app.route("/api/publisher_search")
@login_required
def api_publisher_search():
    """Dashboard 'பதிப்பகம் Search' — குறைந்தது 4 எழுத்துகள் கொடுத்தால்
    ஒத்த பதிப்பகங்களின் (vendor_name) பட்டியலை திரும்பும்."""
    q = (request.args.get("q") or "").strip()
    year = request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    if len(q) < 4:
        return jsonify({"error": "குறைந்தது 4 எழுத்துகள் தேவை"}), 400
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT vendor_name FROM books "
            "WHERE vendor_name IS NOT NULL AND TRIM(vendor_name) != '' "
            "AND vendor_name ILIKE %s AND academic_year = %s "
            "ORDER BY vendor_name LIMIT 20",
            ('%' + q + '%', year)
        )
        rows = cur.fetchall()
    return jsonify([r["vendor_name"] for r in rows])


@app.route("/api/title_search")
@login_required
def api_title_search():
    """Dashboard 'Master Title Change' — குறைந்தது 4 எழுத்துகள் கொடுத்தால்
    ஒத்த தலைப்புகளின் (title) பட்டியலை திரும்பும்."""
    q = (request.args.get("q") or "").strip()
    year = request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    if len(q) < 4:
        return jsonify({"error": "குறைந்தது 4 எழுத்துகள் தேவை"}), 400
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT title FROM books "
            "WHERE title IS NOT NULL AND TRIM(title) != '' "
            "AND title ILIKE %s AND academic_year = %s "
            "ORDER BY title LIMIT 20",
            ('%' + q + '%', year)
        )
        rows = cur.fetchall()
    return jsonify([r["title"] for r in rows])


@app.route("/api/publisher_report", methods=["POST"])
@login_required
def api_publisher_report():
    """தேர்ந்தெடுத்த பதிப்பகத்திற்குரிய அனைத்து புத்தகங்களின் முழு விவரத்தையும்
    (பிரித்தது/அனுப்பியது தேதிகள் உட்பட) ஒரு அறிக்கையாக உருவாக்கி,
    Ctrl+P → PDF-ஆக சேமிக்கும் வகையில் புதிய tab-ல் திறக்கும் URL தரும்."""
    body = request.json or {}
    vendor = (body.get("vendor") or "").strip()
    year = body.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    today_str = datetime.now().strftime("%d/%m/%Y")
    if not vendor:
        return jsonify({"error": "பதிப்பகம் கொடுக்கப்படவில்லை"}), 400
    try:
        with DBConn() as (conn, cur):
            cur.execute(
                "SELECT * FROM books WHERE TRIM(vendor_name) = %s AND academic_year = %s "
                "ORDER BY title",
                (vendor, year)
            )
            rows = cur.fetchall()
        if not rows:
            return jsonify({"error": f'"{vendor}" பதிப்பகத்திற்கு புத்தகங்கள் இந்த ஆண்டில் இல்லை'})

        table_rows, tpp, tap = "", 0.0, 0.0
        for i, r in enumerate(rows, 1):
            price, acc_price = r.get("price"), r.get("accepted_price")
            try:
                tpp += float(price) if price else 0.0
            except Exception:
                pass
            try:
                tap += float(acc_price) if acc_price else 0.0
            except Exception:
                pass
            separated = r.get("work_status") or "—"
            sent = r.get("date") or ("அனுப்பப்பட்டது" if (r.get("sent_details") or "") == "sent" else "—")
            table_rows += f"""<tr><td style="text-align:center">{i}</td>
<td style="text-align:left">{r.get('title') or '—'}</td><td style="text-align:left">{r.get('author') or '—'}</td>
<td style="text-align:left">{r.get('isbn') or '—'}</td><td style="text-align:center">{r.get('year_pub') or '—'}</td>
<td style="text-align:right">{_fmt_price(price) or '—'}</td><td style="text-align:right">{_fmt_price(acc_price) or '—'}</td>
<td style="text-align:left">{r.get('library_name_tm') or r.get('library_name') or '—'}</td>
<td style="text-align:center">{_fmt_whole(r.get('central_number')) or '—'}</td>
<td style="text-align:center">{_fmt_whole(r.get('branch_number')) or '—'}</td>
<td style="text-align:center">{separated}</td><td style="text-align:center">{sent}</td></tr>"""
        table_rows += f"""<tr style="font-weight:bold;background:#e8f5e9;"><td colspan="5" style="text-align:right">மொத்தம் ({len(rows)} நூல்கள்)</td>
<td style="text-align:right">{tpp:.2f}</td><td style="text-align:right">{tap:.2f}</td><td colspan="4"></td></tr>"""

        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>பதிப்பகம் அறிக்கை - {vendor}</title>
<style>@page{{size:A4 landscape;margin:12mm 10mm;}}body{{font-family:'Nirmala UI','Noto Sans Tamil',Arial,sans-serif;font-size:9pt;color:#000;margin:0;}}
.rt{{text-align:center;margin-bottom:8px;}}.rt p{{margin:2px 0;}}.t1{{font-size:13pt;font-weight:bold;}}.t2{{font-size:12pt;font-weight:bold;}}
.t3{{font-size:11pt;font-weight:bold;}}.t5{{font-size:9pt;}}
table{{width:100%;border-collapse:collapse;margin-top:10px;}}th{{background:#ede9fe;font-weight:bold;border:1px solid #000;padding:5px 4px;font-size:8.5pt;text-align:center;}}
td{{border:1px solid #000;padding:4px;font-size:8.5pt;vertical-align:top;}}tr:nth-child(even){{background:#f9f9f9;}}.sig{{margin-top:30px;text-align:right;font-size:9.5pt;line-height:1.8;}}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு, {DISTRICT_NAME}</p><p class="t2">பதிப்பகம் : {vendor}</p>
<p class="t3">பதிப்பகம் வாரியான முழு புத்தக விவரம் — {year}</p>
<p class="t5">அறிக்கை நாள் : {today_str} &nbsp;&nbsp;|&nbsp;&nbsp; மொத்தம் <strong>{len(rows)}</strong> புத்தகங்கள்</p></div>
<table><thead><tr><th style="width:3%">வ.எண்</th><th style="width:20%">தலைப்பு</th><th style="width:12%">எழுதியவர்</th>
<th style="width:11%">ISBN</th><th style="width:6%">பதிப்பு<br>ஆண்டு</th><th style="width:7%">பதிப்பு<br>விலை</th>
<th style="width:7%">ஏற்பு<br>விலை</th><th style="width:14%">நூலகம்</th><th style="width:6%">மையப்<br>பதிவெண்</th>
<th style="width:6%">கிளைப்<br>பதிவெண்</th><th style="width:8%">பிரித்தது</th><th style="width:8%">அனுப்பியது</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""
        report_id = _save_report(html, f"பதிப்பகம் அறிக்கை - {vendor}")
        return jsonify({
            "success": True,
            "message": f'"{vendor}" அறிக்கை புதிய tab-ல் திறக்கப்படும்.\nPDF-ஆக சேமிக்க: Ctrl+P → Save as PDF',
            "url": f"/reports/view/{report_id}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/report5_libs")
@login_required
def api_report5_libs():
    year = request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT library_name_tm FROM books "
            "WHERE library_name_tm IS NOT NULL AND library_name_tm != '' AND academic_year = %s "
            "ORDER BY library_name_tm",
            (year,)
        )
        rows = cur.fetchall()
    return jsonify([r["library_name_tm"] for r in rows])


def _build_report5_html(lib_name, year):
    today_str = datetime.now().strftime("%d/%m/%Y")
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT * FROM books WHERE TRIM(library_name_tm) = %s "
            "AND central_number IS NOT NULL AND academic_year = %s ORDER BY branch_number",
            (lib_name, year)
        )
        rows = cur.fetchall()
    if not rows:
        raise _ReportError(f'"{lib_name}" நூலகத்திற்கு பிரிக்கப்பட்ட புத்தகங்கள் இல்லை')

    table_rows, tpp, tap = "", 0.0, 0.0
    for i, r in enumerate(rows, 1):
        price, acc_price = r.get("price"), r.get("accepted_price")
        try:
            tpp += float(price) if price else 0.0
        except Exception:
            pass
        try:
            tap += float(acc_price) if acc_price else 0.0
        except Exception:
            pass
        table_rows += f"""<tr><td style="text-align:center">{i}</td><td style="text-align:center">{r.get('state_acc_number') or '—'}</td>
<td style="text-align:center">{_fmt_whole(r.get('central_number')) or '—'}</td><td style="text-align:center">{_fmt_whole(r.get('branch_number')) or '—'}</td>
<td style="text-align:left">{r.get('title') or '—'}</td><td style="text-align:left">{r.get('author') or '—'}</td>
<td style="text-align:left">{r.get('vendor_name') or '—'}</td><td style="text-align:center">{r.get('year_pub') or '—'}</td>
<td style="text-align:right">{_fmt_price(price) or '—'}</td><td style="text-align:right">{_fmt_price(acc_price) or '—'}</td></tr>"""
    table_rows += f"""<tr style="font-weight:bold;background:#e8f5e9;"><td colspan="8" style="text-align:right">மொத்தம்</td>
<td style="text-align:right">{tpp:.2f}</td><td style="text-align:right">{tap:.2f}</td></tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 5 - {lib_name}</title>
<style>@page{{size:A4 landscape;margin:12mm 10mm;}}body{{font-family:'Nirmala UI','Noto Sans Tamil',Arial,sans-serif;font-size:9pt;color:#000;margin:0;}}
.rt{{text-align:center;margin-bottom:8px;}}.rt p{{margin:2px 0;}}.t1{{font-size:13pt;font-weight:bold;}}.t2{{font-size:12pt;font-weight:bold;}}
.t3{{font-size:11pt;font-weight:bold;}}.t5{{font-size:9pt;}}
table{{width:100%;border-collapse:collapse;margin-top:10px;}}th{{background:#c8e6c9;font-weight:bold;border:1px solid #000;padding:5px 4px;font-size:8.5pt;text-align:center;}}
td{{border:1px solid #000;padding:4px;font-size:8.5pt;vertical-align:top;}}tr:nth-child(even){{background:#f9f9f9;}}.sig{{margin-top:30px;text-align:right;font-size:9.5pt;line-height:1.8;}}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு, {DISTRICT_NAME}</p><p class="t2">{lib_name}</p>
<p class="t3">இணையதள நூல் கொள்முதல் பட்டியல் {year}</p>
<p class="t5">அறிக்கை நாள் : {today_str} &nbsp;&nbsp;|&nbsp;&nbsp; மொத்தம் <strong>{len(rows)}</strong> புத்தகங்கள்</p></div>
<table><thead><tr><th style="width:4%">வ.எண்</th><th style="width:9%">மாநிலப்<br>பதிவெண்</th>
<th style="width:8%">மையப்<br>பதிவெண்</th><th style="width:7%">கிளைப்<br>பதிவெண்</th>
<th style="width:22%">தலைப்பு</th><th style="width:12%">எழுதியவர்</th><th style="width:14%">பதிப்பகம்</th>
<th style="width:6%">பதிப்பு<br>ஆண்டு</th><th style="width:8%">பதிப்பு<br>விலை</th><th style="width:8%">ஏற்பு<br>விலை</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div></body></html>"""


@app.route("/api/report5", methods=["POST"])
@login_required
def api_report5():
    body = request.json or {}
    lib_name = body.get("lib_name", "")
    year = body.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    try:
        html = _build_report5_html(lib_name, year)
    except _ReportError as e:
        return jsonify({"error": e.message}), e.status
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    report_id = _save_report(html, f"அறிக்கை 5 - {lib_name}")
    return jsonify({
        "success": True,
        "message": f'"{lib_name}" அறிக்கை புதிய tab-ல் திறக்கப்படும்.\nPDF-ஆக சேமிக்க: Ctrl+P → Save as PDF',
        "url": f"/reports/view/{report_id}"
    })


@app.route("/api/report5/excel", methods=["POST"])
@login_required
def api_report5_excel():
    body = request.json or {}
    lib_name = body.get("lib_name", "")
    year = body.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    try:
        html = _build_report5_html(lib_name, year)
    except _ReportError as e:
        return jsonify({"error": e.message}), e.status
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    wb = _report_html_to_workbook([("அறிக்கை5", html)])
    fname = f"அறிக்கை5_{lib_name}_{datetime.now().strftime('%d%m%Y')}.xlsx"
    return _workbook_response(wb, fname)


# ==========================================================
# REPORT 7 — மைய நூல் சேர்க்கை பதிவேடு (5000 வீதம் பகுதிகளாக)
# ==========================================================
_REPORT7_CHUNK = 5000


def _report7_ranges(cur, year):
    cur.execute(
        "SELECT MIN(central_number) AS mn, MAX(central_number) AS mx FROM books "
        "WHERE central_number IS NOT NULL AND academic_year = %s", (year,)
    )
    row = cur.fetchone()
    if row["mn"] is None:
        return None, None, None
    cn_min, cn_max = row["mn"], row["mx"]
    chunk_start = (cn_min // _REPORT7_CHUNK) * _REPORT7_CHUNK
    ranges, s, idx = [], chunk_start, 1
    while s <= cn_max:
        e = s + _REPORT7_CHUNK - 1
        cur.execute(
            "SELECT COUNT(*) AS c FROM books WHERE central_number BETWEEN %s AND %s AND academic_year = %s",
            (s, e, year)
        )
        c = cur.fetchone()["c"]
        if c:
            ranges.append({"idx": idx, "start": s, "end": e, "count": c})
            idx += 1
        s += _REPORT7_CHUNK
    return cn_min, cn_max, ranges


@app.route("/api/report7/ranges")
@login_required
def api_report7_ranges():
    year = request.args.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS c FROM books WHERE central_number IS NOT NULL AND academic_year = %s",
            (year,)
        )
        total = cur.fetchone()["c"]
        cn_min, cn_max, ranges = _report7_ranges(cur, year)
    if cn_min is None:
        return jsonify({"error": "மையப் பதிவெண் எதுவும் பதிவு செய்யப்படவில்லை"}), 400
    return jsonify({"ranges": ranges, "total": total, "cn_min": cn_min, "cn_max": cn_max})


def _build_report7_chunk_html(cur, sel, year, total_books, total_ranges, today_str):
    s, e, idx = sel["start"], sel["end"], sel["idx"]
    report_css = """
@page{size:A4 landscape;margin:12mm 10mm;}
body{font-family:'Nirmala UI','Noto Sans Tamil',Arial,sans-serif;font-size:9pt;color:#000;margin:0;}
.rt{text-align:center;margin-bottom:8px;}.rt p{margin:2px 0;}
.t1{font-size:13pt;font-weight:bold;}.t2{font-size:12pt;font-weight:bold;}
.t3{font-size:11pt;font-weight:bold;}.t5{font-size:9pt;}
table{width:100%;border-collapse:collapse;margin-top:10px;}
th{background:#b2dfdb;font-weight:bold;border:1.5px solid #000;padding:6px 5px;font-size:9pt;text-align:center;}
td{border:1.5px solid #000;padding:4px 5px;font-size:8.5pt;vertical-align:top;word-break:break-word;}
tr:nth-child(even){background:#f5f5f5;}
.sig{margin-top:30px;text-align:right;font-size:10pt;line-height:1.8;}
.total-row{background:#e0f7fa;font-weight:bold;}
"""
    cur.execute(
        "SELECT * FROM books WHERE central_number BETWEEN %s AND %s AND academic_year = %s "
        "ORDER BY central_number",
        (s, e, year)
    )
    chunk_rows = cur.fetchall()
    if not chunk_rows:
        return None
    table_rows = ""
    for r in chunk_rows:
        central_no = _fmt_whole(r.get("central_number")) or "—"
        branch_no = _fmt_whole(r.get("branch_number")) or "—"
        lib_name_tm = r.get("library_name_tm") or r.get("library_name") or "—"
        acc_price = r.get("accepted_price")
        table_rows += (
            "<tr>"
            f"<td style='text-align:center'>{central_no}</td>"
            f"<td style='text-align:left'>{r.get('author') or '—'}</td>"
            f"<td style='text-align:left'>{r.get('title') or '—'}</td>"
            f"<td style='text-align:center'>{r.get('year_pub') or '—'}</td>"
            f"<td style='text-align:left'>{r.get('vendor_name') or '—'}</td>"
            f"<td style='text-align:right'>{_fmt_price(acc_price) or '—'}</td>"
            f"<td style='text-align:left'>{branch_no} / {lib_name_tm}</td>"
            "</tr>"
        )
    chunk_count = len(chunk_rows)
    range_label = f"{s}–{e}"
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>அறிக்கை 7 (பகுதி {idx}/{total_ranges}) - {range_label}</title>
<style>{report_css}</style></head><body>
<div class="rt">
  <p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p>
  <p class="t2">மாவட்ட மைய நூலகம்</p>
  <p class="t3">மைய நூல் சேர்க்கை பதிவேடு — {year}</p>
  <p class="t5">மையப் பதிவெண் : <strong>{range_label}</strong> &nbsp;|&nbsp; இந்த பகுதி : <strong>{chunk_count}</strong> நூல்கள் &nbsp;|&nbsp; மொத்தம் : <strong>{total_books}</strong> &nbsp;|&nbsp; அறிக்கை நாள் : {today_str} &nbsp;|&nbsp; பகுதி {idx}/{total_ranges}</p>
</div>
<table>
  <thead><tr>
    <th style="width:10%">மைய நூல்<br>சேர்க்கை எண்</th>
    <th style="width:14%">எழுதியவர்</th>
    <th style="width:26%">தலைப்பு</th>
    <th style="width:7%">பதிப்பு<br>ஆண்டு</th>
    <th style="width:16%">பதிப்பாளர்</th>
    <th style="width:8%">ஏற்பு<br>விலை</th>
    <th style="width:19%">கிளை நூலக பதிவெண் /<br>நூலகம் பெயர்</th>
  </tr></thead>
  <tbody>
    {table_rows}
    <tr class="total-row"><td colspan="6" style="text-align:right">இந்த பகுதி மொத்தம்</td><td style="text-align:center">{chunk_count} நூல்கள்</td></tr>
  </tbody>
</table>
<div class="sig"><strong>நூலகர்</strong><br>மாவட்ட மைய நூலகம்<br>{DISTRICT_NAME}</div>
</body></html>"""
    return html, idx, range_label


@app.route("/api/report7", methods=["POST"])
@login_required
def api_report7():
    body = request.json or {}
    selected = body.get("selected", [])
    year = body.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    if not selected:
        return jsonify({"error": "எந்த பகுதியும் தேர்வு செய்யப்படவில்லை"}), 400
    today_str = datetime.now().strftime("%d/%m/%Y")
    try:
        with DBConn() as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS c FROM books WHERE central_number IS NOT NULL AND academic_year = %s",
                (year,)
            )
            total_books = cur.fetchone()["c"]
            _, _, all_ranges = _report7_ranges(cur, year)
            total_ranges = len(all_ranges) if all_ranges else 0

            saved, urls = [], []
            for sel in selected:
                result = _build_report7_chunk_html(cur, sel, year, total_books, total_ranges, today_str)
                if result is None:
                    continue
                html, idx, range_label = result
                rid = _save_report(html, f"அறிக்கை 7 - பகுதி {idx} ({range_label})")
                saved.append(f"பகுதி {idx} ({range_label})")
                urls.append(f"/reports/view/{rid}")

        if not saved:
            return jsonify({"error": "தேர்வு செய்த பகுதிகளில் data இல்லை"}), 400
        return jsonify({
            "success": True,
            "message": f"அறிக்கை 7 — {len(saved)} பகுதி(கள்) திறக்கப்படும்:\n" + ", ".join(saved) +
                       "\nPDF-ஆக சேமிக்க: Ctrl+P → Save as PDF",
            "urls": urls
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/report7/excel", methods=["POST"])
@login_required
def api_report7_excel():
    body = request.json or {}
    selected = body.get("selected", [])
    year = body.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    if not selected:
        return jsonify({"error": "எந்த பகுதியும் தேர்வு செய்யப்படவில்லை"}), 400
    today_str = datetime.now().strftime("%d/%m/%Y")
    try:
        with DBConn() as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS c FROM books WHERE central_number IS NOT NULL AND academic_year = %s",
                (year,)
            )
            total_books = cur.fetchone()["c"]
            _, _, all_ranges = _report7_ranges(cur, year)
            total_ranges = len(all_ranges) if all_ranges else 0

            sections = []
            for sel in selected:
                result = _build_report7_chunk_html(cur, sel, year, total_books, total_ranges, today_str)
                if result is None:
                    continue
                html, idx, range_label = result
                sections.append((f"பகுதி{idx}", html))

        if not sections:
            return jsonify({"error": "தேர்வு செய்த பகுதிகளில் data இல்லை"}), 400
        wb = _report_html_to_workbook(sections)
        fname = f"அறிக்கை7_{datetime.now().strftime('%d%m%Y')}.xlsx"
        return _workbook_response(wb, fname)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================================
# SEARCH
# ==========================================================
@app.route("/api/search")
@login_required
def api_search():
    text = request.args.get('q', '').strip()
    year = request.args.get('year') or BASE_YEAR
    if len(text) < 1:
        return jsonify([])
    # 1 எழுத்து மட்டும் தட்டச்சு செய்தால் (எ.கா. "த") — தலைப்பு சரியாக அந்த
    # எழுத்தாக மட்டுமே உள்ள புத்தகங்கள் (exact match). இல்லையெனில் "%த%" என்பது
    # நூற்றுக்கணக்கான தலைப்புகளைப் பொருத்தி LIMIT 100-க்குள் உண்மையான
    # புத்தகம் மறைந்துவிடும். 2+ எழுத்துகளுக்கு பழைய contains தேடல் தொடரும்.
    if len(text) == 1:
        title_cond = "LOWER(TRIM(title)) = LOWER(%s)"
        title_param = text
    else:
        title_cond = "title ILIKE %s"
        title_param = f"%{text}%"
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT title, price, vendor_name, COUNT(*) AS count, "
            "MIN(NULLIF(TRIM(book_id), '')) AS book_id, "
            "MIN(NULLIF(TRIM(author), '')) AS author "
            f"FROM books WHERE {title_cond} AND academic_year = %s "
            "GROUP BY title, price, vendor_name LIMIT 100",
            (title_param, year)
        )
        rows = cur.fetchall()

        # multi-price flag (unassigned books-ல்) — case/space/ஹைபன்-பின்பகுதி மாறுபாடு பொருட்படுத்தாமல்
        cur.execute(
            f"SELECT {_NORM_TITLE_SQL} AS norm_title "
            "FROM books "
            "WHERE (set_number IS NULL OR set_number='') "
            "AND title IS NOT NULL AND TRIM(title) != '' AND academic_year = %s "
            "GROUP BY norm_title HAVING COUNT(DISTINCT price) > 1",
            (year,)
        )
        multi_price_norm_titles = {r["norm_title"] for r in cur.fetchall()}

        # இந்த batch-ல் இருக்கும் book_id-களுக்குள் ஏற்கனவே cover படம்
        # சேமிக்கப்பட்டுள்ளதா என்பதை ஒரே query-ல் பார்த்துக்கொள்ளுதல்.
        # book_covers table இன்னும் create ஆகாத DB-க்களில் (schema.sql
        # update run செய்யாதவை) search உடைந்துவிடக் கூடாது என்பதற்காக
        # இந்த query பிழையானால் தள்ளுபடி செய்யப்படும்.
        book_ids = [r["book_id"] for r in rows if r["book_id"]]
        covers_present = set()
        if book_ids:
            try:
                cur.execute(
                    "SELECT book_id FROM book_covers WHERE book_id = ANY(%s)",
                    (book_ids,)
                )
                covers_present = {r["book_id"] for r in cur.fetchall()}
            except Exception as e:
                print(f"book_covers lookup skipped (table not ready?): {e}")
                conn.rollback()

    out = []
    for r in rows:
        out.append({
            "title": r["title"] or "",
            "author": r["author"] or "",
            "vendor": r["vendor_name"] or "",
            "price": r["price"] or "",
            "count": r["count"],
            "isMultiPrice": _norm_title(r["title"]) in multi_price_norm_titles,
            "isFuzzyDup": False,   # fuzzy cache — அடுத்த கட்டத்தில் சேர்க்கப்படும்
            "bookId": r["book_id"] or "",
            "hasCover": bool(r["book_id"]) and r["book_id"] in covers_present,
        })
    return jsonify(out)


# ==========================================================
# புத்தக முகப்புப் படங்கள் (Book Covers) — ஒரே தலைப்பில் வேறு
# வேறு விலைகள் உள்ள புத்தகங்களை பிரித்தறிய, Book Id வாரியாக
# முகப்புப் படம் (front page photo) அப்லோட் செய்து பார்க்க.
# ==========================================================
_ALLOWED_COVER_EXT = {".jpg", ".jpeg", ".jfif"}


@app.route("/api/admin/search_book_for_cover")
@admin_required
def api_admin_search_book_for_cover():
    """Cover Upload-க்கு — Admin விரும்பும் எந்த Book Id-ஐயும் தேடி
    தேர்ந்தெடுக்க. Book Id அல்லது தலைப்பு வைத்து தேடலாம். Book Id
    இல்லாத rows (காலியானவை) இதில் வராது — cover book_id வைத்தே
    சேமிக்கப்படுவதால்."""
    text = (request.args.get("q") or "").strip()
    year = request.args.get("year") or BASE_YEAR
    if len(text) < 2:
        return jsonify([])
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT ON (book_id) book_id, title, price, vendor_name "
            "FROM books "
            "WHERE (book_id ILIKE %s OR title ILIKE %s) "
            "AND book_id IS NOT NULL AND TRIM(book_id) != '' "
            "AND academic_year = %s "
            "ORDER BY book_id, title LIMIT 50",
            (f"%{text}%", f"%{text}%", year)
        )
        rows = cur.fetchall()
        book_ids = [r["book_id"] for r in rows]
        covers_present = set()
        if book_ids:
            try:
                cur.execute(
                    "SELECT book_id FROM book_covers WHERE book_id = ANY(%s)",
                    (book_ids,)
                )
                covers_present = {r["book_id"] for r in cur.fetchall()}
            except Exception as e:
                print(f"book_covers lookup skipped (table not ready?): {e}")
                conn.rollback()

    rows.sort(key=lambda r: (r["title"] or "", r["price"] or ""))
    return jsonify([
        {
            "bookId": r["book_id"],
            "title": r["title"] or "",
            "price": r["price"] or "",
            "vendor": r["vendor_name"] or "",
            "hasCover": r["book_id"] in covers_present,
        }
        for r in rows
    ])


@app.route("/api/admin/multi_price_book_ids")
@admin_required
def api_admin_multi_price_book_ids():
    """'ஒரே தலைப்பில் வேறு விலை' உள்ள புத்தகங்களின் Book Id பட்டியல் —
    Cover Upload dropdown-க்கு. Book Id இல்லாத rows இதில் வராது."""
    year = request.args.get("year") or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            f"WITH multi AS ("
            f"  SELECT {_NORM_TITLE_SQL} AS norm_title FROM books "
            f"  WHERE title IS NOT NULL AND TRIM(title) != '' AND academic_year = %s "
            f"  GROUP BY norm_title HAVING COUNT(DISTINCT price) > 1"
            f") "
            f"SELECT DISTINCT ON (b.book_id) b.book_id, b.title, b.price, b.vendor_name "
            f"FROM books b "
            f"WHERE {_NORM_TITLE_SQL.replace('title', 'b.title')} IN (SELECT norm_title FROM multi) "
            f"AND b.book_id IS NOT NULL AND TRIM(b.book_id) != '' "
            f"AND b.academic_year = %s "
            f"ORDER BY b.book_id, b.title",
            (year, year)
        )
        rows = cur.fetchall()
        book_ids = [r["book_id"] for r in rows]
        covers_present = set()
        if book_ids:
            try:
                cur.execute(
                    "SELECT book_id FROM book_covers WHERE book_id = ANY(%s)",
                    (book_ids,)
                )
                covers_present = {r["book_id"] for r in cur.fetchall()}
            except Exception as e:
                print(f"book_covers lookup skipped (table not ready?): {e}")
                conn.rollback()

    rows.sort(key=lambda r: (r["title"] or "", r["price"] or ""))
    return jsonify([
        {
            "bookId": r["book_id"],
            "title": r["title"] or "",
            "price": r["price"] or "",
            "vendor": r["vendor_name"] or "",
            "hasCover": r["book_id"] in covers_present,
        }
        for r in rows
    ])


def _compress_cover_image(image_bytes, max_dimension=800, quality=72):
    """
    Book cover படத்தை DB-ல் store பண்றதுக்கு முன் சிறிதாக்குகிறது:
    - அளவு max_dimension (px) தாண்டாதபடி resize (aspect ratio மாறாது)
    - JPEG-ஆக, குறைந்த quality-ல் மறுபடியும் encode (storage மிச்சம்)
    """
    img = PILImage.open(BytesIO(image_bytes))
    img = img.convert("RGB")  # PNG/JFIF transparency இருந்தாலும் JPEG-க்கு safe
    img.thumbnail((max_dimension, max_dimension), PILImage.LANCZOS)
    out = BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


@app.route("/api/admin/book_cover/upload", methods=["POST"])
@admin_required
def api_admin_book_cover_upload():
    book_id = (request.form.get("book_id") or "").strip()
    title = (request.form.get("title") or "").strip()
    f = request.files.get("file")

    if not book_id:
        return jsonify({"error": "Book Id தேர்ந்தெடுக்கவும்"}), 400
    if not f or not f.filename:
        return jsonify({"error": "முகப்புப் படத்தை தேர்ந்தெடுக்கவும்"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _ALLOWED_COVER_EXT:
        return jsonify({"error": "jpg / jpeg / jfif படங்கள் மட்டுமே அனுமதிக்கப்படும்"}), 400

    image_bytes = f.read()
    if not image_bytes:
        return jsonify({"error": "படக் கோப்பு காலியாக உள்ளது"}), 400
    if len(image_bytes) > 5 * 1024 * 1024:
        return jsonify({"error": "படத்தின் அளவு 5MB-க்கு குறைவாக இருக்க வேண்டும்"}), 400

    try:
        image_bytes = _compress_cover_image(image_bytes)
    except Exception as e:
        return jsonify({"error": f"படத்தை சரியாக படிக்க முடியவில்லை: {e}"}), 400

    with DBConn() as (conn, cur):
        cur.execute(
            "INSERT INTO book_covers (book_id, title, image, content_type, uploaded_at) "
            "VALUES (%s, %s, %s, 'image/jpeg', now()) "
            "ON CONFLICT (book_id) DO UPDATE SET "
            "title = EXCLUDED.title, image = EXCLUDED.image, "
            "content_type = EXCLUDED.content_type, uploaded_at = now()",
            (book_id, title, psycopg2.Binary(image_bytes))
        )

    return jsonify({"success": True, "message": f"'{book_id}' Book Id-க்கு முகப்புப் படம் சேமிக்கப்பட்டது."})


@app.route("/api/book_cover/<book_id>")
@login_required
def api_book_cover_get(book_id):
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT image, content_type FROM book_covers WHERE book_id = %s",
            (book_id,)
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "இந்த Book Id-க்கு முகப்புப் படம் இன்னும் அப்லோட் செய்யப்படவில்லை"}), 404
    return send_file(
        BytesIO(bytes(row["image"])),
        mimetype=row["content_type"] or "image/jpeg"
    )


# ==========================================================
# வேறு மாவட்ட DB-ல் (எ.கா. Dindigul) சேமித்த முகப்புப் படங்களை
# தலைப்பு (+விலை) பொருந்தும் புத்தகங்களுக்கு மட்டும் இங்கு இறக்குமதி செய்ய.
# - மூல DB-ல் படிக்க மட்டும் (read-only) — எதையும் மாற்றாது/அழிக்காது.
# - Book Id எல்லா மாவட்டங்களுக்கும் பொதுவானது: முதலில் அதே Book Id இருந்தால்
#   நேரடியாகப் பொருத்தும்; இல்லையென்றால் மட்டும் தலைப்பு (+விலை) வைத்துப் பொருத்தும்.
# - தெளிவாகப் பொருந்தாதவை (இரட்டை விலை குழப்பம்) தள்ளிவிடப்படும்.
# ==========================================================
def _norm_price_num(p):
    try:
        return round(float(re.sub(r'[^0-9.]', '', str(p or '')) or 'x'), 2)
    except Exception:
        return None


@app.route("/api/admin/book_covers/import_from_db", methods=["POST"])
@admin_required
def api_admin_book_covers_import_from_db():
    data = request.get_json(silent=True) or {}
    source_url = (data.get("source_url") or "").strip().strip('"\'').strip()
    dry_run = bool(data.get("dry_run", True))
    overwrite = bool(data.get("overwrite", False))

    if not (source_url.startswith("postgres://") or source_url.startswith("postgresql://")):
        return jsonify({"error": "Dindigul DB-ன் Database URL (postgres://... அல்லது postgresql://...) கொடுக்கவும்"}), 400

    # ---- 1. மூல DB-ல் இருந்து cover பட்டியல் (படம் இல்லாமல்) ----
    try:
        src = psycopg2.connect(source_url, connect_timeout=15)
    except Exception as e:
        msg = str(e).replace(source_url, "***")
        return jsonify({"error": "மூல DB-உடன் இணைக்க முடியவில்லை: " + msg[:200]}), 400
    try:
        src.set_session(readonly=True, autocommit=True)
        scur = src.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            scur.execute(
                "SELECT c.book_id, "
                "COALESCE(NULLIF(TRIM(c.title), ''), "
                "  (SELECT b.title FROM books b WHERE b.book_id = c.book_id AND b.title IS NOT NULL LIMIT 1)) AS title, "
                "(SELECT b.price FROM books b WHERE b.book_id = c.book_id "
                "   AND b.price IS NOT NULL AND TRIM(b.price) <> '' LIMIT 1) AS price "
                "FROM book_covers c ORDER BY c.book_id"
            )
        except Exception:
            # books table-ல் இருந்து விலை/தலைப்பு எடுக்க முடியாத DB — cover table மட்டும் படிப்போம்
            scur.execute("SELECT book_id, title, NULL AS price FROM book_covers ORDER BY book_id")
        src_rows = scur.fetchall()
    except Exception as e:
        src.close()
        return jsonify({"error": "மூல DB-ல் book_covers படிக்க முடியவில்லை: " + str(e).replace(source_url, "***")[:200]}), 400

    if not src_rows:
        src.close()
        return jsonify({"error": "மூல DB-ல் முகப்புப் படங்கள் எதுவும் இல்லை"}), 404

    # ---- 2. இந்த DB-ல் உள்ள புத்தகங்கள் (எல்லா ஆண்டுகளும்) ----
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT book_id, title, price FROM books "
            "WHERE book_id IS NOT NULL AND TRIM(book_id) <> ''"
        )
        target_rows = cur.fetchall()
        cur.execute("SELECT book_id FROM book_covers")
        existing_covers = {r["book_id"] for r in cur.fetchall()}

    # தலைப்பு (normalize) -> {book_id: price}
    target_by_title = defaultdict(dict)
    for r in target_rows:
        target_by_title[_norm_title(r["title"])][r["book_id"]] = r["price"]

    # மூலத்தில் ஒரே தலைப்புக்கு எத்தனை படங்கள்
    src_title_count = defaultdict(int)
    for r in src_rows:
        src_title_count[_norm_title(r["title"])] += 1

    # ---- 3. பொருத்துதல் ----
    plan = []            # (source_book_id, [target_book_ids])
    no_match, ambiguous = [], []
    target_ids = {r["book_id"] for r in target_rows}
    for r in src_rows:
        # 1) Book Id எல்லா மாவட்டங்களுக்கும் பொதுவானது — அதே Book Id இங்கு இருந்தால் நேரடியாகப் பொருத்து
        if r["book_id"] in target_ids:
            plan.append((r["book_id"], [r["book_id"]]))
            continue
        # 2) இங்கு அந்த Book Id இல்லையென்றால் மட்டும் தலைப்பு (+விலை) வைத்துப் பொருத்து
        nt = _norm_title(r["title"])
        if not nt:
            no_match.append(r["title"] or r["book_id"])
            continue
        cands = target_by_title.get(nt)
        if not cands:
            no_match.append(r["title"])
            continue
        sp = _norm_price_num(r["price"])
        exact = [bid for bid, pr in cands.items()
                 if sp is not None and _norm_price_num(pr) == sp]
        if exact:
            plan.append((r["book_id"], exact))
        elif len(cands) == 1 and src_title_count[nt] == 1:
            plan.append((r["book_id"], list(cands.keys())))
        else:
            ambiguous.append(r["title"])

    would_apply = 0
    already = 0
    for _, tids in plan:
        for t in tids:
            if t in existing_covers and not overwrite:
                already += 1
            else:
                would_apply += 1

    result = {
        "success": True,
        "dry_run": dry_run,
        "source_total": len(src_rows),
        "matched_titles": len(plan),
        "to_apply": would_apply,
        "already_have_cover": already,
        "no_match": len(no_match),
        "ambiguous": len(ambiguous),
        "no_match_samples": [t for t in no_match[:10]],
        "ambiguous_samples": [t for t in ambiguous[:10]],
    }

    if dry_run:
        src.close()
        return jsonify(result)

    # ---- 4. உண்மையான இறக்குமதி ----
    applied = 0
    try:
        need_ids = sorted({sid for sid, _ in plan})
        images = {}
        if need_ids:
            scur.execute(
                "SELECT book_id, image, content_type FROM book_covers WHERE book_id = ANY(%s)",
                (need_ids,)
            )
            for r in scur.fetchall():
                images[r["book_id"]] = (bytes(r["image"]), r["content_type"] or "image/jpeg")
    except Exception as e:
        src.close()
        return jsonify({"error": "படங்களை மூல DB-ல் இருந்து படிக்க முடியவில்லை: " + str(e).replace(source_url, "***")[:200]}), 400
    finally:
        try:
            src.close()
        except Exception:
            pass

    title_by_target = {}
    for r in target_rows:
        title_by_target.setdefault(r["book_id"], r["title"])

    with DBConn() as (conn, cur):
        for sid, tids in plan:
            img = images.get(sid)
            if not img:
                continue
            for t in tids:
                if t in existing_covers and not overwrite:
                    continue
                if overwrite:
                    cur.execute(
                        "INSERT INTO book_covers (book_id, title, image, content_type, uploaded_at) "
                        "VALUES (%s, %s, %s, %s, now()) "
                        "ON CONFLICT (book_id) DO UPDATE SET title = EXCLUDED.title, "
                        "image = EXCLUDED.image, content_type = EXCLUDED.content_type, uploaded_at = now()",
                        (t, title_by_target.get(t) or "", psycopg2.Binary(img[0]), img[1])
                    )
                else:
                    cur.execute(
                        "INSERT INTO book_covers (book_id, title, image, content_type, uploaded_at) "
                        "VALUES (%s, %s, %s, %s, now()) ON CONFLICT (book_id) DO NOTHING",
                        (t, title_by_target.get(t) or "", psycopg2.Binary(img[0]), img[1])
                    )
                applied += 1

    result["applied"] = applied
    return jsonify(result)


@app.route("/api/admin/book_titles/sync_from_db", methods=["POST"])
@admin_required
def api_admin_book_titles_sync_from_db():
    """
    வேறு மாவட்ட DB-ல் (எ.கா. Dindigul) திருத்தப்பட்ட தலைப்புகளை, அதே Book Id
    உள்ள புத்தகங்களுக்கு இந்த DB-ல் மாற்றும். மூல DB read-only.
    தேர்ந்தெடுத்த academic_year வரிசைகளில் மட்டும் மாற்றும் (இயல்பு: 2025-2026).
    """
    data = request.get_json(silent=True) or {}
    source_url = (data.get("source_url") or "").strip().strip('"\'').strip()
    dry_run = bool(data.get("dry_run", True))
    year = (data.get("year") or "2025-2026").strip()

    if not (source_url.startswith("postgres://") or source_url.startswith("postgresql://")):
        return jsonify({"error": "Dindigul DB-ன் Database URL (postgres://... அல்லது postgresql://...) கொடுக்கவும்"}), 400

    # ---- 1. மூல DB-ல் இருந்து book_id -> தலைப்பு ----
    try:
        src = psycopg2.connect(source_url, connect_timeout=15)
    except Exception as e:
        return jsonify({"error": "மூல DB-உடன் இணைக்க முடியவில்லை: " + str(e).replace(source_url, "***")[:200]}), 400
    year_filtered = True
    try:
        src.set_session(readonly=True, autocommit=True)
        scur = src.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        base_sql = ("SELECT DISTINCT book_id, TRIM(title) AS title FROM books "
                    "WHERE book_id IS NOT NULL AND TRIM(book_id) <> '' "
                    "AND title IS NOT NULL AND TRIM(title) <> ''")
        try:
            scur.execute(base_sql + " AND academic_year = %s", (year,))
        except Exception:
            # மூல DB-ல் academic_year column இல்லை — முழு table படிக்கப்படும்
            year_filtered = False
            scur.execute(base_sql)
        src_rows = scur.fetchall()
    except Exception as e:
        return jsonify({"error": "மூல DB-ல் books படிக்க முடியவில்லை: " + str(e).replace(source_url, "***")[:200]}), 400
    finally:
        try:
            src.close()
        except Exception:
            pass

    if not src_rows:
        return jsonify({"error": "மூல DB-ல் Book Id உள்ள புத்தகங்கள் எதுவும் கிடைக்கவில்லை"}), 404

    src_titles = defaultdict(set)
    for r in src_rows:
        src_titles[r["book_id"].strip()].add(r["title"])
    conflict_ids = {b for b, t in src_titles.items() if len(t) > 1}
    src_map = {b: next(iter(t)) for b, t in src_titles.items() if len(t) == 1}

    # ---- 2. இந்த DB-ல் (தேர்ந்தெடுத்த ஆண்டு) உள்ள தலைப்புகள் ----
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT book_id, title, COUNT(*) AS cnt FROM books "
            "WHERE academic_year = %s AND book_id IS NOT NULL AND TRIM(book_id) <> '' "
            "GROUP BY book_id, title",
            (year,)
        )
        target_rows = cur.fetchall()

    changes = {}          # book_id -> (புதிய தலைப்பு, [(பழைய தலைப்பு, rows)])
    same = 0
    for r in target_rows:
        bid = (r["book_id"] or "").strip()
        new_t = src_map.get(bid)
        if not new_t:
            continue
        if (r["title"] or "").strip() == new_t:
            same += r["cnt"]
            continue
        changes.setdefault(bid, (new_t, []))[1].append((r["title"], r["cnt"]))

    target_ids = {(r["book_id"] or "").strip() for r in target_rows}
    not_in_source = len(target_ids - set(src_map) - conflict_ids)
    rows_to_change = sum(c for _, olds in changes.values() for _, c in olds)

    result = {
        "success": True,
        "dry_run": dry_run,
        "year": year,
        "year_filtered_source": year_filtered,
        "source_book_ids": len(src_map),
        "target_book_ids": len(target_ids),
        "titles_to_change": len(changes),
        "rows_to_change": rows_to_change,
        "already_same_rows": same,
        "not_in_source": not_in_source,
        "source_conflicts": len(conflict_ids),
        "samples": [
            {"book_id": b, "old": olds[0][0], "new": new_t}
            for b, (new_t, olds) in list(changes.items())[:15]
        ],
    }
    if dry_run:
        return jsonify(result)

    # ---- 3. உண்மையான மாற்றம் — அனைத்தும் ஒரே UPDATE-ல் (வேகமாக, timeout வராமல்) ----
    bids = list(changes.keys())
    new_titles = [changes[b][0] for b in bids]
    updated = 0
    with DBConn() as (conn, cur):
        cur.execute(
            "UPDATE books b SET title = v.new_title "
            "FROM (SELECT unnest(%s::text[]) AS bid, unnest(%s::text[]) AS new_title) v "
            "WHERE b.academic_year = %s AND TRIM(b.book_id) = v.bid "
            "AND b.title IS DISTINCT FROM v.new_title",
            (bids, new_titles, year)
        )
        updated = cur.rowcount
    try:
        with DBConn() as (conn, cur):
            cur.execute(
                "UPDATE book_covers c SET title = v.new_title "
                "FROM (SELECT unnest(%s::text[]) AS bid, unnest(%s::text[]) AS new_title) v "
                "WHERE c.book_id = v.bid",
                (bids, new_titles)
            )
    except Exception as e:
        print(f"book_covers title sync skipped: {e}")
    result["updated_rows"] = updated
    return jsonify(result)


# ==========================================================
# LIBRARIAN — Book Search Details (read-only, ஒரு நூலகத்திற்கு
# அனுப்பப்பட்ட/பிரிக்கப்பட்ட புத்தகங்கள் மட்டும்)
# ==========================================================
@app.route("/api/librarian/search")
@login_required
def api_librarian_search():
    library = request.args.get("library", "").strip()
    text = request.args.get("q", "").strip()
    if not library:
        return jsonify({"error": "நூலகம் தேர்ந்தெடுக்கவும்"}), 400
    if len(text) < 4:
        return jsonify({"error": "குறைந்தது 4 எழுத்துக்கள் தட்டச்சு செய்யவும்"}), 400
    active_year = _get_setting("active_academic_year", BASE_YEAR)
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT id, title, author FROM books "
            f"WHERE library_name_tm = %s AND {_SENT_SQL} AND title ILIKE %s "
            "AND academic_year = %s "
            "ORDER BY title LIMIT 50",
            (library, f"%{text}%", active_year)
        )
        rows = cur.fetchall()
    return jsonify([
        {"id": r["id"], "title": r["title"] or "", "author": r["author"] or ""}
        for r in rows
    ])


@app.route("/api/librarian/book/<int:book_id>")
@login_required
def api_librarian_book_detail(book_id):
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT title, state_acc_number, central_number, branch_number, "
            "author, vendor_name, year_pub, price, accepted_price, library_name_tm "
            "FROM books WHERE id=%s", (book_id,)
        )
        r = cur.fetchone()
    if not r:
        return jsonify({"error": "புத்தகம் கிடைக்கவில்லை"}), 404
    return jsonify({
        "title": r["title"] or "—",
        "state_acc_number": r["state_acc_number"] or "—",
        "central_number": _fmt_whole(r["central_number"]) or "—",
        "branch_number": _fmt_whole(r["branch_number"]) or "—",
        "author": r["author"] or "—",
        "publisher": r["vendor_name"] or "—",
        "year_pub": r["year_pub"] or "—",
        "price": _fmt_price(r["price"]) or "—",
        "accepted_price": _fmt_price(r["accepted_price"]) or "—",
        "library_name_tm": r["library_name_tm"] or "—",
    })
@app.route("/api/book_detail")
@login_required
def api_book_detail():
    title = request.args.get('title', '')
    price = request.args.get('price', '')
    year = request.args.get('year') or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT author, vendor_name, "
            "COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE set_number IS NOT NULL AND set_number != '') AS assigned "
            "FROM books WHERE title=%s AND price=%s AND academic_year=%s "
            "GROUP BY author, vendor_name LIMIT 1",
            (title, price, year)
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "book இல்லை"}), 404

        isbns = _isbns_for_title(cur, title, year)
        if len(isbns) > 1:
            return jsonify({
                "error": _multi_isbn_block_message(isbns),
                "code": "MULTI_ISBN",
                "isbns": isbns
            }), 409

        cur.execute(
            "SELECT DISTINCT library_type FROM books "
            "WHERE title=%s AND price=%s AND (set_number IS NULL OR set_number='') "
            "AND academic_year=%s AND library_type IS NOT NULL ORDER BY library_type",
            (title, price, year)
        )
        lib_types = [r["library_type"] for r in cur.fetchall()]

    total = row["total"]
    assigned = row["assigned"]
    return jsonify({
        "title": title, "author": row["author"] or "N/A", "vendor": row["vendor_name"] or "N/A",
        "price": price, "total": total, "assigned": assigned, "remaining": total - assigned,
        "lib_types": lib_types
    })


@app.route("/api/libraries_for_type")
@login_required
def api_libraries_for_type():
    title = request.args.get('title', '')
    price = request.args.get('price', '')
    lib_type = request.args.get('lib_type', '')
    year = request.args.get('year') or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT library_name_tm FROM books "
            "WHERE title=%s AND price=%s AND library_type=%s "
            "AND (set_number IS NULL OR set_number='') "
            "AND academic_year=%s AND library_name_tm IS NOT NULL ORDER BY library_name_tm",
            (title, price, lib_type, year)
        )
        libs = [r["library_name_tm"] for r in cur.fetchall()]
    return jsonify(libs)


# ==========================================================
# ஊதிய மையம் (WAGE CENTER) — state_acc_number_1 column-ல் நூலகம் வாரியாக
# சேமிக்கப்பட்டுள்ள ஊதிய மைய குறியீட்டின் அடிப்படையில், "பிரிக்க" / "அனுப்ப"
# இரண்டிலும் அந்த ஊதிய மையத்திற்குண்டான நூலகங்கள் மட்டும் காட்ட உதவும்.
# dclstaff — அதிகபட்சம் 3 ஊதிய மையங்கள் வரை ஒரே நேரத்தில் தேர்வு செய்யலாம்
# (query string-ல் கமா-பிரிக்கப்பட்டு அனுப்பப்படும்: wage_center=A,B,C).
# admin எப்போதும் அனைத்து ஊதிய மையங்களையும் பார்ப்பார் — filter இல்லை.
# வரிசை எப்போதும்: மாவட்ட மைய நூலகம் (DCL) → முழு நேர (FTL) → கிளை (BL) → ஊர்ப்புற (VL)
# ==========================================================
def _get_wage_centers_param():
    """query string-ல் இருந்து wage_center param-ஐ படிக்கும் — கமா-பிரிக்கப்பட்ட
    பல மதிப்புகளை (அதிகபட்சம் 3) ஏற்கும். காலியாக இருந்தால் [] — 'அனைத்தும்' எனப் பொருள்."""
    raw = request.args.get("wage_center", "")
    centers = [c.strip() for c in raw.split(",") if c.strip()]
    return centers[:3]


def _lib_type_rank(lib_type):
    """library_type text-ஐ வைத்து DCL→FTL→BL→VL வரிசைக்கான rank கொடுக்கும்.
    'Full Time Branch Library -FTL' போன்ற பல்வேறு உரை வடிவங்களுக்கும் பொருந்தும்படி
    ஆங்கில code-ஐயும், தமிழ் வார்த்தைகளையும் இரண்டையும் பரிசோதிக்கிறோம்."""
    orig = lib_type or ""
    t = orig.upper()
    if re.search(r'(?<![A-Z])DCL(?![A-Z])', t) or 'மாவட்ட' in orig:
        return 0
    if re.search(r'(?<![A-Z])FTL(?![A-Z])', t) or 'முழு நேர' in orig:
        return 1
    if re.search(r'(?<![A-Z])BL(?![A-Z])', t) or 'கிளை' in orig:
        return 2
    if re.search(r'(?<![A-Z])VL(?![A-Z])', t) or 'கிராம' in orig or 'ஊர்ப்புற' in orig:
        return 3
    return 4


@app.route("/api/wage_centers/available")
@login_required
def api_wage_centers_available():
    year = request.args.get('year') or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT TRIM(state_acc_number_1) AS wc FROM books "
            "WHERE state_acc_number_1 IS NOT NULL AND TRIM(state_acc_number_1) != '' "
            "AND academic_year=%s ORDER BY wc",
            (year,)
        )
        centers = [r["wc"] for r in cur.fetchall()]
    return jsonify(centers)


# dclstaff எந்த ஊதிய மைய(ங்க)ளில் வேலை செய்ய வேண்டும் என Admin தேர்ந்தெடுத்து
# வைக்கும் setting — dclstaff-க்கு selector இல்லை, இதையே தானாக பின்பற்றுவார்கள்.
@app.route("/api/wage_centers/active", methods=["GET"])
@login_required
def api_wage_centers_active_get():
    raw = _get_setting("active_wage_centers", "")
    centers = [c.strip() for c in raw.split(",") if c.strip()] if raw else []
    return jsonify({"active_wage_centers": centers})


@app.route("/api/wage_centers/active", methods=["POST"])
@admin_required
def api_wage_centers_active_set():
    data = request.json or {}
    centers = data.get("wage_centers", [])
    if not isinstance(centers, list):
        return jsonify({"error": "wage_centers ஒரு பட்டியலாக இருக்க வேண்டும்"}), 400
    centers = [str(c).strip() for c in centers if str(c).strip()][:3]
    _set_setting("active_wage_centers", ",".join(centers))
    return jsonify({"success": True, "active_wage_centers": centers})


@app.route("/api/libraries_for_wage_center")
@login_required
def api_libraries_for_wage_center():
    title = request.args.get('title', '')
    price = request.args.get('price', '')
    wage_centers = _get_wage_centers_param()
    year = request.args.get('year') or BASE_YEAR
    with DBConn() as (conn, cur):
        if wage_centers:
            placeholders = ",".join(["%s"] * len(wage_centers))
            cur.execute(
                "SELECT library_name_tm, MIN(library_type) AS library_type FROM books "
                f"WHERE title=%s AND price=%s AND TRIM(state_acc_number_1) IN ({placeholders}) "
                "AND (set_number IS NULL OR set_number='') "
                "AND academic_year=%s AND library_name_tm IS NOT NULL "
                "GROUP BY library_name_tm",
                (title, price, *wage_centers, year)
            )
        else:
            cur.execute(
                "SELECT library_name_tm, MIN(library_type) AS library_type FROM books "
                "WHERE title=%s AND price=%s "
                "AND (set_number IS NULL OR set_number='') "
                "AND academic_year=%s AND library_name_tm IS NOT NULL "
                "GROUP BY library_name_tm",
                (title, price, year)
            )
        rows = cur.fetchall()
    rows.sort(key=lambda r: (_lib_type_rank(r["library_type"]), r["library_name_tm"] or ""))
    return jsonify([r["library_name_tm"] for r in rows])


# ==========================================================
# "தவறான பதிவு நீக்கம்" (RECLAIM) — தவறாக பிரிக்க/அனுப்ப ஆன புத்தகங்களை
# மீண்டும் unassigned நிலைக்கு கொண்டுவருதல் + விடுவிக்கப்படும் central/branch
# எண்களை pool-ல் சேமித்து அடுத்த Assign-ல் மறுபடியும் வழங்குதல்.
# ==========================================================
@app.route("/api/reclaim/search")
@admin_required
def api_reclaim_search():
    text = request.args.get('q', '').strip()
    if len(text) < 2:
        return jsonify([])
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT title, price, vendor_name, COUNT(*) AS count "
            "FROM books WHERE title ILIKE %s AND central_number IS NOT NULL "
            "GROUP BY title, price, vendor_name ORDER BY title LIMIT 100",
            (f"%{text}%",)
        )
        rows = cur.fetchall()
    return jsonify([{
        "title": r["title"] or "",
        "vendor": r["vendor_name"] or "",
        "price": r["price"] or "",
        "count": r["count"],
    } for r in rows])


@app.route("/api/reclaim/rows")
@admin_required
def api_reclaim_rows():
    title = request.args.get('title', '')
    price = request.args.get('price', '')
    year = request.args.get('year') or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            f"SELECT id, library_name_tm, central_number, branch_number, set_number, "
            f"({_SENT_SQL}) AS is_sent "
            "FROM books WHERE title=%s AND price=%s AND central_number IS NOT NULL "
            "AND academic_year=%s "
            "ORDER BY library_name_tm, central_number",
            (title, price, year)
        )
        rows = cur.fetchall()
    return jsonify([{
        "id": r["id"],
        "library_name_tm": r["library_name_tm"] or "—",
        "central_number": r["central_number"],
        "branch_number": r["branch_number"],
        "set_number": r["set_number"] or "",
        "sent": r["is_sent"],
    } for r in rows])


@app.route("/api/reclaim/execute", methods=["POST"])
@admin_required
def api_reclaim_execute():
    data = request.json or {}
    ids = data.get("ids", [])
    year = data.get("year") or BASE_YEAR
    if not ids:
        return jsonify({"error": "குறைந்தது ஒரு வரியை தேர்ந்தெடுக்கவும்"}), 400

    try:
        with DBConn() as (conn, cur):
            cur.execute(
                "SELECT id, central_number, branch_number, librarian_id FROM books "
                "WHERE id = ANY(%s) AND central_number IS NOT NULL FOR UPDATE",
                (ids,)
            )
            rows = cur.fetchall()
            if not rows:
                return jsonify({"error": "தேர்ந்தெடுத்தவை ஏற்கனவே reclaim ஆகிவிட்டன — refresh செய்து பாருங்கள்"}), 400

            cur.execute(
                "UPDATE books SET set_number=NULL, central_number=NULL, branch_number=NULL, "
                "work_status=NULL, sent_details=NULL, date=NULL WHERE id = ANY(%s)",
                ([r["id"] for r in rows],)
            )

            central_vals = [r["central_number"] for r in rows if r["central_number"] is not None]
            if central_vals:
                cur.execute(
                    "INSERT INTO reclaimed_central (academic_year, central_number) VALUES " +
                    ",".join(["(%s,%s)"] * len(central_vals)) +
                    " ON CONFLICT (academic_year, central_number) DO NOTHING",
                    tuple(x for v in central_vals for x in (year, v))
                )

            branch_pairs = [(year, str(r["librarian_id"]).strip(), r["branch_number"])
                            for r in rows if r["branch_number"] is not None and r["librarian_id"]]
            if branch_pairs:
                cur.executemany(
                    "INSERT INTO reclaimed_branch (academic_year, librarian_id, branch_number) VALUES (%s, %s, %s) "
                    "ON CONFLICT (academic_year, librarian_id, branch_number) DO NOTHING",
                    branch_pairs
                )
    except Exception as e:
        app.logger.exception("api_reclaim_execute failed")
        return jsonify({"error": f"Reclaim தோல்வி: {e}"}), 500

    return jsonify({
        "success": True,
        "message": f"{len(rows)} புத்தகங்கள் மீளப்பெறப்பட்டு, மறுபடியும் 'பிரிக்க' பட்டியலில் சேர்க்கப்பட்டன."
    })


@app.route("/api/reclaim/pool_status")
@admin_required
def api_reclaim_pool_status():
    year = request.args.get('year') or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT central_number FROM reclaimed_central WHERE academic_year=%s ORDER BY central_number",
            (year,)
        )
        central = [r["central_number"] for r in cur.fetchall()]
        cur.execute(
            "SELECT b.librarian_id, lib.library_name_tm, "
            "ARRAY_AGG(DISTINCT b.branch_number ORDER BY b.branch_number) AS numbers "
            "FROM reclaimed_branch b "
            "LEFT JOIN ("
            "    SELECT DISTINCT ON (librarian_id) librarian_id, library_name_tm "
            "    FROM books WHERE librarian_id IS NOT NULL ORDER BY librarian_id"
            ") lib ON lib.librarian_id = b.librarian_id "
            "WHERE b.academic_year=%s "
            "GROUP BY b.librarian_id, lib.library_name_tm ORDER BY lib.library_name_tm",
            (year,)
        )
        branch_rows = cur.fetchall()
    return jsonify({
        "central": central,
        "branch": [{"library_name_tm": r["library_name_tm"] or r["librarian_id"], "numbers": r["numbers"]}
                   for r in branch_rows]
    })


@app.route("/api/assign/reclaim_check", methods=["POST"])
@staff_or_admin_required
def api_assign_reclaim_check():
    data = request.json or {}
    libraries = data.get("libraries", [])
    year = data.get("year") or BASE_YEAR
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT central_number FROM reclaimed_central WHERE academic_year=%s ORDER BY central_number",
            (year,)
        )
        central = [r["central_number"] for r in cur.fetchall()]

        branch = {}
        if libraries:
            cur.execute(
                "SELECT DISTINCT library_name_tm, librarian_id FROM books "
                "WHERE library_name_tm = ANY(%s) AND librarian_id IS NOT NULL AND academic_year=%s",
                (libraries, year)
            )
            lib_id_map = {r["library_name_tm"]: str(r["librarian_id"]).strip() for r in cur.fetchall()}
            for lib_name, lib_id in lib_id_map.items():
                cur.execute(
                    "SELECT branch_number FROM reclaimed_branch WHERE librarian_id=%s AND academic_year=%s "
                    "ORDER BY branch_number",
                    (lib_id, year)
                )
                nums = [r["branch_number"] for r in cur.fetchall()]
                if nums:
                    branch[lib_name] = nums

    return jsonify({"central": central, "branch": branch})


# ==========================================================
# ASSIGN-TIME WARNING — இதே தலைப்புள்ள நூல் வேறு விலைக்கு ஏற்கனவே
# தேர்ந்தெடுக்கப்பட்ட நூலகங்களுக்கு பிரிக்கப்பட்டு/அனுப்பப்பட்டிருந்தால்
# எச்சரிக்கை காட்ட (block செய்யாது — உண்மையாகவே தேவை என்றால் தொடரலாம்)
# ==========================================================
@app.route("/api/assign/price_check", methods=["POST"])
@staff_or_admin_required
def api_assign_price_check():
    data = request.json or {}
    title = data.get('title', '')
    price = str(data.get('price', ''))
    libraries = data.get('libraries', [])
    year = data.get('year') or BASE_YEAR
    if not title or not libraries:
        return jsonify({"warnings": []})

    norm_title = _norm_title(title)

    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT price, "
            "COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),'')) AS lib "
            "FROM books "
            f"WHERE {_NORM_TITLE_SQL} = %s "
            "AND price != %s "
            "AND (set_number IS NOT NULL AND set_number != '') "
            "AND academic_year = %s "
            "AND COALESCE(NULLIF(TRIM(library_name_tm),''), NULLIF(TRIM(library_name),'')) = ANY(%s)",
            (norm_title, price, year, libraries)
        )
        rows = cur.fetchall()

    by_lib = defaultdict(set)
    for r in rows:
        if r["lib"]:
            by_lib[r["lib"]].add(r["price"] or "—")

    warnings = [
        {
            "library": lib,
            "prices": sorted(prices),
            "message": (
                f"இதே தலைப்புள்ள நூல் — {', '.join(sorted(prices))} இந்த விலைக்கானது "
                f"ஏற்கனவே '{lib}' இந்த நூலகத்திற்கு அனுப்பப் பட்டுள்ளது"
            )
        }
        for lib, prices in by_lib.items()
    ]
    return jsonify({"warnings": warnings})


# ==========================================================
# ASSIGN — duplicate-proof (2 staff simultaneous-ஆக வேலை செய்தாலும் safe)
#
# எப்படி safe ஆகிறது:
#   1. FOR UPDATE — matching unassigned rows-ஐ இந்த transaction lock செய்யும்.
#      இன்னொரு staff அதே rows-ஐ assign செய்ய முயன்றால், அவர் transaction
#      இது commit ஆகும் வரை block ஆகும்; commit ஆனபின் அந்த rows already
#      assigned ஆகிவிட்டதால் அவருடைய query-ல் 0 rows தான் கிடைக்கும்
#      ('ஏற்கனவே assign ஆகிவிட்டது' error காட்டப்படும்) — duplicate தடுக்கப்படுகிறது.
#   2. counters table — central_number & branch_number இரண்டுக்கும் FOR UPDATE
#      row lock போட்டு atomic-ஆக அடுத்த எண்ணை generate செய்யும்.
# ==========================================================
@app.route("/api/assign", methods=["POST"])
@staff_or_admin_required
def api_assign():
    data = request.json or {}
    title = data.get('title')
    price = str(data.get('price'))
    lib_type = data.get('lib_type')
    libraries = data.get('libraries', [])
    set_number = data.get('set_number')
    use_reclaimed = bool(data.get('use_reclaimed'))
    year = data.get('year') or BASE_YEAR
    central_ckey = _counter_key("central_number", year)

    if not libraries or not set_number:
        return jsonify({'error': 'நூலகம் மற்றும் SET NUMBER தேர்வு செய்யவும்'}), 400

    today = datetime.now().strftime("%d/%m/%Y")

    with DBConn() as (conn, cur):
        try:
            # 0) Defense-in-depth: multi-ISBN தலைப்புகளை பிரிக்க அனுமதிக்கக் கூடாது
            #    (frontend book_detail-லேயே block ஆனாலும், நேரடியாக இந்த API-க்கு
            #    அனுப்பப்பட்டாலும் server-side-ஆகவே தடுக்கப்படும்)
            isbns = _isbns_for_title(cur, title, year)
            if len(isbns) > 1:
                return jsonify({
                    "error": _multi_isbn_block_message(isbns),
                    "code": "MULTI_ISBN",
                    "isbns": isbns
                }), 409

            # 1) matching unassigned rows-ஐ lock செய் (இந்த ஆண்டுக்கு மட்டும்)
            #    lib_type கொடுக்கப்படாவிட்டால் (ஊதிய மையம் வழியாக பல நூலக
            #    வகைகளும் கலந்து தேர்ந்தெடுக்கப்பட்டிருக்கலாம்) — library_type
            #    கட்டுப்பாடு இல்லாமல், library_name_tm மட்டும் வைத்து lock செய்கிறோம்.
            if lib_type:
                cur.execute(
                    "SELECT id, librarian_id FROM books "
                    "WHERE title=%s AND price=%s AND library_type=%s "
                    "AND library_name_tm = ANY(%s) "
                    "AND (set_number IS NULL OR set_number='') "
                    "AND academic_year=%s "
                    "ORDER BY id "
                    "FOR UPDATE",
                    (title, price, lib_type, libraries, year)
                )
            else:
                cur.execute(
                    "SELECT id, librarian_id FROM books "
                    "WHERE title=%s AND price=%s "
                    "AND library_name_tm = ANY(%s) "
                    "AND (set_number IS NULL OR set_number='') "
                    "AND academic_year=%s "
                    "ORDER BY id "
                    "FOR UPDATE",
                    (title, price, libraries, year)
                )
            rows = cur.fetchall()
            if not rows:
                return jsonify({'error': 'பதிவு செய்ய எதுவும் இல்லை (ஏற்கனவே assign ஆகியிருக்கலாம் — refresh செய்து பாருங்கள்)'}), 400

            n = len(rows)
            lib_ids_needed = sorted({str(r["librarian_id"]).strip() for r in rows if r["librarian_id"]})
            lib_id_counts = defaultdict(int)
            for r in rows:
                if r["librarian_id"]:
                    lib_id_counts[str(r["librarian_id"]).strip()] += 1

            # 1b) reclaim pool-ல் இருந்து எடுக்க வேண்டுமா (admin/staff உறுதிப்படுத்தினால் மட்டும்) — இந்த ஆண்டுக்கு மட்டும்
            central_pool_used = []      # இந்த batch-க்கு பயன்படுத்தும் reclaimed central numbers
            branch_pool_used = {}       # lib_id -> [reclaimed branch numbers]
            if use_reclaimed:
                cur.execute(
                    "SELECT central_number FROM reclaimed_central WHERE academic_year=%s "
                    "ORDER BY central_number FOR UPDATE",
                    (year,)
                )
                avail_central = [r["central_number"] for r in cur.fetchall()]
                central_pool_used = avail_central[:n]
                if central_pool_used:
                    cur.execute(
                        "DELETE FROM reclaimed_central WHERE academic_year=%s AND central_number = ANY(%s)",
                        (year, central_pool_used)
                    )
                for lib_id in lib_ids_needed:
                    cur.execute(
                        "SELECT branch_number FROM reclaimed_branch WHERE librarian_id=%s AND academic_year=%s "
                        "ORDER BY branch_number FOR UPDATE",
                        (lib_id, year)
                    )
                    avail_branch = [r["branch_number"] for r in cur.fetchall()]
                    take_n = min(len(avail_branch), lib_id_counts[lib_id])
                    used = avail_branch[:take_n]
                    if used:
                        cur.execute(
                            "DELETE FROM reclaimed_branch WHERE librarian_id=%s AND academic_year=%s AND branch_number = ANY(%s)",
                            (lib_id, year, used)
                        )
                        branch_pool_used[lib_id] = list(used)

            # 2) central_number counter atomic-ஆக reserve செய் (pool-ல் இருந்து எடுத்தவை போக மீதிக்கு மட்டும்)
            central_needed_from_counter = n - len(central_pool_used)
            cur.execute(
                "INSERT INTO counters (key, next_value) VALUES (%s, 1) ON CONFLICT (key) DO NOTHING",
                (central_ckey,)
            )
            cur.execute("SELECT next_value FROM counters WHERE key=%s FOR UPDATE", (central_ckey,))
            central_start = cur.fetchone()["next_value"]
            if central_needed_from_counter:
                cur.execute(
                    "UPDATE counters SET next_value = next_value + %s WHERE key=%s",
                    (central_needed_from_counter, central_ckey)
                )

            # 3) library-வாரியாக branch_number counters reserve செய் (இந்த ஆண்டுக்குரிய key)
            #    (ஒரே transaction-ல் பல libraries-க்கு counters lock ஆவதால்
            #     deadlock தவிர்க்க librarian_id வரிசைப்படி lock செய்கிறோம்)
            branch_next = {}
            branch_keys = {}
            for lib_id in lib_ids_needed:
                key = _counter_key(f"branch:{lib_id}", year)
                branch_keys[lib_id] = key
                cur.execute("SELECT next_value FROM counters WHERE key=%s FOR UPDATE", (key,))
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        "INSERT INTO counters (key, next_value) VALUES (%s, 1)", (key,)
                    )
                    branch_next[lib_id] = 1
                else:
                    branch_next[lib_id] = row["next_value"]

            # 4) ஒவ்வொரு row-க்கும் central/branch எண் assign செய்து UPDATE
            #    (reclaim pool-ல் இருந்து எடுத்த எண்கள் முதலில் — சின்ன எண் முதலில்;
            #     pool தீர்ந்தபின் மட்டும் மாறாத last-number+1 counter தொடரும்)
            central_queue = list(central_pool_used)
            central_counter = central_start
            branch_queues = {lib_id: list(nums) for lib_id, nums in branch_pool_used.items()}
            reclaimed_central_count = 0
            reclaimed_branch_count = 0

            for r in rows:
                lib_id = str(r["librarian_id"]).strip() if r["librarian_id"] else None

                if central_queue:
                    central_val = central_queue.pop(0)
                    reclaimed_central_count += 1
                else:
                    central_val = central_counter
                    central_counter += 1

                branch_val = None
                if lib_id and branch_queues.get(lib_id):
                    branch_val = branch_queues[lib_id].pop(0)
                    reclaimed_branch_count += 1
                elif lib_id and lib_id in branch_next:
                    branch_val = branch_next[lib_id]
                    branch_next[lib_id] += 1

                cur.execute(
                    "UPDATE books SET set_number=%s, central_number=%s, branch_number=%s, "
                    "work_status=%s WHERE id=%s",
                    (set_number, central_val, branch_val, today, r["id"])
                )

            # 5) branch counters-ஐ புதிய next value-க்கு save செய்
            for lib_id, nxt in branch_next.items():
                cur.execute(
                    "UPDATE counters SET next_value=%s WHERE key=%s",
                    (nxt, branch_keys[lib_id])
                )

            msg = f"{n} புத்தகங்கள் பதிவு செய்யப்பட்டன!\nSet: {set_number}"
            if reclaimed_central_count or reclaimed_branch_count:
                msg += (f"\n♻️ Reclaim pool-ல் இருந்து — மைய எண்: {reclaimed_central_count}, "
                        f"கிளை எண்: {reclaimed_branch_count}")
            if central_needed_from_counter:
                msg += f"\nCentral (புதியது): {central_start}-{central_counter - 1}"

            return jsonify({'success': True, 'message': msg})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
