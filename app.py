import os
import mimetypes
from datetime import datetime
from io import BytesIO

from flask import Flask, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from sqlalchemy import func
from flask_cors import CORS

# ----------------
# Flask App
# ----------------
app = Flask(__name__)

# CORS
CORS(
    app,
    resources={r"/*": {"origins": ["http://127.0.0.1:5500", "https://project-connect-x4ei.onrender.com"]}},
    supports_credentials=True,
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"]
)

# Max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Database setup
pg_user = os.getenv("PGUSER")
pg_pass = os.getenv("PGPASSWORD")
pg_host = os.getenv("PGHOST")
pg_port = os.getenv("PGPORT", "5432")
pg_db = os.getenv("PGDATABASE")
pg_sslmode = os.getenv("PGSSLMODE", "require")

if pg_user and pg_pass and pg_host and pg_db:
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"postgresql+psycopg2://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
        f"?sslmode={pg_sslmode}"
    )
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'  # local fallback

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------
# Models
# ----------------
class FirmImage(db.Model):
    __tablename__ = "firm_images"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    image_data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    cv_filename = db.Column(db.String(255), nullable=False)
    cv_data = db.Column(db.LargeBinary, nullable=False)
    id_filename = db.Column(db.String(255), nullable=False)
    id_data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Assignment(db.Model):
    __tablename__ = "assignments"
    id = db.Column(db.Integer, primary_key=True)
    lecture_id = db.Column(db.String(50), index=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    deadline_iso = db.Column(db.String(50))
    status = db.Column(db.String(20), default="open")
    file_filename = db.Column(db.String(255))
    file_data = db.Column(db.LargeBinary)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Submission(db.Model):
    __tablename__ = "submissions"
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)
    user_code = db.Column(db.String(50), nullable=False, index=True)
    filename = db.Column(db.String(255))
    file_data = db.Column(db.LargeBinary)
    description = db.Column(db.Text)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

with app.app_context():
    db.create_all()

# ----------------
# Helpers
# ----------------
def safe_filename(file_obj):
    if not file_obj:
        return ""
    name = getattr(file_obj, "filename", file_obj)
    return secure_filename(name or "")

def guess_mimetype(filename):
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"

# ----------------
# Routes
# ----------------
@app.route("/")
def index():
    return jsonify({"message": "Flask API (Postgres/Neon) is live!"})

@app.route("/health", methods=["GET"])
def health_check():
    try:
        db.session.execute("SELECT 1")
        return jsonify({"status": "healthy", "db": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# ============================
# ASSIGNMENTS
# ============================
@app.route("/api/assignments", methods=["POST"])
def create_assignment():
    lecture_id = request.form.get("lecture_id")
    title = request.form.get("title")
    deadline_iso = request.form.get("deadline_iso")
    description = request.form.get("description")
    if not lecture_id or not title or not deadline_iso:
        return jsonify({"error": "lecture_id, title, deadline_iso required"}), 400

    try:
        file_filename = None
        file_data = None
        if "file" in request.files:
            f = request.files["file"]
            file_filename = safe_filename(f)
            file_data = f.read()

        assignment = Assignment(
            lecture_id=lecture_id,
            title=title,
            description=description,
            deadline_iso=deadline_iso,
            file_filename=file_filename,
            file_data=file_data
        )
        db.session.add(assignment)
        db.session.commit()

        file_url = f"/serve-assignment-file/{assignment.id}" if file_filename else None
        return jsonify({
            "message": "Assignment created",
            "assignment": {
                "id": assignment.id,
                "lecture_id": assignment.lecture_id,
                "title": assignment.title,
                "description": assignment.description,
                "deadline_iso": assignment.deadline_iso,
                "status": assignment.status,
                "file_url": file_url,
                "created_at": assignment.created_at.isoformat() if assignment.created_at else None
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/assignments/<int:assignment_id>/submissions", methods=["PUT", "OPTIONS"])
def update_submission(assignment_id):
    if request.method == "OPTIONS":
        # preflight request
        return "", 200

    user_code = request.form.get("user_code")
    if not user_code:
        return jsonify({"error": "user_code required"}), 400

    try:
        filename = None
        data = None
        if "file" in request.files:
            f = request.files["file"]
            filename = safe_filename(f)
            data = f.read()

        description = request.form.get("description")

        # Find existing submission
        sub = Submission.query.filter_by(assignment_id=assignment_id, user_code=user_code).first()
        if not sub:
            sub = Submission(assignment_id=assignment_id, user_code=user_code)

        if filename:
            sub.filename = filename
            sub.file_data = data
        if description is not None:
            sub.description = description

        sub.updated_at = datetime.utcnow()
        db.session.add(sub)
        db.session.commit()

        file_url = f"/serve-submission-file/{sub.id}" if sub.filename else None
        return jsonify({
            "message": "Submission updated",
            "id": sub.id,
            "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
            "file_url": file_url
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/assignments/<int:assignment_id>/submissions", methods=["GET"])
def list_submissions_for_assignment(assignment_id):
    subs = Submission.query.filter_by(assignment_id=assignment_id).all()
    result = []
    for s in subs:
        result.append({
            "id": s.id,
            "assignment_id": s.assignment_id,
            "user_code": s.user_code,
            "filename": s.filename,
            "file_url": f"/serve-submission-file/{s.id}" if s.filename else None,
            "description": s.description,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None
        })
    return jsonify({"submissions": result})

@app.route("/serve-submission-file/<int:submission_id>", methods=["GET"])
def serve_submission_file(submission_id):
    s = Submission.query.get(submission_id)
    if not s or not s.file_data:
        return jsonify({"error": "File not found"}), 404
    return send_file(BytesIO(s.file_data), mimetype=guess_mimetype(s.filename),
                     as_attachment=True, download_name=s.filename)

# ----------------
# Run App
# ----------------
if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug)
