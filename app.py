from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
import os
from pathlib import Path
import anthropic

app = Flask(__name__)
DB = Path("data/prompts.db")


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB.parent.mkdir(exist_ok=True)

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

    if conn.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO prompts(title, category, content) VALUES (?, ?, ?)",
            (
                "Explain Python code",
                "Coding",
                "Explain the following Python code step by step. "
                "Identify bugs, edge cases, and suggest improvements."
            )
        )

        conn.execute(
            "INSERT INTO prompts(title, category, content) VALUES (?, ?, ?)",
            (
                "Debug an error",
                "Debugging",
                "Analyze this error message, identify the likely root cause, "
                "and give a minimal fix followed by a better long-term solution."
            )
        )

    conn.commit()
    conn.close()


@app.route("/")
def index():
    q = request.args.get("q", "").strip()

    conn = db()

    if q:
        prompts = conn.execute(
            """
            SELECT * FROM prompts
            WHERE title LIKE ?
               OR category LIKE ?
               OR content LIKE ?
            ORDER BY id DESC
            """,
            (f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        prompts = conn.execute(
            "SELECT * FROM prompts ORDER BY id DESC"
        ).fetchall()

    conn.close()

    return render_template(
        "index.html",
        prompts=prompts,
        q=q
    )


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
                INSERT INTO prompts(title, category, content)
                VALUES (?, ?, ?)
                """,
                (title, category, content)
            )

            conn.commit()
            conn.close()

            return redirect(url_for("index"))

    return render_template("create.html")


@app.route("/prompt/<int:prompt_id>")
def prompt(prompt_id):

    conn = db()

    item = conn.execute(
        "SELECT * FROM prompts WHERE id=?",
        (prompt_id,)
    ).fetchone()

    conn.close()

    if not item:
        return "Prompt not found", 404

    return render_template(
        "prompt.html",
        prompt=item
    )


@app.route("/improve", methods=["POST"])
def improve():

    data = request.get_json(silent=True) or {}

    prompt = data.get("prompt", "").strip()

    if not prompt:
        return jsonify({
            "error": "Please provide a prompt."
        }), 400

    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # No API key configured
    if not api_key:
        return jsonify({
            "mode": "demo",
            "result": demo_improvement(prompt)
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
                    "content": prompt
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
            "result": result
        })

    except Exception as e:

        print("CLAUDE REQUEST FAILED:", str(e))

        # Keep the app useful even when API credits are unavailable.
        return jsonify({
            "mode": "demo",
            "result": demo_improvement(prompt),
            "message": (
                "Claude API is currently unavailable. "
                "Showing a local demo improvement instead."
            )
        })


def demo_improvement(prompt):

    return f"""Improved Prompt — Demo Mode

Role:
Act as an expert developer and prompt engineer.

Task:
{prompt}

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


if __name__ == "__main__":
    init_db()
    app.run(debug=True)