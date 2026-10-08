from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from pathlib import Path

app = Flask(__name__)
DB = Path("data/prompts.db")

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    DB.parent.mkdir(exist_ok=True)
    conn = db()
    conn.execute("""CREATE TABLE IF NOT EXISTS prompts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    if conn.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 0:
        conn.execute("INSERT INTO prompts(title,category,content) VALUES (?,?,?)",
                     ("Explain Python code", "Coding",
                      "Explain the following Python code step by step. Identify bugs, edge cases, and suggest improvements."))
        conn.execute("INSERT INTO prompts(title,category,content) VALUES (?,?,?)",
                     ("Debug an error", "Debugging",
                      "Analyze this error message, identify the likely root cause, and give a minimal fix followed by a better long-term solution."))
    conn.commit()
    conn.close()

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    conn = db()
    if q:
        prompts = conn.execute(
            "SELECT * FROM prompts WHERE title LIKE ? OR category LIKE ? OR content LIKE ? ORDER BY id DESC",
            (f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        prompts = conn.execute("SELECT * FROM prompts ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("index.html", prompts=prompts, q=q)

@app.route("/create", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        title = request.form["title"].strip()
        category = request.form["category"].strip()
        content = request.form["content"].strip()
        if title and category and content:
            conn = db()
            conn.execute("INSERT INTO prompts(title,category,content) VALUES (?,?,?)",
                         (title, category, content))
            conn.commit()
            conn.close()
            return redirect(url_for("index"))
    return render_template("create.html")

@app.route("/prompt/<int:prompt_id>")
def prompt(prompt_id):
    conn = db()
    item = conn.execute("SELECT * FROM prompts WHERE id=?", (prompt_id,)).fetchone()
    conn.close()
    if not item:
        return "Prompt not found", 404
    return render_template("prompt.html", prompt=item)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
