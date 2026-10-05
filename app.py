from pathlib import Path
import mimetypes
import re
import sqlite3
import unicodedata
import os
import secrets
import uuid

import bcrypt
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, text
from sqlalchemy.engine import URL
from werkzeug.utils import secure_filename

load_dotenv(Path(__file__).resolve().parent / ".env")

app = Flask(__name__)
app.secret_key = "pls-development-secret-key"
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
CORS(app, supports_credentials=True)

DATABASE_PATH = Path(__file__).resolve().parent / "database" / "personalized_learning.db"
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
database_url = URL.create(drivername="sqlite", database=str(DATABASE_PATH))

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
MATERIALS_DIR = Path(__file__).resolve().parent / "uploads" / "course_materials"


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"success": False, "message": "The upload exceeds the 512 MB file limit."}), 413


def enable_sqlite_foreign_keys(connection, _connection_record):
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


with app.app_context():
    event.listen(db.engine, "connect", enable_sqlite_foreign_keys)

# Apply the schema on startup. CREATE TABLE IF NOT EXISTS keeps existing data intact.
SCHEMA_PATH = Path(__file__).resolve().parent / "database" / "schema.sql"
with sqlite3.connect(DATABASE_PATH) as connection:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    user_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    if "role" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'student'")
    admin_email = os.environ.get("PLS_ADMIN_EMAIL", "").strip().lower()
    if admin_email:
        connection.execute("UPDATE users SET role = 'admin' WHERE lower(email) = ?", (admin_email,))
    course_columns = {row[1] for row in connection.execute("PRAGMA table_info(courses)")}
    if "instructor_id" not in course_columns:
        connection.execute("ALTER TABLE courses ADD COLUMN instructor_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL")
    profile_columns = {row[1] for row in connection.execute("PRAGMA table_info(student_profiles)")}
    for column, declaration in {
        "age": "INTEGER", "course_degree": "VARCHAR(200)", "interests": "TEXT NOT NULL DEFAULT '[]'",
        "preferred_learning_style": "VARCHAR(50)", "preferred_difficulty": "VARCHAR(50)",
        "daily_study_time": "INTEGER", "learning_goal": "TEXT",
    }.items():
        if column not in profile_columns:
            connection.execute(f"ALTER TABLE student_profiles ADD COLUMN {column} {declaration}")
    # SQLite permits storing integers in a VARCHAR column, but rebuild older
    # profile tables so the declared schema also matches the current model.
    profile_columns = {row[1]: row[2].upper() for row in connection.execute("PRAGMA table_info(student_profiles)")}
    if profile_columns.get("daily_study_time") != "INTEGER":
        connection.executescript("""
            CREATE TABLE student_profiles_updated (
                profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                age INTEGER CHECK (age IS NULL OR age BETWEEN 5 AND 120),
                date_of_birth DATE,
                education_level VARCHAR(100),
                course_degree VARCHAR(200),
                interests TEXT NOT NULL DEFAULT '[]',
                preferred_learning_style VARCHAR(50),
                preferred_difficulty VARCHAR(50),
                daily_study_time INTEGER CHECK (daily_study_time IS NULL OR daily_study_time BETWEEN 1 AND 24),
                learning_goal TEXT,
                bio TEXT,
                learning_preferences TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            INSERT INTO student_profiles_updated
              (profile_id, user_id, age, date_of_birth, education_level, course_degree, interests,
               preferred_learning_style, preferred_difficulty, daily_study_time, learning_goal,
               bio, learning_preferences, created_at, updated_at)
            SELECT profile_id, user_id, age, date_of_birth, education_level, course_degree, interests,
                   preferred_learning_style, preferred_difficulty,
                   CASE daily_study_time
                     WHEN 'Under 1 hour/day' THEN 1 WHEN '1–2 hours/day' THEN 2
                     WHEN '2–3 hours/day' THEN 3 WHEN '3+ hours/day' THEN 4
                     ELSE CAST(daily_study_time AS INTEGER) END,
                   learning_goal, bio, learning_preferences, created_at, updated_at
            FROM student_profiles;
            DROP TABLE student_profiles;
            ALTER TABLE student_profiles_updated RENAME TO student_profiles;
        """)

    # Seed starter courses once, while leaving later catalog edits untouched.
    starter_courses = [
        ("Python Programming", "Python fundamentals, variables, functions, and problem solving.", "beginner", "Programming"),
        ("Machine Learning", "Core machine learning ideas, model training, and evaluation.", "intermediate", "Data Science"),
        ("Database Management", "SQL fundamentals, relational data, and database design.", "beginner", "Technology"),
        ("Web Development", "Build websites with HTML, CSS, and JavaScript.", "beginner", "Web Development"),
    ]
    for title, description, difficulty, subject_name in starter_courses:
        connection.execute("INSERT OR IGNORE INTO subjects (name) VALUES (?)", (subject_name,))
        subject_id = connection.execute("SELECT subject_id FROM subjects WHERE name = ? COLLATE NOCASE", (subject_name,)).fetchone()[0]
        if not connection.execute("SELECT 1 FROM courses WHERE title = ? COLLATE NOCASE", (title,)).fetchone():
            connection.execute("""
                INSERT INTO courses (subject_id, title, description, difficulty, is_published)
                VALUES (?, ?, ?, ?, 1)
            """, (subject_id, title, description, difficulty))


@app.route("/")
def home():
    return "Personalized Learning System is running!"


