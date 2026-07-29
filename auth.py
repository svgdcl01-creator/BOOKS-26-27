# -*- coding: utf-8 -*-
"""
Login system — Flask session-based.
3 accounts: 1 admin (நீங்கள்) + 2 staff.
Admin: assign + renumber + settings + backup/restore + reports
Staff: assign + search மட்டும்
"""
from functools import wraps
from flask import session, redirect, request, jsonify
from werkzeug.security import check_password_hash
from db import DBConn


def get_user(username):
    with DBConn() as (conn, cur):
        cur.execute("SELECT username, password_hash, role FROM users WHERE username=%s", (username,))
        return cur.fetchone()


def verify_login(username, password):
    user = get_user(username)
    if not user:
        return None
    if check_password_hash(user["password_hash"], password):
        return user
    return None


def login_required(fn):
    """எந்த login-ஆன userக்கும் அனுமதி (admin அல்லது staff)"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "login தேவை", "code": "AUTH_REQUIRED"}), 401
            return redirect("/login")
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    """Renumber / Settings / Backup-Restore — Admin மட்டும்"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "login தேவை", "code": "AUTH_REQUIRED"}), 401
            return redirect("/login")
        if session.get("role") != "admin":
            return jsonify({"error": "இது Admin-க்கு மட்டும் அனுமதிக்கப்பட்ட வேலை"}), 403
        return fn(*args, **kwargs)
    return wrapper


def staff_or_admin_required(fn):
    """Assign / Send / Reclaim போன்ற data-மாற்றும் வேலைகள் — Admin/DCL Staff
    மட்டும் (Librarian role-க்கு read-only அணுகல் மட்டும்)"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "login தேவை", "code": "AUTH_REQUIRED"}), 401
            return redirect("/login")
        if session.get("role") not in ("admin", "staff"):
            return jsonify({"error": "இது Admin/Staff-க்கு மட்டும் அனுமதிக்கப்பட்ட வேலை"}), 403
        return fn(*args, **kwargs)
    return wrapper
