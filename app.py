import os
import psycopg2
from flask import Flask, request, jsonify, send_file
from io import BytesIO
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime
import json

# ----------------
# Flask Config
# ----------------
app = Flask(__name__)

# Max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# SQLAlchemy config for metadata only
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------
# CORS settings
# ----------------
CORS(
    app,
    resources={
        r"/api/*": {"origins": ["http://127.0.0.1:5500", "http://localhost:5500", "https://project-connect-x4ei.onrender.com"]},
        r"/documents/*": {"origins": ["http://127.0.0.1:5500", "http://localhost:5500"]}
    },
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"]
)

# ----------------
# PostgreSQL Connection
# ----------------
def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT", "5432"),
        sslmode=os.getenv("PGSSLMODE", "require")
    )

# ----------------
# SQLAlchemy Models (metadata only)
# ----------------
class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), nullable=False)
    cv_filename = db.Column(db.String(255), nullable=False)
    id_filename = db.Column(db.String(255), nullable=False)

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lecture_id = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    deadline_iso = db.Column(db.String(50))
    status = db.Column(db.String(20), default="open")
    file_name = db.Column(db.String(255))  # File name in DB

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, nullable=False)
    user_code = db.Column(db.String(50), nullable=False)
    file_name = db.Column(db.String(255))
    description = db.Column(db.Text)
    updated_at = db.Column(db.String(50))

with app.app_context():
    db.create_all()

# ----------------
# HELPERS
# ----------------
def save_file_to_db(file, table, user_code=None, lecture_id=None, assignment_id=None, description=None):
    filename = secure_filename(file.filename)
    content = file.read()
    try:
        conn = get_connection()
        cur = conn.cursor()
        if table == "documents":
            # store CV and ID separately
            cv_file = content if file.name == "cvFile" else None
            id_file = content if file.name == "idFile" else None
            cur.execute("""
                INSERT INTO documents_table (user_code, cv_filename, cv_data, id_filename, id_data)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (user_code, filename, cv_file, filename, id_file))
        elif table == "assignments":
            cur.execute("""
                INSERT INTO assignments_table (lecture_id, title, description, deadline_iso, file_name, file_data)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """, (lecture_id, filename, description, datetime.utcnow().isoformat(), filename, content))
        elif table == "submissions":
            cur.execute("""
                INSERT INTO submissions_table (assignment_id, user_code, file_name, file_data, description, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """, (assignment_id, user_code, filename, content, description, datetime.utcnow().isoformat()))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return new_id, filename
    except Exception as e:
        print(e)
        return None, None

def get_file_from_db(table, file_id):
    try:
        conn = get_connection()
        cur = conn.cursor()
        if table == "assignments":
            cur.execute("SELECT file_name, file_data FROM assignments_table WHERE id=%s", (file_id,))
        elif table == "submissions":
            cur.execute("SELECT file_name, file_data FROM submissions_table WHERE id=%s", (file_id,))
        else:
            return None
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return row[0], row[1]
        return None
    except Exception as e:
        print(e)
        return None

# ----------------
# ASSIGNMENTS CRUD
# ----------------
@app.route("/api/assignments", methods=["POST"])
def create_assignment():
    lecture_id = request.form.get("lecture_id")
    title = request.form.get("title")
    description = request.form.get("description")
    deadline_iso = request.form.get("deadline_iso")
    if not lecture_id or not title or not deadline_iso:
        return jsonify({"error": "lecture_id, title, deadline_iso required"}), 400

    file = request.files.get("file")
    file_name = None
    if file:
        # store file in PostgreSQL
        file_id, file_name = save_file_to_db(file, "assignments", lecture_id=lecture_id, description=description)

    new_assignment = Assignment(
        lecture_id=lecture_id,
        title=title,
        description=description,
        deadline_iso=deadline_iso,
        file_name=file_name
    )
    db.session.add(new_assignment)
    db.session.commit()
    return jsonify({"message": "Assignment created", "id": new_assignment.id, "file_name": file_name}), 201

@app.route("/api/assignments/<int:assignment_id>/download", methods=["GET"])
def download_assignment_file(assignment_id):
    file_name, file_data = get_file_from_db("assignments", assignment_id)
    if not file_data:
        return jsonify({"error": "File not found"}), 404
    return send_file(BytesIO(file_data), download_name=file_name, as_attachment=True)

# ----------------
# SUBMISSIONS CRUD
# ----------------
@app.route("/api/assignments/<int:assignment_id>/submissions", methods=["PUT"])
def upload_submission(assignment_id):
    user_code = request.form.get("user_code")
    description = request.form.get("description")
    file = request.files.get("file")
    if not user_code or not file:
        return jsonify({"error": "user_code and file are required"}), 400

    file_id, file_name = save_file_to_db(file, "submissions", assignment_id=assignment_id, user_code=user_code, description=description)
    return jsonify({"message": "Submission uploaded", "file_name": file_name}), 201

@app.route("/api/assignments/<int:assignment_id>/submissions/<int:submission_id>/download", methods=["GET"])
def download_submission_file(assignment_id, submission_id):
    file_name, file_data = get_file_from_db("submissions", submission_id)
    if not file_data:
        return jsonify({"error": "File not found"}), 404
    return send_file(BytesIO(file_data), download_name=file_name, as_attachment=True)

# ----------------
# RUN
# ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
