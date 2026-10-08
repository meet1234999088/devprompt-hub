from flask import Flask, render_template, request, redirect, url_for, jsonify
import anthropic
import os
import sqlite3
from pathlib import Path

app = Flask(__name__)

DB = Path("data/prompts.db")


# =========================================================
# DATABASE
# =========================================================

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

    # Add sample prompts if database is empty
    if conn.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 0:

        conn.execute(
            """
            INSERT INTO prompts(title, category, content)
            VALUES (?, ?, ?)
            """,
            (
                "Explain Python code",
                "Coding",
                "Explain the following Python code step by step. "
                "Identify bugs, edge cases, and suggest improvements."
            )
        )

        conn.execute(
            """
            INSERT INTO prompts(title, category, content)
            VALUES (?, ?, ?)
            """,
            (
                "Debug an error",
                "Debugging",
                "Analyze this error message, identify the likely root cause, "
                "and give a minimal fix followed by a better long-term solution."
            )
        )

    conn.commit()
    conn.close()


# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def index():

    q = request.args.get("q", "").strip()

    conn = db()

    if q:

        prompts = conn.execute(
            """
            SELECT *
            FROM prompts
            WHERE title LIKE ?
               OR category LIKE ?
               OR content LIKE ?
            ORDER BY id DESC
            """,
            (
                f"%{q}%",
                f"%{q}%",
                f"%{q}%"
            )
        ).fetchall()

    else:

        prompts = conn.execute(
            """
            SELECT *
            FROM prompts
            ORDER BY id DESC
            """
        ).fetchall()

    conn.close()

    return render_template(
        "index.html",
        prompts=prompts,
        q=q
    )


# =========================================================
# CREATE PROMPT
# =========================================================

@app.route("/create", methods=["GET", "POST"])
def create():

    if request.method == "POST":

        title = request.form["title"].strip()
        category = request.form["category"].strip()
        content = request.form["content"].strip()

        if title and category and content:

            conn = db()

            conn.execute(
                """
                INSERT INTO prompts(title, category, content)
                VALUES (?, ?, ?)
                """,
                (
                    title,
                    category,
                    content
                )
            )

            conn.commit()
            conn.close()

            return redirect(url_for("index"))

    return render_template("create.html")


# =========================================================
# VIEW PROMPT
# =========================================================

@app.route("/prompt/<int:prompt_id>")
def prompt(prompt_id):

    conn = db()

    item = conn.execute(
        """
        SELECT *
        FROM prompts
        WHERE id = ?
        """,
        (prompt_id,)
    ).fetchone()

    conn.close()

    if not item:

        return "Prompt not found", 404

    return render_template(
        "prompt.html",
        prompt=item
    )


# =========================================================
# CLAUDE API
# =========================================================

@app.route("/improve", methods=["POST"])
def improve():

    print("")
    print("========================================")
    print("CLAUDE REQUEST RECEIVED")
    print("========================================")

    # -----------------------------------------------------
    # Check API key
    # -----------------------------------------------------

    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:

        print("ERROR: ANTHROPIC_API_KEY is not configured.")

        return jsonify({
            "error": "Claude API key is not configured."
        }), 500


    # -----------------------------------------------------
    # Get prompt from browser
    # -----------------------------------------------------

    data = request.get_json()

    if not data:

        print("ERROR: No JSON data received.")

        return jsonify({
            "error": "No data received."
        }), 400


    prompt = data.get("prompt", "").strip()

    if not prompt:

        print("ERROR: Empty prompt.")

        return jsonify({
            "error": "Please enter a prompt."
        }), 400


    print("Prompt received successfully.")
    print("Prompt length:", len(prompt))


    # -----------------------------------------------------
    # Create Claude client
    # -----------------------------------------------------

    try:

        client = anthropic.Anthropic(
            api_key=api_key
        )

        print("Claude client created successfully.")


        # -------------------------------------------------
        # Send request to Claude
        # -------------------------------------------------

        message = client.messages.create(

            model="claude-sonnet-4-6",

            max_tokens=1000,

            system="""
You are a professional prompt-engineering assistant.

Improve the user's AI prompt while preserving its
original purpose.

Make the prompt:
- Clear
- Specific
- Well structured
- Easy for an AI model to understand
- Explicit about the expected output

Do not change the user's original goal.

Return ONLY the improved prompt.
Do not explain the changes.
Do not add introductory text.
""",

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )


        # -------------------------------------------------
        # Extract Claude response
        # -------------------------------------------------

        result = ""

        for block in message.content:

            if getattr(block, "type", None) == "text":

                result += block.text


        print("Claude response received successfully.")
        print("Response length:", len(result))

        print("========================================")
        print("CLAUDE REQUEST SUCCESSFUL")
        print("========================================")
        print("")


        return jsonify({
            "result": result
        })


    # -----------------------------------------------------
    # Claude error
    # -----------------------------------------------------

    except Exception as e:

        print("")
        print("========================================")
        print("CLAUDE API ERROR")
        print("========================================")
        print(type(e).__name__)
        print(str(e))
        print("========================================")
        print("")

        return jsonify({
            "error": str(e)
        }), 500


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    init_db()

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )