# -*- coding: utf-8 -*-
"""
BOOKPURCHASE — Online (Multi-user) பதிப்பு
Original main.py-ன் Excel/pandas logic-ஐ PostgreSQL-க்கு migrate செய்யப்பட்டது.

இந்த கட்டத்தில் தயார்: Login, Search, Book Detail, Assign (duplicate-proof).
அடுத்த கட்டம்: Renumber, Backup/Restore, Reports 1-7, Send/Mark (Admin routes).
"""
import os
import re
import threading
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime
from io import BytesIO
import pandas as pd
import psycopg2.extras
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
  .box{background:white;padding:40px 32px;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.3);
       width:100%;max-width:340px;box-sizing:border-box;}
  h2{color:#0b3d3d;margin-top:0;text-align:center;}
  label{display:block;font-size:13px;font-weight:600;color:#0b3d3d;margin:14px 0 6px;}
  select, input{width:100%;padding:12px;border:1px solid #ccc;border-radius:8px;
        font-size:1rem;box-sizing:border-box;font-family:'Noto Sans Tamil',sans-serif;}
  button{width:100%;padding:12px;background:#0b3d3d;color:white;border:none;
         border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;margin-top:18px;}
  .err{color:#c0392b;text-align:center;margin-top:10px;font-size:.9rem;}
  #pwdField{display:none;}
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
    "admin": "Dlodgl@789",
    "dclstaff": "123456789",
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
            "SELECT vendor_name, price FROM books WHERE isbn=%s AND academic_year=%s "
            "AND vendor_name IS NOT NULL AND TRIM(vendor_name) != '' LIMIT 1",
            (isbn, year)
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "SELECT vendor_name, price FROM books WHERE isbn=%s AND academic_year=%s LIMIT 1",
                (isbn, year)
            )
            row = cur.fetchone()
    return jsonify({
        "vendor_name": (row["vendor_name"] if row else "") or "",
        "price": (row["price"] if row else "") or ""
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
# NORMALIZED TITLE — "ஒரே தலைப்பு" ஒப்பீடு எங்கும் ஒரே மாதிரி இருக்க
# (பிரிக்கப்படாதவை, அனுப்பப்பட்டவை, assign-time warning ஆகிய எல்லா
# இடங்களிலும் இதே normalization பயன்படுத்தப்படுகிறது):
#   1. இடைவெளிகள் ஒன்றாக சுருக்கப்படும்
#   2. பெரிய/சிறிய எழுத்து வேறுபாடு பொருட்படுத்தப்படாது
#   3. "-" (ஹைபன்) இருந்தால், அதற்கு முந்தைய பகுதி மட்டும் ஒப்பிடப்படும் —
#      இதனால் "இந்தியா-INDIA" மற்றும் "இந்தியா-" ஆகிய இரண்டும்
#      ஒரே தலைப்பாகவே கருதப்படும் (பின் பகுதி இருந்தாலும், இல்லாவிட்டாலும்)
# ==========================================================
_NORM_TITLE_SQL = (
    "UPPER(TRIM(SPLIT_PART(REGEXP_REPLACE(TRIM(title), '\\s+', ' ', 'g'), '-', 1)))"
)


def _norm_title(t):
    """Python-side equivalent of _NORM_TITLE_SQL — frontend இல்லாத ஒப்பீடுகளுக்கு."""
    t = re.sub(r'\s+', ' ', (t or '').strip())
    t = t.split('-', 1)[0].strip()
    return t.upper()


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
    with DBConn() as (conn, cur):
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
    with DBConn() as (conn, cur):
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
        page_size = max(1, min(100, int(request.args.get("page_size", 10))))
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


_excel_export_jobs = {}   # (dtype, year) -> {"status": running|done|error, "path": str, "fname": str, "error": str}


def _build_excel_export_job(app_ctx, dtype, year, where, fname_prefix):
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

            db_col_names = [c for c, _ in _EXCEL_COLUMNS]
            db_cols = ", ".join(db_col_names)
            excel_headers = [h for _, h in _EXCEL_COLUMNS]

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
                        f"SELECT id, {db_cols} FROM books WHERE {where} AND id > %s "
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
    # "done"/"error" state-ஐயும் மீண்டும் build செய்யும் — தரவு மாறியிருக்கலாம்
    threading.Thread(target=_build_excel_export_job, args=(app, dtype, year, where, fname_prefix), daemon=True).start()
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
# REPORTS — HTML அறிக்கை உருவாக்கி DB-ல் சேமிக்கப்பட்டு, Frontend அதை
# புதிய tab-ல் திறக்கும் (பயனர் Ctrl+P → Save as PDF செய்யலாம்)
# ==========================================================
def _save_report(html, title):
    with DBConn() as (conn, cur):
        cur.execute(
            "INSERT INTO generated_reports (title, html) VALUES (%s, %s) RETURNING id",
            (title, html)
        )
        rid = cur.fetchone()["id"]
    return rid


@app.route("/reports/view/<int:report_id>")
@login_required
def view_report(report_id):
    with DBConn() as (conn, cur):
        cur.execute("SELECT html FROM generated_reports WHERE id=%s", (report_id,))
        row = cur.fetchone()
    if not row:
        return "அறிக்கை கிடைக்கவில்லை", 404
    return row["html"]


@app.route("/api/report/<int:num>")
@login_required
def api_report(num):
    today_str = datetime.now().strftime("%d/%m/%Y")
    year = request.args.get('year') or BASE_YEAR
    try:
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
                    return jsonify({"error": "இன்னும் எந்த பணியும் பதிவு செய்யப்படவில்லை"})
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
                    f"<tr><td>{i}</td><td style='text-align:left'>{l}</td><td>{vc}</td><td>{tmc}</td><td>{enc}</td></tr>"
                    for i, (l, vc, tmc, enc) in enumerate(rows, 1)
                )
                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 2 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட நூலக ஆணைக்குழு {DISTRICT_NAME}</p><p class="t2">மாவட்ட மைய நூலகம்</p>
<p class="t3">2026-2027 புதிய நூல்கள் — மொத்த நிலை விவரம்</p><p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th>வ.எண்</th><th>விவரம்</th><th>பதிப்பகங்கள்</th><th>தமிழ்</th><th>ஆங்கிலம்</th></tr></thead>
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

                def _split10(total, total_tm, assigned, assigned_tm, sent, sent_tm):
                    # வரிசை: பெறப்பட்டது(த,ஆ), பிரிக்கப்பட்டது(த,ஆ), மீதம்(த,ஆ),
                    #        அனுப்பப்பட்டது(த,ஆ), அனுப்ப வேண்டியது(த,ஆ)
                    pending, pending_tm = total - assigned, total_tm - assigned_tm
                    ps, ps_tm = assigned - sent, assigned_tm - sent_tm
                    return (
                        total_tm, total - total_tm,
                        assigned_tm, assigned - assigned_tm,
                        pending_tm, pending - pending_tm,
                        sent_tm, sent - sent_tm,
                        ps_tm, ps - ps_tm,
                    )

                t1_rows, g1 = [], [0] * 10
                for sno, lt in enumerate(lt_order, 1):
                    sub = [r for r in lib_rows if r["lt"] == lt]
                    vals = _split10(
                        sum(r["total"] for r in sub), sum(r["total_tm"] for r in sub),
                        sum(r["assigned"] for r in sub), sum(r["assigned_tm"] for r in sub),
                        sum(r["sent"] for r in sub), sum(r["sent_tm"] for r in sub),
                    )
                    t1_rows.append((sno, lt) + vals)
                    for k in range(10):
                        g1[k] += vals[k]
                t1_html = "".join(
                    f"<tr><td>{r[0]}</td><td style='text-align:left'>{r[1]}</td>"
                    + "".join(f"<td>{v}</td>" for v in r[2:]) + "</tr>" for r in t1_rows
                )
                t1_html += (
                    "<tr style='background:#d0e8ff;font-weight:800;'><td></td>"
                    "<td style='text-align:left'>மொத்தம்</td>" + "".join(f"<td>{v}</td>" for v in g1) + "</tr>"
                )

                t2_html, sno2, g2 = "", 0, [0] * 10
                for lt in lt_order:
                    t2_html += (f"<tr style='background:#0d5c63;color:#fff;font-weight:800;'>"
                                f"<td colspan='12' style='text-align:left'>▌ {lt}</td></tr>")
                    sub = sorted([r for r in lib_rows if r["lt"] == lt], key=lambda r: r["ln"])
                    for r in sub:
                        sno2 += 1
                        vals = _split10(r["total"], r["total_tm"], r["assigned"], r["assigned_tm"], r["sent"], r["sent_tm"])
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
<th colspan='2'>பெறப்பட்டது</th><th colspan='2'>பிரிக்கப்பட்டது</th><th colspan='2'>மீதம்</th>
<th colspan='2'>அனுப்பப்பட்டது</th><th colspan='2'>அனுப்ப வேண்டியது</th></tr>
<tr><th>தமிழ்</th><th>ஆங்கிலம்</th><th>தமிழ்</th><th>ஆங்கிலம்</th><th>தமிழ்</th><th>ஆங்கிலம்</th>
<th>தமிழ்</th><th>ஆங்கிலம்</th><th>தமிழ்</th><th>ஆங்கிலம்</th></tr>"""

                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 3 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}
@page{{size:A4 portrait;margin:10mm 8mm 10mm 8mm;}}
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
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(vendor_name),''), 'தெரியாத பதிப்பகம்') AS vendor,
                           COUNT(DISTINCT TRIM(title)) AS title_count,
                           COUNT(DISTINCT TRIM(title)) FILTER (WHERE {_TAMIL_TITLE_SQL}) AS title_count_tm,
                           COUNT(*) AS copy_count,
                           COUNT(*) FILTER (WHERE {_TAMIL_TITLE_SQL}) AS copy_count_tm
                    FROM books WHERE (set_number IS NULL OR set_number = '') AND academic_year = %s
                    GROUP BY vendor ORDER BY vendor
                """, (year,))
                rows = cur.fetchall()
                if not rows:
                    return jsonify({"error": "பிரிக்கப்படாத புத்தகங்கள் எதுவும் இல்லை"})
                rows_html, tt_tm, tt_en, tc_tm, tc_en = "", 0, 0, 0, 0
                for i, r in enumerate(rows, 1):
                    title_tm = r["title_count_tm"]
                    title_en = r["title_count"] - title_tm
                    copy_tm = r["copy_count_tm"]
                    copy_en = r["copy_count"] - copy_tm
                    rows_html += (f"<tr><td>{i}</td><td style='text-align:left'>{r['vendor']}</td>"
                                  f"<td>{title_tm}</td><td>{title_en}</td>"
                                  f"<td>{copy_tm}</td><td>{copy_en}</td></tr>")
                    tt_tm += title_tm
                    tt_en += title_en
                    tc_tm += copy_tm
                    tc_en += copy_en
                rows_html += (f"<tr style='background:#d0e8ff;font-weight:800;'><td></td>"
                              f"<td style='text-align:left'>மொத்தம்</td>"
                              f"<td>{tt_tm}</td><td>{tt_en}</td><td>{tc_tm}</td><td>{tc_en}</td></tr>")
                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 4 - {today_str}</title>
<style>{REPORT_COMMON_HEAD}</style></head><body>
<div class="rt"><p class="t1">மாவட்ட மைய நூலகம், {DISTRICT_NAME}</p>
<p class="t3">2026-2027 ல் இதுவரை பிரிக்கப்படாத பதிப்பகங்கள் மற்றும் நூல்கள் விவரம்</p>
<p class="t5">அறிக்கை நாள் : {today_str}</p></div>
<table><thead><tr><th rowspan='2'>வ.எண்</th><th rowspan='2'>பதிப்பகம் பெயர்</th>
<th colspan='2'>மொத்த தலைப்புகள்</th><th colspan='2'>மொத்தப் படிகள்</th></tr>
<tr><th>தமிழ்</th><th>ஆங்கிலம்</th><th>தமிழ்</th><th>ஆங்கிலம்</th></tr></thead>
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
                    return jsonify({"error": "அனுப்பப்பட்ட புத்தகங்களில் ஒரே தலைப்பில் வேறு வேறு விலைகள் எதுவும் இல்லை"})

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

            else:
                return jsonify({"error": "இந்த அறிக்கை இன்னும் தயார் இல்லை (அடுத்த கட்டத்தில் வரும்)"}), 400

        report_id = _save_report(html, f"அறிக்கை {num} - {today_str}")
        return jsonify({
            "success": True,
            "message": f"அறிக்கை {num} புதிய tab-ல் திறக்கப்படும்.\nPDF-ஆக சேமிக்க: Ctrl+P → Save as PDF",
            "url": f"/reports/view/{report_id}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@app.route("/api/report5", methods=["POST"])
@login_required
def api_report5():
    body = request.json or {}
    lib_name = body.get("lib_name", "")
    year = body.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    today_str = datetime.now().strftime("%d/%m/%Y")
    try:
        with DBConn() as (conn, cur):
            cur.execute(
                "SELECT * FROM books WHERE TRIM(library_name_tm) = %s "
                "AND central_number IS NOT NULL AND academic_year = %s ORDER BY branch_number",
                (lib_name, year)
            )
            rows = cur.fetchall()
        if not rows:
            return jsonify({"error": f'"{lib_name}" நூலகத்திற்கு பிரிக்கப்பட்ட புத்தகங்கள் இல்லை'})

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

        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>அறிக்கை 5 - {lib_name}</title>
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
        report_id = _save_report(html, f"அறிக்கை 5 - {lib_name}")
        return jsonify({
            "success": True,
            "message": f'"{lib_name}" அறிக்கை புதிய tab-ல் திறக்கப்படும்.\nPDF-ஆக சேமிக்க: Ctrl+P → Save as PDF',
            "url": f"/reports/view/{report_id}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@app.route("/api/report7", methods=["POST"])
@login_required
def api_report7():
    body = request.json or {}
    selected = body.get("selected", [])
    year = body.get("year") or _get_setting("active_academic_year", BASE_YEAR)
    if not selected:
        return jsonify({"error": "எந்த பகுதியும் தேர்வு செய்யப்படவில்லை"}), 400
    today_str = datetime.now().strftime("%d/%m/%Y")
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
                s, e, idx = sel["start"], sel["end"], sel["idx"]
                cur.execute(
                    "SELECT * FROM books WHERE central_number BETWEEN %s AND %s AND academic_year = %s "
                    "ORDER BY central_number",
                    (s, e, year)
                )
                chunk_rows = cur.fetchall()
                if not chunk_rows:
                    continue
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


# ==========================================================
# SEARCH
# ==========================================================
@app.route("/api/search")
@login_required
def api_search():
    text = request.args.get('q', '').strip()
    year = request.args.get('year') or BASE_YEAR
    if len(text) < 2:
        return jsonify([])
    with DBConn() as (conn, cur):
        cur.execute(
            "SELECT title, price, vendor_name, COUNT(*) AS count "
            "FROM books WHERE title ILIKE %s AND academic_year = %s "
            "GROUP BY title, price, vendor_name LIMIT 100",
            (f"%{text}%", year)
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

    out = []
    for r in rows:
        out.append({
            "title": (r["title"] or "")[:80],
            "vendor": r["vendor_name"] or "",
            "price": r["price"] or "",
            "count": r["count"],
            "isMultiPrice": _norm_title(r["title"]) in multi_price_norm_titles,
            "isFuzzyDup": False,   # fuzzy cache — அடுத்த கட்டத்தில் சேர்க்கப்படும்
        })
    return jsonify(out)


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
            f"WHERE NORMALIZE(TRIM(library_name_tm), NFC) = NORMALIZE(%s, NFC) "
            f"AND {_SENT_SQL} AND NORMALIZE(title, NFC) ILIKE NORMALIZE(%s, NFC) "
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
        "title": (r["title"] or "")[:80],
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