@app.route("/test-db")
def test_db():
    try:
        db.session.execute(text("SELECT 1"))
        return "SQLite connection successful!"
    except Exception as e:
        return f"SQLite connection failed: {e}", 500


@app.route("/api/register", methods=["POST"])
def register():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "Invalid or missing JSON data."
        }), 400

    full_name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    role = str(data.get("role", "student")).strip().lower()

    if not full_name or not email or not password:
        return jsonify({
            "success": False,
            "message": "All fields are required."
        }), 400

    if role not in {"student", "teacher", "admin"}:
        return jsonify({"success": False, "message": "Choose student, teacher, or admin as the account type."}), 400
    if role == "admin":
        configured_invite = os.environ.get("PLS_ADMIN_SIGNUP_CODE", "").strip()
        supplied_invite = str(data.get("admin_code", "")).strip()
        if not configured_invite:
            return jsonify({"success": False, "message": "Admin sign-up is disabled. Ask the system administrator to configure an admin invite code."}), 403
        if not supplied_invite or not secrets.compare_digest(supplied_invite, configured_invite):
            return jsonify({"success": False, "message": "The admin invite code is invalid."}), 403

    if len(full_name) < 2 or len(full_name) > 255:
        return jsonify({
            "success": False,
            "message": "Full name must be between 2 and 255 characters."
        }), 400

    name_separators = set(" .'-’")
    if not any(character.isalpha() for character in full_name) or any(
        not character.isalpha()
        and not unicodedata.category(character).startswith("M")
        and character not in name_separators
        for character in full_name
    ):
        return jsonify({
            "success": False,
            "message": "Use letters, spaces, apostrophes, hyphens, or periods for your name."
        }), 400

    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify({
            "success": False,
            "message": "Please enter a valid email address."
        }), 400

    if len(password) < 8:
        return jsonify({
            "success": False,
            "message": "Password must be at least 8 characters."
        }), 400

    if len(password.encode("utf-8")) > 72:
        return jsonify({
            "success": False,
            "message": "Password must be 72 UTF-8 bytes or fewer."
        }), 400

    try:

        existing_user = db.session.execute(
            text("""
                SELECT user_id
                FROM users
                WHERE email = :email
            """),
            {"email": email}
        ).fetchone()

        if existing_user:
            return jsonify({
                "success": False,
                "message": "An account with this email already exists."
            }), 409

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        db.session.execute(
            text("""
            INSERT INTO users
                (full_name, email, password_hash, role)
                VALUES
                (:full_name, :email, :password_hash, :role)
            """),
            {
                "full_name": full_name,
                "email": email,
                "password_hash": password_hash,
                "role": role
            }
        )

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Account created successfully."
        }), 201

    except Exception as e:

        db.session.rollback()

        print("Registration error:", e)

        return jsonify({
            "success": False,
            "message": "Could not create the account."
        }), 500


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "Invalid or missing JSON data."
        }), 400

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not email or not password:
        return jsonify({
            "success": False,
            "message": "Email and password are required."
        }), 400

    user = db.session.execute(
        text("""
            SELECT user_id, full_name, email, password_hash, role
            FROM users
            WHERE email = :email
        """),
        {"email": email}
    ).fetchone()

    if not user or not bcrypt.checkpw(
        password.encode("utf-8"),
        user.password_hash.encode("utf-8")
    ):
        return jsonify({
            "success": False,
            "message": "That email and password combination was not found."
        }), 401

    # Remember the logged-in student
    session["user_id"] = user.user_id
    session["full_name"] = user.full_name
    session["email"] = user.email
    session["role"] = user.role
    has_profile = db.session.execute(
        text("SELECT 1 FROM student_profiles WHERE user_id = :user_id"),
        {"user_id": user.user_id}
    ).fetchone() is not None

    return jsonify({
        "success": True,
        "message": f"Welcome back, {user.full_name}!",
        "user": {
            "user_id": user.user_id,
            "full_name": user.full_name,
            "email": user.email
        },
        "role": user.role,
        "profile_completed": has_profile
    }), 200

@app.route("/api/dashboard", methods=["GET"])
def dashboard():

    if "user_id" not in session:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    account = db.session.execute(
        text("SELECT full_name, email, role FROM users WHERE user_id = :user_id"),
        {"user_id": session["user_id"]}
    ).fetchone()
    if not account:
        session.clear()
        return jsonify({"success": False, "message": "Account not found."}), 401
    # Keep the browser session in sync when an admin role is configured or changed.
    session["full_name"] = account.full_name
    session["email"] = account.email
    session["role"] = account.role

    summary = db.session.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM enrollments
             WHERE user_id = :user_id AND status = 'active') AS active_courses,
            (SELECT COALESCE(SUM(time_spent_seconds), 0) FROM student_progress
             WHERE user_id = :user_id) AS study_seconds,
            (SELECT COUNT(*) FROM student_progress
             WHERE user_id = :user_id AND status = 'completed') AS completed_lessons
    """), {"user_id": session["user_id"]}).mappings().one()

    return jsonify({
        "success": True,
        "role": session.get("role", "student"),
        "summary": dict(summary),
        "user": {
            "user_id": session["user_id"],
            "full_name": session["full_name"],
            "email": session["email"]
        }
    }), 200


@app.route("/api/student-profile", methods=["GET", "PUT"])
def student_profile():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401

    user_id = session["user_id"]
    if request.method == "GET":
        row = db.session.execute(text("""
            SELECT u.full_name, p.age, p.education_level, p.course_degree, p.interests,
                   p.preferred_learning_style, p.preferred_difficulty, p.daily_study_time, p.learning_goal
            FROM users u LEFT JOIN student_profiles p ON p.user_id = u.user_id
            WHERE u.user_id = :user_id
        """), {"user_id": user_id}).fetchone()
        if not row:
            return jsonify({"success": False, "message": "Student account not found."}), 404
        import json
        profile = dict(row._mapping)
        try:
            profile["interests"] = json.loads(profile["interests"] or "[]")
        except (TypeError, ValueError):
            profile["interests"] = []
        # Convert values saved by the earlier label-based form (e.g. "1–2 hours/day")
        # into the integer-hour value expected by the current profile form.
        if isinstance(profile["daily_study_time"], str):
            legacy_hours = {"Under 1 hour/day": 1, "1–2 hours/day": 2, "2–3 hours/day": 3, "3+ hours/day": 4}
            profile["daily_study_time"] = legacy_hours.get(profile["daily_study_time"])
        profile["completed"] = bool(profile["education_level"] and profile["preferred_difficulty"] and profile["learning_goal"])
        return jsonify({"success": True, "profile": profile}), 200

    data = request.get_json(silent=True) or {}
    full_name = str(data.get("full_name", "")).strip()
    education_level = str(data.get("education_level", "")).strip()
    course_degree = str(data.get("course_degree", "")).strip()
    learning_style = str(data.get("preferred_learning_style", "")).strip()
    difficulty = str(data.get("preferred_difficulty", "")).strip().lower()
    try:
        study_time = int(data.get("daily_study_time")) if str(data.get("daily_study_time", "")).strip() else None
    except (TypeError, ValueError):
        study_time = None
    learning_goal = str(data.get("learning_goal", "")).strip()
    try:
        age = int(data.get("age")) if str(data.get("age", "")).strip() else None
    except (TypeError, ValueError):
        age = -1
    interests = data.get("interests", [])
    if not isinstance(interests, list) or any(not isinstance(item, str) for item in interests):
        return jsonify({"success": False, "message": "Choose valid areas of interest."}), 400
    if not full_name or not education_level or not learning_style or difficulty not in {"beginner", "intermediate", "advanced"} or study_time is None or not learning_goal:
        return jsonify({"success": False, "message": "Complete all required profile fields."}), 400
    if age is not None and not 5 <= age <= 120:
        return jsonify({"success": False, "message": "Age must be between 5 and 120."}), 400
    if not 1 <= study_time <= 24:
        return jsonify({"success": False, "message": "Daily study time must be between 1 and 24 hours."}), 400
    if any(len(value) > limit for value, limit in [(full_name, 255), (education_level, 100), (course_degree, 200), (learning_style, 50), (learning_goal, 2000)]) or len(interests) > 20:
        return jsonify({"success": False, "message": "One or more profile fields are too long."}), 400

    import json
    db.session.execute(text("UPDATE users SET full_name = :name WHERE user_id = :user_id"), {"name": full_name, "user_id": user_id})
    db.session.execute(text("""
        INSERT INTO student_profiles (user_id, age, education_level, course_degree, interests,
          preferred_learning_style, preferred_difficulty, daily_study_time, learning_goal, updated_at)
        VALUES (:user_id, :age, :education, :course, :interests, :style, :difficulty, :study_time, :goal, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET age=excluded.age, education_level=excluded.education_level,
          course_degree=excluded.course_degree, interests=excluded.interests,
          preferred_learning_style=excluded.preferred_learning_style, preferred_difficulty=excluded.preferred_difficulty,
          daily_study_time=excluded.daily_study_time, learning_goal=excluded.learning_goal, updated_at=CURRENT_TIMESTAMP
    """), {"user_id": user_id, "age": age, "education": education_level, "course": course_degree,
           "interests": json.dumps(interests), "style": learning_style, "difficulty": difficulty,
           "study_time": study_time, "goal": learning_goal})
    db.session.commit()
    session["full_name"] = full_name
    return jsonify({"success": True, "message": "Your student profile has been saved."}), 200


@app.route("/api/courses", methods=["GET"])
def list_courses():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    rows = db.session.execute(text("""
        SELECT c.course_id, c.title, c.description, c.difficulty, s.name AS subject,
               e.status AS enrollment_status
        FROM courses c
        LEFT JOIN subjects s ON s.subject_id = c.subject_id
        LEFT JOIN enrollments e ON e.course_id = c.course_id AND e.user_id = :user_id
        WHERE c.is_published = 1 OR e.status IN ('active','completed')
        ORDER BY c.title
    """), {"user_id": session["user_id"]}).fetchall()
    courses = [dict(row._mapping) for row in rows]
    materials = db.session.execute(text("""
        SELECT cm.material_id, cm.course_id, cm.title, cm.material_type,
          cm.original_filename, cm.mimetype, cm.file_size, cm.created_at
        FROM course_materials cm
        JOIN enrollments e ON e.course_id=cm.course_id
        WHERE e.user_id=:user_id AND e.status IN ('active','completed')
        ORDER BY cm.created_at DESC
    """), {"user_id": session["user_id"]}).fetchall()
    materials_by_course = {}
    for row in materials:
        material = dict(row._mapping)
        material["download_url"] = f"/api/materials/{material['material_id']}/download"
        materials_by_course.setdefault(material.pop("course_id"), []).append(material)
    for course in courses:
        course["materials"] = materials_by_course.get(course["course_id"], [])
    quiz_rows = db.session.execute(text("""
        SELECT q.quiz_id, q.course_id, q.title, q.description, q.passing_score
        FROM quizzes q
        JOIN enrollments e ON e.course_id=q.course_id
        WHERE e.user_id=:user_id AND e.status IN ('active','completed')
        ORDER BY q.course_id, q.title
    """), {"user_id": session["user_id"]}).fetchall()
    quizzes_by_course = {}
    quizzes_by_id = {}
    for row in quiz_rows:
        quiz = dict(row._mapping)
        quiz["attempts"] = []
        quizzes_by_course.setdefault(quiz["course_id"], []).append(quiz)
        quizzes_by_id[quiz["quiz_id"]] = quiz
    attempt_rows = db.session.execute(text("""
        SELECT qa.quiz_id, qa.attempt_number, qa.status, qa.score, qa.started_at, qa.completed_at
        FROM quiz_attempts qa
        JOIN quizzes q ON q.quiz_id=qa.quiz_id
        JOIN enrollments e ON e.course_id=q.course_id
        WHERE qa.user_id=:user_id AND e.user_id=:user_id AND e.status IN ('active','completed')
        ORDER BY qa.started_at DESC
    """), {"user_id": session["user_id"]}).fetchall()
    for row in attempt_rows:
        attempt = dict(row._mapping)
        quiz = quizzes_by_id.get(attempt.pop("quiz_id"))
        if quiz is not None:
            quiz["attempts"].append(attempt)
    for course in courses:
        course["quizzes"] = quizzes_by_course.get(course["course_id"], [])
    return jsonify({"success": True, "courses": courses}), 200


@app.route("/api/enrollments", methods=["POST"])
def enroll_in_course():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    data = request.get_json(silent=True) or {}
    try:
        course_id = int(data.get("course_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Choose a valid course."}), 400
    course = db.session.execute(text("SELECT course_id FROM courses WHERE course_id = :id AND is_published = 1"), {"id": course_id}).fetchone()
    if not course:
        return jsonify({"success": False, "message": "That course is not available."}), 404
    db.session.execute(text("""
        INSERT INTO enrollments (user_id, course_id, status) VALUES (:user_id, :course_id, 'active')
        ON CONFLICT(user_id, course_id) DO UPDATE SET status='active', enrolled_at=CURRENT_TIMESTAMP, completed_at=NULL
    """), {"user_id": session["user_id"], "course_id": course_id})
    db.session.commit()
    return jsonify({"success": True, "message": "You are enrolled in this course."}), 201

@app.route("/api/teacher/dashboard", methods=["GET"])
def teacher_dashboard_data():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    if session.get("role") != "teacher":
        return jsonify({"success": False, "message": "Teacher access required."}), 403

    teacher_id = session["user_id"]
    courses = [dict(row._mapping) for row in db.session.execute(text("""
        SELECT c.course_id, c.title, c.difficulty, c.is_published,
          s.name AS subject, COUNT(DISTINCT e.user_id) AS student_count,
          (SELECT COUNT(*) FROM quizzes q WHERE q.course_id=c.course_id) AS quiz_count
        FROM courses c
        LEFT JOIN subjects s ON s.subject_id=c.subject_id
        LEFT JOIN enrollments e ON e.course_id=c.course_id AND e.status='active'
        WHERE c.instructor_id=:teacher_id
        GROUP BY c.course_id
        ORDER BY c.title
    """), {"teacher_id": teacher_id}).fetchall()]

    learner_rows = db.session.execute(text("""
        SELECT c.course_id, c.title AS course_title, u.user_id, u.full_name, u.email,
          e.status AS enrollment_status, e.enrolled_at,
          (SELECT COUNT(*) FROM lessons l
            JOIN student_progress p ON p.lesson_id=l.lesson_id
            WHERE l.course_id=c.course_id AND p.user_id=u.user_id AND p.status='completed') AS completed_lessons,
          (SELECT COUNT(*) FROM lessons l WHERE l.course_id=c.course_id) AS total_lessons,
          (SELECT COALESCE(ROUND(AVG(p.completion_percent), 1), 0)
            FROM lessons l LEFT JOIN student_progress p
              ON p.lesson_id=l.lesson_id AND p.user_id=u.user_id
            WHERE l.course_id=c.course_id) AS lesson_completion,
          (SELECT COUNT(*) FROM quiz_attempts qa JOIN quizzes q ON q.quiz_id=qa.quiz_id
            WHERE q.course_id=c.course_id AND qa.user_id=u.user_id
              AND qa.status IN ('submitted','graded')) AS quizzes_taken,
          (SELECT COUNT(*) FROM quiz_attempts qa JOIN quizzes q ON q.quiz_id=qa.quiz_id
            WHERE q.course_id=c.course_id AND qa.user_id=u.user_id AND qa.status='graded'
              AND qa.score IS NOT NULL) AS graded_quizzes,
          (SELECT COALESCE(ROUND(AVG(qa.score), 1), 0) FROM quiz_attempts qa
            JOIN quizzes q ON q.quiz_id=qa.quiz_id
            WHERE q.course_id=c.course_id AND qa.user_id=u.user_id
              AND qa.status='graded' AND qa.score IS NOT NULL) AS average_quiz_score
        FROM courses c
        JOIN enrollments e ON e.course_id=c.course_id
        JOIN users u ON u.user_id=e.user_id AND u.role='student'
        WHERE c.instructor_id=:teacher_id
        ORDER BY c.title, u.full_name
    """), {"teacher_id": teacher_id}).fetchall()
    learners = [dict(row._mapping) for row in learner_rows]

    attempt_rows = db.session.execute(text("""
        SELECT c.course_id, qa.user_id, q.title AS quiz_title, qa.attempt_number,
          qa.status, qa.score, qa.started_at, qa.completed_at
        FROM courses c
        JOIN quizzes q ON q.course_id=c.course_id
        JOIN quiz_attempts qa ON qa.quiz_id=q.quiz_id
        JOIN users u ON u.user_id=qa.user_id AND u.role='student'
        JOIN enrollments e ON e.user_id=u.user_id AND e.course_id=c.course_id
        WHERE c.instructor_id=:teacher_id
        ORDER BY c.title, u.full_name, q.title, qa.attempt_number
    """), {"teacher_id": teacher_id}).fetchall()
    attempts_by_learner = {}
    for row in attempt_rows:
        attempt = dict(row._mapping)
        key = (attempt.pop("course_id"), attempt.pop("user_id"))
        attempts_by_learner.setdefault(key, []).append(attempt)
    for learner in learners:
        learner["quiz_attempts"] = attempts_by_learner.get((learner["course_id"], learner["user_id"]), [])

    return jsonify({
        "success": True,
        "teacher": {"full_name": session.get("full_name"), "email": session.get("email")},
        "courses": courses,
        "learners": learners
    }), 200


@app.route("/api/teacher/materials", methods=["GET", "POST"])
def teacher_materials():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    if session.get("role") != "teacher":
        return jsonify({"success": False, "message": "Teacher access required."}), 403

    teacher_id = session["user_id"]
    if request.method == "GET":
        rows = db.session.execute(text("""
            SELECT cm.material_id, cm.course_id, c.title AS course_title, cm.title,
              cm.material_type, cm.original_filename, cm.mimetype, cm.file_size, cm.created_at
            FROM course_materials cm
            JOIN courses c ON c.course_id=cm.course_id
            WHERE c.instructor_id=:teacher_id
            ORDER BY cm.created_at DESC
        """), {"teacher_id": teacher_id}).fetchall()
        materials = [dict(row._mapping) for row in rows]
        for material in materials:
            material["download_url"] = f"/api/materials/{material['material_id']}/download"
        return jsonify({"success": True, "materials": materials}), 200

    try:
        course_id = int(request.form.get("course_id", ""))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Choose one of your courses."}), 400
    course = db.session.execute(text("""
        SELECT course_id FROM courses WHERE course_id=:course_id AND instructor_id=:teacher_id
    """), {"course_id": course_id, "teacher_id": teacher_id}).first()
    if not course:
        return jsonify({"success": False, "message": "You can upload materials only to courses assigned to you."}), 403

    material_type = str(request.form.get("material_type", "")).strip().lower()
    if material_type not in {"video", "notes"}:
        return jsonify({"success": False, "message": "Choose video or notes as the material type."}), 400
    uploaded_file = request.files.get("file")
    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({"success": False, "message": "Choose a file to upload."}), 400

    original_filename = uploaded_file.filename.replace("\\", "/").split("/")[-1].strip()
    safe_original = secure_filename(original_filename)
    extension = Path(safe_original).suffix.lower()
    allowed_extensions = {
        "video": {".mp4", ".webm", ".mov", ".m4v"},
        "notes": {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".md"}
    }
    if not safe_original or extension not in allowed_extensions[material_type]:
        allowed = "MP4, WebM, MOV, or M4V" if material_type == "video" else "PDF, DOC, DOCX, PPT, PPTX, TXT, or MD"
        return jsonify({"success": False, "message": f"Unsupported file type. Choose {allowed}."}), 400
    original_filename = safe_original

    title = str(request.form.get("title", "")).strip() or Path(original_filename).stem
    if len(title) > 200:
        return jsonify({"success": False, "message": "Material title must be 200 characters or fewer."}), 400
    uploaded_file.stream.seek(0, os.SEEK_END)
    file_size = uploaded_file.stream.tell()
    uploaded_file.stream.seek(0)
    if file_size == 0:
        return jsonify({"success": False, "message": "The selected file is empty."}), 400

    storage_filename = f"{uuid.uuid4().hex}{extension}"
    mimetype = mimetypes.guess_type(safe_original)[0] or "application/octet-stream"
    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
    destination = MATERIALS_DIR / storage_filename
    try:
        uploaded_file.save(destination)
        result = db.session.execute(text("""
            INSERT INTO course_materials
              (course_id, uploader_id, title, material_type, original_filename,
               storage_filename, mimetype, file_size)
            VALUES (:course_id, :uploader_id, :title, :material_type, :original_filename,
                    :storage_filename, :mimetype, :file_size)
        """), {
            "course_id": course_id,
            "uploader_id": teacher_id,
            "title": title,
            "material_type": material_type,
            "original_filename": original_filename[:255],
            "storage_filename": storage_filename,
            "mimetype": mimetype,
            "file_size": file_size
        })
        db.session.commit()
    except Exception:
        db.session.rollback()
        destination.unlink(missing_ok=True)
        return jsonify({"success": False, "message": "The material could not be saved."}), 500

    return jsonify({"success": True, "message": "Course material uploaded.", "material_id": result.lastrowid}), 201


@app.route("/api/teacher/materials/<int:material_id>", methods=["DELETE"])
def delete_teacher_material(material_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    if session.get("role") != "teacher":
        return jsonify({"success": False, "message": "Teacher access required."}), 403
    material = db.session.execute(text("""
        SELECT cm.storage_filename FROM course_materials cm
        JOIN courses c ON c.course_id=cm.course_id
        WHERE cm.material_id=:material_id AND c.instructor_id=:teacher_id
    """), {"material_id": material_id, "teacher_id": session["user_id"]}).first()
    if not material:
        return jsonify({"success": False, "message": "Material not found in your courses."}), 404
    db.session.execute(text("DELETE FROM course_materials WHERE material_id=:id"), {"id": material_id})
    db.session.commit()
    (MATERIALS_DIR / material.storage_filename).unlink(missing_ok=True)
    return jsonify({"success": True, "message": "Course material removed."}), 200


@app.route("/api/materials/<int:material_id>/download", methods=["GET"])
def download_course_material(material_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    material = db.session.execute(text("""
        SELECT cm.storage_filename, cm.original_filename, cm.material_type, cm.mimetype,
          c.instructor_id, c.course_id
        FROM course_materials cm JOIN courses c ON c.course_id=cm.course_id
        WHERE cm.material_id=:id
    """), {"id": material_id}).first()
    if not material:
        return jsonify({"success": False, "message": "Course material not found."}), 404

    role = session.get("role")
    permitted = role == "admin" or (role == "teacher" and material.instructor_id == session["user_id"])
    if role == "student":
        permitted = db.session.execute(text("""
            SELECT 1 FROM enrollments WHERE user_id=:user_id AND course_id=:course_id
              AND status IN ('active','completed')
        """), {"user_id": session["user_id"], "course_id": material.course_id}).first() is not None
    if not permitted:
        return jsonify({"success": False, "message": "You are not enrolled in this course."}), 403

    return send_from_directory(
        MATERIALS_DIR,
        material.storage_filename,
        mimetype=material.mimetype,
        as_attachment=material.material_type == "notes",
        download_name=material.original_filename,
        conditional=True
    )


@app.route("/api/admin/users", methods=["GET"])
def admin_users():

    # User must be logged in
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    # User must be an admin
    if session.get("role") != "admin":
        return jsonify({
            "success": False,
            "message": "Admin access required."
        }), 403

    try:

        rows = db.session.execute(text("""
            SELECT
                user_id,
                full_name,
                email,
                role,
                created_at
            FROM users
            ORDER BY created_at DESC
        """)).fetchall()

        users = [
            dict(row._mapping)
            for row in rows
        ]

        return jsonify({
            "success": True,
            "users": users
        }), 200

    except Exception as e:

        print("Admin users error:", e)

        return jsonify({
            "success": False,
            "message": "Could not retrieve users."
        }), 500


@app.route("/api/admin/profiles", methods=["GET"])
def admin_profiles():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Admin access required."}), 403
    rows = db.session.execute(text("""
        SELECT u.user_id, u.full_name, u.email, u.role, u.created_at,
          sp.age, sp.education_level, sp.course_degree, sp.interests,
          sp.preferred_learning_style, sp.preferred_difficulty, sp.daily_study_time, sp.learning_goal,
          (SELECT COUNT(*) FROM enrollments e WHERE e.user_id=u.user_id AND e.status='active') AS active_courses,
          (SELECT COUNT(*) FROM student_progress p WHERE p.user_id=u.user_id AND p.status='completed') AS completed_lessons,
          (SELECT COALESCE(SUM(p.time_spent_seconds),0) FROM student_progress p WHERE p.user_id=u.user_id) AS study_seconds,
          (SELECT COALESCE(ROUND(AVG(p.completion_percent),1),0) FROM student_progress p WHERE p.user_id=u.user_id) AS average_completion,
          (SELECT COUNT(*) FROM quiz_attempts qa WHERE qa.user_id=u.user_id AND qa.status IN ('submitted','graded')) AS quiz_attempts,
          (SELECT COALESCE(ROUND(AVG(qa.score),1),0) FROM quiz_attempts qa WHERE qa.user_id=u.user_id AND qa.status='graded' AND qa.score IS NOT NULL) AS average_quiz_score,
          tp.expertise AS teacher_expertise, tp.qualifications AS teacher_qualifications, tp.bio AS teacher_bio,
          (SELECT COUNT(*) FROM courses c WHERE c.instructor_id=u.user_id) AS teaching_courses,
          (SELECT COUNT(DISTINCT e.user_id) FROM enrollments e JOIN courses c ON c.course_id=e.course_id WHERE c.instructor_id=u.user_id AND e.status='active') AS teaching_students,
          (SELECT COALESCE(ROUND(AVG(p.completion_percent),1),0) FROM student_progress p JOIN lessons l ON l.lesson_id=p.lesson_id JOIN courses c ON c.course_id=l.course_id WHERE c.instructor_id=u.user_id) AS class_average_completion
        FROM users u
        LEFT JOIN student_profiles sp ON sp.user_id=u.user_id
        LEFT JOIN teacher_profiles tp ON tp.user_id=u.user_id
        WHERE u.role IN ('student','teacher')
        ORDER BY u.role, u.full_name
    """)).fetchall()
    import json
    profiles = [dict(row._mapping) for row in rows]
    course_rows = db.session.execute(text("""
        SELECT e.user_id, c.title, e.status AS enrollment_status, e.enrolled_at,
          COUNT(DISTINCT l.lesson_id) AS total_lessons,
          COUNT(DISTINCT CASE WHEN p.status='completed' THEN p.progress_id END) AS completed_lessons,
          COALESCE(ROUND(AVG(p.completion_percent), 1), 0) AS average_completion,
          COALESCE(SUM(p.time_spent_seconds), 0) AS study_seconds
        FROM enrollments e
        JOIN courses c ON c.course_id=e.course_id
        LEFT JOIN lessons l ON l.course_id=c.course_id
        LEFT JOIN student_progress p ON p.lesson_id=l.lesson_id AND p.user_id=e.user_id
        GROUP BY e.user_id, c.course_id
        ORDER BY c.title
    """)).fetchall()
    courses_by_user = {}
    for row in course_rows:
        course = dict(row._mapping)
        courses_by_user.setdefault(course.pop("user_id"), []).append(course)
    for profile in profiles:
        profile["courses"] = courses_by_user.get(profile["user_id"], [])
        try:
            profile["interests"] = json.loads(profile.get("interests") or "[]")
        except (TypeError, ValueError):
            profile["interests"] = []
        try:
            profile["teacher_expertise"] = json.loads(profile.get("teacher_expertise") or "[]")
        except (TypeError, ValueError):
            profile["teacher_expertise"] = []
    return jsonify({"success": True, "profiles": profiles}), 200


@app.route("/api/admin/users/<int:user_id>", methods=["PATCH"])
def update_managed_user(user_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Admin access required."}), 403
    data = request.get_json(silent=True) or {}
    role = data.get("role")
    if not isinstance(role, str) or role not in {"student", "teacher"}:
        return jsonify({"success": False, "message": "Choose student or teacher."}), 400
    user = db.session.execute(text("SELECT user_id FROM users WHERE user_id=:id AND role!='admin'"), {"id": user_id}).first()
    if not user:
        return jsonify({"success": False, "message": "Student or teacher account not found."}), 404
    full_name = str(data.get("full_name", "")).strip()
    if not 2 <= len(full_name) <= 255:
        return jsonify({"success": False, "message": "Full name must be between 2 and 255 characters."}), 400
    db.session.execute(text("UPDATE users SET full_name=:name, role=:role WHERE user_id=:id"), {"name": full_name, "role": role, "id": user_id})
    if role == "teacher":
        expertise = data.get("expertise", [])
        if not isinstance(expertise, list) or any(not isinstance(value, str) for value in expertise) or len(expertise) > 30:
            db.session.rollback()
            return jsonify({"success": False, "message": "Enter valid teaching expertise."}), 400
        qualifications = str(data.get("qualifications", "")).strip()
        bio = str(data.get("bio", "")).strip()
        if len(qualifications) > 1000 or len(bio) > 2000:
            db.session.rollback()
            return jsonify({"success": False, "message": "Teacher profile details are too long."}), 400
        import json
        db.session.execute(text("""
            INSERT INTO teacher_profiles (user_id, expertise, qualifications, bio, updated_at)
            VALUES (:id, :expertise, :qualifications, :bio, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET expertise=excluded.expertise,
              qualifications=excluded.qualifications, bio=excluded.bio, updated_at=CURRENT_TIMESTAMP
        """), {"id": user_id, "expertise": json.dumps(expertise), "qualifications": qualifications, "bio": bio})
    else:
        student = data.get("student_profile", {})
        if not isinstance(student, dict):
            db.session.rollback()
            return jsonify({"success": False, "message": "Enter a valid student profile."}), 400
        try:
            age = int(student.get("age")) if str(student.get("age", "")).strip() else None
            study_time = int(student.get("daily_study_time")) if str(student.get("daily_study_time", "")).strip() else None
        except (TypeError, ValueError):
            db.session.rollback()
            return jsonify({"success": False, "message": "Age and study time must be whole numbers."}), 400
        interests = student.get("interests", [])
        if not isinstance(interests, list) or any(not isinstance(value, str) for value in interests):
            db.session.rollback()
            return jsonify({"success": False, "message": "Enter valid areas of interest."}), 400
        education = str(student.get("education_level", "")).strip()
        degree = str(student.get("course_degree", "")).strip()
        style = str(student.get("preferred_learning_style", "")).strip()
        difficulty = str(student.get("preferred_difficulty", "")).strip().lower()
        goal = str(student.get("learning_goal", "")).strip()
        if (age is not None and not 5 <= age <= 120) or (study_time is not None and not 1 <= study_time <= 24):
            db.session.rollback()
            return jsonify({"success": False, "message": "Check the student's age and daily study time."}), 400
        if (difficulty not in {"", "beginner", "intermediate", "advanced"} or len(interests) > 20
                or any(len(value) > 150 for value in interests)
                or len(education) > 100 or len(degree) > 200 or len(style) > 50 or len(goal) > 2000):
            db.session.rollback()
            return jsonify({"success": False, "message": "Check the student's learning preferences."}), 400
        import json
        db.session.execute(text("""
            INSERT INTO student_profiles (user_id, age, education_level, course_degree, interests,
              preferred_learning_style, preferred_difficulty, daily_study_time, learning_goal, updated_at)
            VALUES (:id, :age, :education, :degree, :interests, :style, :difficulty, :study_time, :goal, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET age=excluded.age, education_level=excluded.education_level,
              course_degree=excluded.course_degree, interests=excluded.interests,
              preferred_learning_style=excluded.preferred_learning_style, preferred_difficulty=excluded.preferred_difficulty,
              daily_study_time=excluded.daily_study_time, learning_goal=excluded.learning_goal, updated_at=CURRENT_TIMESTAMP
        """), {"id": user_id, "age": age, "education": education, "degree": degree,
               "interests": json.dumps(interests), "style": style, "difficulty": difficulty,
               "study_time": study_time, "goal": goal})
    db.session.commit()
    return jsonify({"success": True, "message": "Account role and profile updated."}), 200


@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
def delete_managed_student(user_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Admin access required."}), 403

    result = db.session.execute(
        text("DELETE FROM users WHERE user_id=:id AND role='student'"),
        {"id": user_id}
    )
    if result.rowcount == 0:
        db.session.rollback()
        return jsonify({"success": False, "message": "Student account not found. Only student accounts can be deleted here."}), 404

    db.session.commit()
    return jsonify({"success": True, "message": "Student account and associated learning records deleted."}), 200


@app.route("/api/admin/courses", methods=["GET", "POST"])
def admin_courses():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Admin access required."}), 403

    if request.method == "GET":
        rows = db.session.execute(text("""
            SELECT c.course_id, c.title, c.description, c.difficulty, c.is_published, c.instructor_id,
                   s.name AS subject, u.full_name AS instructor, COUNT(e.enrollment_id) AS student_count
            FROM courses c LEFT JOIN subjects s ON s.subject_id = c.subject_id
            LEFT JOIN enrollments e ON e.course_id = c.course_id
            LEFT JOIN users u ON u.user_id = c.instructor_id
            GROUP BY c.course_id ORDER BY c.title
        """)).fetchall()
        return jsonify({"success": True, "courses": [dict(row._mapping) for row in rows]}), 200

    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "")).strip()
    difficulty = str(data.get("difficulty", "beginner")).strip().lower()
    subject_name = str(data.get("subject", "General")).strip() or "General"
    try:
        instructor_id = int(data.get("instructor_id")) if data.get("instructor_id") else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Choose a valid teacher."}), 400
    if not title or len(title) > 200 or len(description) > 2000 or len(subject_name) > 150 or difficulty not in {"beginner", "intermediate", "advanced"}:
        return jsonify({"success": False, "message": "Enter a title, a valid difficulty, and shorter course details."}), 400
    if db.session.execute(text("SELECT 1 FROM courses WHERE title = :title COLLATE NOCASE"), {"title": title}).first():
        return jsonify({"success": False, "message": "A course with that title already exists."}), 409
    db.session.execute(text("INSERT OR IGNORE INTO subjects (name) VALUES (:name)"), {"name": subject_name})
    subject_id = db.session.execute(text("SELECT subject_id FROM subjects WHERE name = :name COLLATE NOCASE"), {"name": subject_name}).scalar_one()
    if instructor_id is not None and not db.session.execute(text("SELECT 1 FROM users WHERE user_id=:id AND role='teacher'"), {"id": instructor_id}).first():
        db.session.rollback()
        return jsonify({"success": False, "message": "Choose an existing teacher account."}), 400
    try:
        result = db.session.execute(text("""
            INSERT INTO courses (subject_id, instructor_id, title, description, difficulty, is_published)
            VALUES (:subject_id, :instructor_id, :title, :description, :difficulty, 1)
        """), {"subject_id": subject_id, "instructor_id": instructor_id, "title": title, "description": description, "difficulty": difficulty})
        db.session.commit()
        return jsonify({"success": True, "message": "Course created and published.", "course_id": result.lastrowid}), 201
    except Exception as error:
        db.session.rollback()
        if "UNIQUE" in str(error).upper():
            return jsonify({"success": False, "message": "A course with that title already exists."}), 409
        raise


@app.route("/api/admin/courses/<int:course_id>", methods=["PATCH"])
def update_admin_course(course_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Admin access required."}), 403
    data = request.get_json(silent=True) or {}
    updates = []
    params = {"id": course_id}
    if "is_published" in data:
        published = data["is_published"]
        if published not in (True, False, 0, 1):
            return jsonify({"success": False, "message": "Choose a valid publishing state."}), 400
        updates.append("is_published=:published")
        params["published"] = int(published)
    if "instructor_id" in data:
        try:
            instructor_id = int(data["instructor_id"]) if data["instructor_id"] not in (None, "") else None
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Choose a valid teacher."}), 400
        if instructor_id is not None and not db.session.execute(
            text("SELECT 1 FROM users WHERE user_id=:id AND role='teacher'"), {"id": instructor_id}
        ).first():
            return jsonify({"success": False, "message": "Choose an existing teacher account."}), 400
        updates.append("instructor_id=:instructor_id")
        params["instructor_id"] = instructor_id
    if not updates:
        return jsonify({"success": False, "message": "Choose a course setting to update."}), 400
    result = db.session.execute(
        text(f"UPDATE courses SET {', '.join(updates)}, updated_at=CURRENT_TIMESTAMP WHERE course_id=:id"),
        params
    )
    if result.rowcount == 0:
        db.session.rollback()
        return jsonify({"success": False, "message": "Course not found."}), 404
    db.session.commit()
    return jsonify({"success": True, "message": "Course settings updated."}), 200
@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "You have been signed out."}), 200

if __name__ == "__main__":
    app.run(debug=True)
