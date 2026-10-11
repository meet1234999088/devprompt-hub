
from flask import (
    Flask, render_template, request, redirect,
    url_for, jsonify, session, flash
)
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path
import sqlite3
import os
import anthropic

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "local-development-key-change-before-deploy"
)

DB = Path("data/prompts.db")


# ---------------- DATABASE ----------------

def db():
    DB.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Safely upgrade an existing prompts table.
    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(prompts)"
        ).fetchall()
    }

    if "user_id" not in columns:
        conn.execute("""
            ALTER TABLE prompts
            ADD COLUMN user_id INTEGER REFERENCES users(id)
        """)

    # REMOVE THE EXACT TRIAL PROMPT.
    # This runs at startup on local and deployed databases.
    conn.execute("""
        DELETE FROM prompts
        WHERE title = ? AND category = ?
    """, ("ASDFGHJK", "SDFGHJ"))

    # Add starter prompts only if the library is empty.
    count = conn.execute(
        "SELECT COUNT(*) FROM prompts"
    ).fetchone()[0]

    if count == 0:
        sample_prompts = [
            (
                "Explain Python code",
                "Coding",
                "Explain the following Python code step by step. "
                "Identify bugs, edge cases, and suggest improvements."
            ),
            (
                "Debug an error",
                "Debugging",
                "Analyze this error message, identify the likely root cause, "
                "and provide a minimal fix followed by a long-term solution."
            ),
            (
                "Write unit tests",
                "Testing",
                "Generate comprehensive unit tests for the provided code. "
                "Cover normal cases, edge cases, and error handling."
            ),
            (
                "Generate documentation",
                "Documentation",
                "Create clear technical documentation for the provided code. "
                "Explain its purpose, parameters, return values, and examples."
            ),
            (
                "Improve an AI prompt",
                "AI & Machine Learning",
                "Review the following AI prompt and improve its clarity, "
                "specificity, structure, and expected output."
            )
        ]

        conn.executemany("""
            INSERT INTO prompts (title, category, content)
            VALUES (?, ?, ?)
        """, sample_prompts)

    conn.commit()
    conn.close()


init_db()


# ---------------- AUTHENTICATION HELPER ----------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login", next=request.path))

        return view(*args, **kwargs)

    return wrapped


# ---------------- REGISTER ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Please complete every field.", "error")

        elif len(username) < 3 or len(username) > 30:
            flash("Username must be between 3 and 30 characters.", "error")

        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")

        else:
            conn = db()

            try:
                cursor = conn.execute("""
                    INSERT INTO users (username, email, password_hash)
                    VALUES (?, ?, ?)
                """, (
                    username,
                    email,
                    generate_password_hash(password)
                ))

                conn.commit()

                session.clear()
                session["user_id"] = cursor.lastrowid
                session["username"] = username

                flash("Account created successfully!", "success")
                return redirect(url_for("index"))

            except sqlite3.IntegrityError:
                flash(
                    "That username or email is already registered.",
                    "error"
                )

            finally:
                conn.close()

    return render_template("register.html")


# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        identity = request.form.get("identity", "").strip()
        password = request.form.get("password", "")

        conn = db()

        user = conn.execute("""
            SELECT * FROM users
            WHERE username = ? OR email = ?
        """, (identity, identity.lower())).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password_hash"], password
        ):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]

            destination = request.args.get("next", "")

            if destination.startswith("/") and not destination.startswith("//"):
                return redirect(destination)

            return redirect(url_for("index"))

        flash("Invalid username/email or password.", "error")

    return render_template("login.html")


