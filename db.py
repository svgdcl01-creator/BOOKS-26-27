# -*- coding: utf-8 -*-
"""
Database connection helper.
DATABASE_URL environment variable-ல் இருந்து Postgres-க்கு connect ஆகும்.
(Neon.tech / Render Postgres இரண்டும் இந்த வடிவிலேயே connection string தரும்)
"""
import os
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable set செய்யவில்லை. "
        ".env கோப்பில் அல்லது Render dashboard-ல் இதை add செய்யவும்."
    )

# sslmode=require பெரும்பாலான cloud Postgres providers-க்கு (Neon, Render) தேவை
_dsn = DATABASE_URL
if "sslmode" not in _dsn:
    _dsn += ("&" if "?" in _dsn else "?") + "sslmode=require"

pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=_dsn)


class DBConn:
    """with DBConn() as (conn, cur): ... — automatic pool return + commit/rollback"""
    def __enter__(self):
        self.conn = pool.getconn()
        self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return self.conn, self.cur

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.cur.close()
            pool.putconn(self.conn)
