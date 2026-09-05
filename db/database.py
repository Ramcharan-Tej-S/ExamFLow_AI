# db/database.py — ExamFlow AI Database Helpers
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, SCHEMA_PATH


def get_connection():
    """Return a new SQLite connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables from schema.sql if they don't exist."""
    conn = get_connection()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    # Ensure is_completed column exists in exam_schedule for existing databases
    try:
        conn.execute("ALTER TABLE exam_schedule ADD COLUMN is_completed INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


# ─── Stats ────────────────────────────────────────────────────────────
def get_stats():
    conn = get_connection()
    stats = {
        "subjects": conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0],
        "topics": conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0],
        "exams": conn.execute("SELECT COUNT(*) FROM exam_schedule").fetchone()[0],
        "sessions": conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0],
        "scores": conn.execute("SELECT COUNT(*) FROM test_scores").fetchone()[0],
    }
    conn.close()
    return stats


# ─── Subjects CRUD ───────────────────────────────────────────────────
def add_subject(name, code="", credits=3, semester=1, self_rating=5.0):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO subjects (name, code, credits, semester, self_rating) VALUES (?, ?, ?, ?, ?)",
        (name, code, credits, semester, self_rating),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def get_all_subjects():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_subject(subject_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_subject(subject_id):
    conn = get_connection()
    # 1. Delete deepest children first: difficulty_scores (references topics)
    conn.execute("DELETE FROM difficulty_scores WHERE topic_id IN (SELECT id FROM topics WHERE subject_id = ?)", (subject_id,))
    # 2. Delete study_sessions (references both topics and subjects)
    conn.execute("DELETE FROM study_sessions WHERE subject_id = ?", (subject_id,))
    # 3. Now safe to delete topics (no more FK references to topics)
    conn.execute("DELETE FROM topics WHERE subject_id = ?", (subject_id,))
    # 4. Delete remaining tables that reference subjects
    conn.execute("DELETE FROM exam_schedule WHERE subject_id = ?", (subject_id,))
    conn.execute("DELETE FROM test_scores WHERE subject_id = ?", (subject_id,))
    conn.execute("DELETE FROM performance_log WHERE subject_id = ?", (subject_id,))
    conn.execute("DELETE FROM uploaded_files WHERE subject_id = ?", (subject_id,))
    # 5. Finally delete the subject itself
    conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
    conn.commit()
    conn.close()


# ─── Topics CRUD ─────────────────────────────────────────────────────
def add_topic(subject_id, topic_name, unit_name="", description="", estimated_hours=2.0):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO topics (subject_id, topic_name, unit_name, description, estimated_hours) VALUES (?, ?, ?, ?, ?)",
        (subject_id, topic_name, unit_name, description, estimated_hours),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def get_topics_by_subject(subject_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM topics WHERE subject_id = ? ORDER BY unit_name, topic_name", (subject_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_topics():
    conn = get_connection()
    rows = conn.execute(
        "SELECT t.*, s.name as subject_name FROM topics t JOIN subjects s ON t.subject_id = s.id ORDER BY s.name, t.unit_name, t.topic_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Difficulty Scores ───────────────────────────────────────────────
def add_difficulty_score(topic_id, level="medium", score=5.0, confidence=0.5, reasoning=""):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO difficulty_scores (topic_id, level, score, confidence, reasoning) VALUES (?, ?, ?, ?, ?)",
        (topic_id, level, score, confidence, reasoning),
    )
    conn.commit()
    did = cur.lastrowid
    conn.close()
    return did


def get_difficulty_by_topic(topic_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM difficulty_scores WHERE topic_id = ? ORDER BY assessed_at DESC LIMIT 1",
        (topic_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_difficulties():
    """Latest difficulty score per topic.

    difficulty_scores keeps every assessment as history, so re-running the
    judge would otherwise return the same topic several times and inflate
    the easy/medium/hard counts past the number of topics.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT d.*, t.topic_name, t.unit_name, s.name as subject_name
        FROM difficulty_scores d
        JOIN topics t ON d.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        WHERE d.id IN (SELECT MAX(id) FROM difficulty_scores GROUP BY topic_id)
        ORDER BY s.name, t.unit_name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Exam Schedule ───────────────────────────────────────────────────
def add_exam(subject_id, exam_date, exam_time="09:00", duration_min=180, exam_type="final", is_completed=0):
    """Add or update exam schedule for a subject."""
    conn = get_connection()
    existing = conn.execute("SELECT id FROM exam_schedule WHERE subject_id = ?", (subject_id,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE exam_schedule 
               SET exam_date = ?, exam_time = ?, duration_min = ?, exam_type = ?, is_completed = ? 
               WHERE subject_id = ?""",
            (exam_date, exam_time, duration_min, exam_type, is_completed, subject_id),
        )
        eid = existing["id"]
    else:
        cur = conn.execute(
            """INSERT INTO exam_schedule (subject_id, exam_date, exam_time, duration_min, exam_type, is_completed) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (subject_id, exam_date, exam_time, duration_min, exam_type, is_completed),
        )
        eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def mark_exam_completed(exam_id):
    """Mark an exam as completed."""
    conn = get_connection()
    conn.execute("UPDATE exam_schedule SET is_completed = 1 WHERE id = ?", (exam_id,))
    conn.commit()
    conn.close()


def delete_exam(exam_id):
    """Delete an exam by id."""
    conn = get_connection()
    conn.execute("DELETE FROM exam_schedule WHERE id = ?", (exam_id,))
    conn.commit()
    conn.close()


def delete_past_exams(before_date=None):
    """Delete exams that are completed or whose dates are in the past."""
    from datetime import date
    if before_date is None:
        before_date = date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    conn.execute("DELETE FROM exam_schedule WHERE exam_date < ? OR is_completed = 1", (before_date,))
    conn.commit()
    conn.close()


def get_all_exams():
    """Get all exams in the database."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT e.*, s.name as subject_name
        FROM exam_schedule e
        JOIN subjects s ON e.subject_id = s.id
        ORDER BY e.exam_date
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_upcoming_exams(today_str=None):
    """Get only upcoming exams (date >= today and not completed)."""
    from datetime import date
    if today_str is None:
        today_str = date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT e.*, s.name as subject_name
            FROM exam_schedule e
            JOIN subjects s ON e.subject_id = s.id
            WHERE e.exam_date >= ? AND COALESCE(e.is_completed, 0) = 0
            ORDER BY e.exam_date
        """, (today_str,)).fetchall()
    except Exception:
        rows = conn.execute("""
            SELECT e.*, s.name as subject_name
            FROM exam_schedule e
            JOIN subjects s ON e.subject_id = s.id
            WHERE e.exam_date >= ?
            ORDER BY e.exam_date
        """, (today_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_exams_by_subject(subject_id):
    """Get exam for a given subject."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM exam_schedule WHERE subject_id = ? ORDER BY exam_date DESC", (subject_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Availability ────────────────────────────────────────────────────
def add_availability(day_of_week, start_time, end_time, is_peak=0, energy_level="medium"):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO availability (day_of_week, start_time, end_time, is_peak, energy_level) VALUES (?, ?, ?, ?, ?)",
        (day_of_week, start_time, end_time, is_peak, energy_level),
    )
    conn.commit()
    aid = cur.lastrowid
    conn.close()
    return aid


def get_all_availability():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM availability ORDER BY day_of_week, start_time").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_availability():
    conn = get_connection()
    conn.execute("DELETE FROM availability")
    conn.commit()
    conn.close()


# ─── Test Scores ─────────────────────────────────────────────────────
def add_test_score(subject_id, score, max_score=100.0, test_type="cie", test_date=None, notes=""):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO test_scores (subject_id, test_type, score, max_score, test_date, notes) VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_DATE), ?)",
        (subject_id, test_type, score, max_score, test_date, notes),
    )
    conn.commit()
    tsid = cur.lastrowid
    conn.close()
    return tsid


def get_scores_by_subject(subject_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM test_scores WHERE subject_id = ? ORDER BY test_date DESC", (subject_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_scores():
    conn = get_connection()
    rows = conn.execute("""
        SELECT ts.*, s.name as subject_name
        FROM test_scores ts
        JOIN subjects s ON ts.subject_id = s.id
        ORDER BY ts.test_date DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Study Sessions ─────────────────────────────────────────────────
def add_study_session(subject_id, topic_id, session_date, start_time, duration_min=60, priority="medium", status="planned"):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO study_sessions (subject_id, topic_id, session_date, start_time, duration_min, priority, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (subject_id, topic_id, session_date, start_time, duration_min, priority, status),
    )
    conn.commit()
    ssid = cur.lastrowid
    conn.close()
    return ssid


def get_all_sessions():
    conn = get_connection()
    rows = conn.execute("""
        SELECT ss.*, s.name as subject_name, t.topic_name
        FROM study_sessions ss
        JOIN subjects s ON ss.subject_id = s.id
        LEFT JOIN topics t ON ss.topic_id = t.id
        ORDER BY ss.session_date, ss.start_time
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sessions_by_date(session_date):
    conn = get_connection()
    rows = conn.execute("""
        SELECT ss.*, s.name as subject_name, t.topic_name
        FROM study_sessions ss
        JOIN subjects s ON ss.subject_id = s.id
        LEFT JOIN topics t ON ss.topic_id = t.id
        WHERE ss.session_date = ?
        ORDER BY ss.start_time
    """, (session_date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_session_status(session_id, status):
    conn = get_connection()
    conn.execute("UPDATE study_sessions SET status = ? WHERE id = ?", (status, session_id))
    conn.commit()
    conn.close()


def clear_sessions():
    conn = get_connection()
    conn.execute("DELETE FROM study_sessions")
    conn.commit()
    conn.close()


# ─── Performance Log ────────────────────────────────────────────────
def add_performance_log(subject_id, readiness_score, predicted_score=0.0, coverage_pct=0.0, reasoning=""):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO performance_log (subject_id, readiness_score, predicted_score, coverage_pct, reasoning) VALUES (?, ?, ?, ?, ?)",
        (subject_id, readiness_score, predicted_score, coverage_pct, reasoning),
    )
    conn.commit()
    plid = cur.lastrowid
    conn.close()
    return plid


def get_performance_history(subject_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM performance_log WHERE subject_id = ? ORDER BY logged_at", (subject_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_performance():
    conn = get_connection()
    rows = conn.execute("""
        SELECT pl.*, s.name as subject_name
        FROM performance_log pl
        JOIN subjects s ON pl.subject_id = s.id
        WHERE pl.id IN (
            SELECT MAX(id) FROM performance_log GROUP BY subject_id
        )
        ORDER BY s.name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Uploaded Files ──────────────────────────────────────────────────
def add_uploaded_file(filename, file_path, file_type="syllabus", subject_id=None):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO uploaded_files (filename, file_path, file_type, subject_id) VALUES (?, ?, ?, ?)",
        (filename, file_path, file_type, subject_id),
    )
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return fid


def mark_file_processed(file_id):
    conn = get_connection()
    conn.execute("UPDATE uploaded_files SET processed = 1 WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()


def get_uploaded_files():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM uploaded_files ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]