# ---------------- LOGOUT ----------------

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# ---------------- HOMEPAGE, SEARCH & FILTERS ----------------

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    selected_category = request.args.get("category", "").strip()

    conn = db()

    categories = conn.execute("""
        SELECT DISTINCT category
        FROM prompts
        WHERE TRIM(category) != ''
        ORDER BY category COLLATE NOCASE
    """).fetchall()

    sql = "SELECT * FROM prompts"
    conditions = []
    params = []

    if q:
        conditions.append("""
            (
                title LIKE ?
                OR category LIKE ?
                OR content LIKE ?
            )
        """)

        term = f"%{q}%"
        params.extend([term, term, term])

    if selected_category:
        conditions.append("category = ?")
        params.append(selected_category)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY id DESC"

    prompts = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template(
        "index.html",
        prompts=prompts,
        q=q,
        categories=categories,
        selected_category=selected_category
    )


# ---------------- CREATE PROMPT ----------------

@app.route("/create", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        content = request.form.get("content", "").strip()

        if not title or not category or not content:
            flash("Please complete every field.", "error")
            return render_template("create.html")

        conn = db()

        conn.execute("""
            INSERT INTO prompts (title, category, content, user_id)
            VALUES (?, ?, ?, ?)
        """, (
            title,
            category,
            content,
            session["user_id"]
        ))

        conn.commit()
        conn.close()

        flash("Prompt created successfully!", "success")
        return redirect(url_for("my_prompts"))

    return render_template("create.html")


# ---------------- MY PROMPTS ----------------

@app.route("/my-prompts")
@login_required
def my_prompts():
    conn = db()

    prompts = conn.execute("""
        SELECT * FROM prompts
        WHERE user_id = ?
        ORDER BY id DESC
    """, (session["user_id"],)).fetchall()

    conn.close()

    return render_template("my_prompts.html", prompts=prompts)


# ---------------- PROMPT DETAILS ----------------

@app.route("/prompt/<int:prompt_id>")
def prompt(prompt_id):
    conn = db()

    item = conn.execute("""
        SELECT * FROM prompts WHERE id = ?
    """, (prompt_id,)).fetchone()

    conn.close()

    if not item:
        return "Prompt not found", 404

    return render_template("prompt.html", prompt=item)


# ---------------- IMPROVE PROMPT WITH CLAUDE ----------------

@app.route("/improve", methods=["POST"])
def improve():
    data = request.get_json(silent=True) or {}
    prompt_text = data.get("prompt", "").strip()

    if not prompt_text:
        return jsonify({
            "error": "Please provide a prompt."
        }), 400

    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        return jsonify({
            "mode": "demo",
            "result": demo_improvement(prompt_text),
            "message": (
                "Demo Mode: This is a local template, "
                "not a response generated by Claude."
            )
        })

    try:
        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=(
                "You are an expert prompt engineer. Improve the user's "
                "developer prompt while preserving its original intent. "
                "Make it clearer, more specific, structured, and useful. "
                "Return only the improved prompt."
            ),
            messages=[
                {
                    "role": "user",
                    "content": prompt_text
                }
            ]
        )

        result = "\n".join(
            block.text
            for block in response.content
            if hasattr(block, "text")
        )

        return jsonify({
            "mode": "claude",
            "result": result,
            "message": "Your prompt was improved using Claude."
        })

    except Exception as error:
        print("CLAUDE REQUEST FAILED:", str(error))

        return jsonify({
            "mode": "demo",
            "result": demo_improvement(prompt_text),
            "message": (
                "Claude is unavailable. Showing a demo improvement instead."
            )
        })


# ---------------- DEMO IMPROVEMENT ----------------

def demo_improvement(prompt_text):
    return f"""Improved Prompt — Demo Mode

Role:
Act as an expert developer and prompt engineer.

Task:
{prompt_text}

Requirements:
1. Analyze the request carefully.
2. Provide a clear and structured response.
3. Identify important assumptions and edge cases.
4. Explain reasoning where useful.
5. Provide practical recommendations.
6. Keep the response concise and technically accurate.

Expected Output:
Return the solution in a clear structure with appropriate examples,
code snippets, or step-by-step instructions where relevant.
"""


# ---------------- RUN APPLICATION ----------------

if __name__ == "__main__":
    app.run(debug=True)
