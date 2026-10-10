from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
import os
from pathlib import Path
import anthropic

app = Flask(__name__)

DB = Path("data/prompts.db")


# ---------------- DATABASE ----------------

def db():
    DB.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

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

        conn.executemany(
            """
            INSERT INTO prompts (title, category, content)
            VALUES (?, ?, ?)
            """,
            sample_prompts
        )

    conn.commit()
    conn.close()


# Initialize the database when the application starts.
init_db()


# ---------------- HOMEPAGE, SEARCH & FILTERS ----------------

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    selected_category = request.args.get("category", "").strip()

    conn = db()

    # Get all available categories.
    categories = conn.execute("""
        SELECT DISTINCT category
        FROM prompts
        WHERE TRIM(category) != ''
        ORDER BY category COLLATE NOCASE
    """).fetchall()

    # Build the prompt query.
    sql = "SELECT * FROM prompts"
    conditions = []
    params = []

    # Search by title, category, or content.
    if q:
        conditions.append("""
            (
                title LIKE ?
                OR category LIKE ?
                OR content LIKE ?
            )
        """)

        search_term = f"%{q}%"

        params.extend([
            search_term,
            search_term,
            search_term
        ])

    # Filter by selected category.
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
def create():
    if request.method == "POST":

        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        content = request.form.get("content", "").strip()

        if title and category and content:
            conn = db()

            conn.execute(
                """
                INSERT INTO prompts (title, category, content)
                VALUES (?, ?, ?)
                """,
                (title, category, content)
            )

            conn.commit()
            conn.close()

            return redirect(url_for("index"))

    return render_template("create.html")


# ---------------- PROMPT DETAILS ----------------

@app.route("/prompt/<int:prompt_id>")
def prompt(prompt_id):
    conn = db()

    item = conn.execute(
        "SELECT * FROM prompts WHERE id = ?",
        (prompt_id,)
    ).fetchone()

    conn.close()

    if not item:
        return "Prompt not found", 404

    return render_template(
        "prompt.html",
        prompt=item
    )


# ---------------- IMPROVE PROMPT ----------------

@app.route("/improve", methods=["POST"])
def improve():
    data = request.get_json(silent=True) or {}

    prompt_text = data.get("prompt", "").strip()

    if not prompt_text:
        return jsonify({
            "error": "Please provide a prompt."
        }), 400

    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # Use demo mode when no API key is configured.
    if not api_key:
        return jsonify({
            "mode": "demo",
            "result": demo_improvement(prompt_text),
            "message": (
                "Demo Mode: This is a locally generated template, "
                "not a response generated by Claude."
            )
        })

    try:
        print("CLAUDE REQUEST RECEIVED")

        client = anthropic.Anthropic(
            api_key=api_key
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=(
                "You are an expert prompt engineer. "
                "Improve the user's developer prompt while preserving "
                "its original intent. Make it clearer, more specific, "
                "structured, and useful. Return only the improved prompt."
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

        print("CLAUDE REQUEST SUCCESS")

        return jsonify({
            "mode": "claude",
            "result": result,
            "message": "Your prompt was improved using Claude."
        })

    except Exception as e:
        # Log the error without exposing the API key.
        print("CLAUDE REQUEST FAILED:", str(e))

        return jsonify({
            "mode": "demo",
            "result": demo_improvement(prompt_text),
            "message": (
                "Claude API is currently unavailable. "
                "Showing a local demo improvement instead."
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
4. Explain the reasoning where useful.
5. Provide practical, implementation-ready recommendations.
6. Keep the response concise and technically accurate.

Expected Output:
Return the solution in a clear structure with appropriate examples,
code snippets, or step-by-step instructions where relevant.
"""


# ---------------- RUN APPLICATION ----------------

if __name__ == "__main__":
    app.run(debug=True)