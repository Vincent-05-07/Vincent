# app.py
import os
import uuid

import mimetypes
import logging
import traceback
from datetime import datetime
from io import BytesIO

from flask import Flask, request, jsonify, send_file, current_app
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from sqlalchemy import func
from flask_cors import CORS, cross_origin
from werkzeug.exceptions import RequestEntityTooLarge, HTTPException

# ----------------
# Flask App
# ----------------


app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


# ----------------
# Logging
# ----------------
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
app.logger.setLevel(logging.DEBUG)

# ----------------
# Config
# ----------------
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(BASE_DIR, "uploads", "documents"))
os.makedirs(DEFAULT_UPLOAD_DIR, exist_ok=True)
app.config['UPLOAD_DIR'] = DEFAULT_UPLOAD_DIR

# DB config: Postgres if env vars present, otherwise SQLite fallback
pg_user = os.getenv("PGUSER")
pg_pass = os.getenv("PGPASSWORD")
pg_host = os.getenv("PGHOST")
pg_port = os.getenv("PGPORT", "5432")
pg_db = os.getenv("PGDATABASE")
pg_sslmode = os.getenv("PGSSLMODE", "require")

if pg_user and pg_pass and pg_host and pg_db:
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"postgresql+psycopg2://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}?sslmode={pg_sslmode}"
    )
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------
# CORS - permissive for your frontend
# ----------------
CORS(app, resources={r"/*": {"origins": "*"}})

# ----------------
# Models
# ----------------
class FirmImage(db.Model):
    __tablename__ = "firm_images"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    file_path = db.Column(db.String(1024), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class UserCV(db.Model):
    __tablename__ = "user_cvs"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(1024), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class UserIDDoc(db.Model):
    __tablename__ = "user_id_docs"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(1024), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Assignment(db.Model):
    __tablename__ = "assignments"
    id = db.Column(db.String(50), primary_key=True)  # Firebase ID
    lecture_id = db.Column(db.String(50), index=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    deadline_iso = db.Column(db.String(50))
    status = db.Column(db.String(20), default="open")
    file_filename = db.Column(db.String(255))
    file_data = db.Column(db.LargeBinary)  # optional, not used
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Submission(db.Model):
    __tablename__ = "submissions"
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.String(50), nullable=False, index=True)  # Firebase ID
    user_code = db.Column(db.String(50), nullable=False, index=True)
    filename = db.Column(db.String(255))
    file_path = db.Column(db.String(1024))
    description = db.Column(db.Text)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# Create tables
with app.app_context():
    db.create_all()
    app.logger.debug("Database initialized; UPLOAD_DIR=%s", app.config['UPLOAD_DIR'])

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

def user_upload_folder(user_code):
    folder = os.path.join(app.config['UPLOAD_DIR'], str(user_code))
    os.makedirs(folder, exist_ok=True)
    return folder

def save_file_to_disk(file_obj, user_code, role_hint=None):
    filename = safe_filename(file_obj)
    if not filename:
        filename = "uploaded_file"
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    prefix = (role_hint + "_") if role_hint else ""
    stored_name = f"{prefix}{timestamp}_{filename}"
    folder = user_upload_folder(user_code)
    full_path = os.path.join(folder, stored_name)
    file_obj.save(full_path)
    rel_path = os.path.relpath(full_path, app.config['UPLOAD_DIR'])
    return stored_name, rel_path

def make_file_url_from_relpath(relpath):
    return f"/serve-document-by-path/{relpath}"

# ----------------
# Error handlers
# ----------------
@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    return jsonify({"error": "File too large. Max size is 50 MB."}), 413

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    return jsonify({"error": "Internal server error"}), 500

# ----------------
# Basic routes
# ----------------
@app.route("/")
def index():
    return jsonify({"message": "Flask API is live!"})

@app.route("/health")
def health_check():
    try:
        db.session.execute("SELECT 1")
        return jsonify({"status": "healthy", "db": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# ----------------
# Assignment file upload
# ----------------

@app.route("/api/assignments/<assignment_id>/submissions/<user_code>", methods=["PUT", "OPTIONS"])
@cross_origin()
def replace_submission(assignment_id, user_code):
    if request.method == "OPTIONS":
        return "", 200

    file_obj = request.files.get("file")
    if not file_obj or not file_obj.filename:
        return jsonify({"error": "No file provided"}), 400

    try:
        # Save file
        saved_name, saved_rel = save_file_to_disk(file_obj, user_code, role_hint="submission")

        # Find existing submission
        submission = Submission.query.filter_by(assignment_id=assignment_id, user_code=user_code).first()
        if submission:
            submission.filename = saved_name
            submission.file_path = saved_rel
            submission.updated_at = datetime.utcnow()
        else:
            submission = Submission(
                assignment_id=assignment_id,
                user_code=user_code,
                filename=saved_name,
                file_path=saved_rel
            )
            db.session.add(submission)

        db.session.commit()

        return jsonify({
            "message": "Submission replaced",
            "submission_id": submission.id,
            "file_url": make_file_url_from_relpath(saved_rel)
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/upload-assignment-file", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_assignment_file():
    if request.method == "OPTIONS":
        return "", 200

    lecture_id = request.form.get("lecture_id")
    assignment_id = request.form.get("assignment_id")  # optional
    file_obj = request.files.get("file")

    if not lecture_id:
        return jsonify({"error": "Missing lecture_id"}), 400

    # Generate backend assignment ID if not provided
    if not assignment_id:
        assignment_id = str(uuid.uuid4())

    try:
        saved_name, saved_rel = None, None
        if file_obj and file_obj.filename:
            saved_name, saved_rel = save_file_to_disk(file_obj, lecture_id, role_hint="assignment")

        # Store in DB
        assignment = Assignment(
            id=assignment_id,
            lecture_id=lecture_id,
            title=request.form.get("title", ""),
            description=request.form.get("description", ""),
            deadline_iso=request.form.get("deadline_iso", ""),
            file_filename=saved_name
        )
        db.session.merge(assignment)
        db.session.commit()

        return jsonify({
            "message": "Assignment created",
            "assignment_id": assignment_id,
            "file_url": make_file_url_from_relpath(saved_rel) if saved_rel else None
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# ----------------
# Submissions (students)
# ----------------
@app.route("/submit/<assignment_id>", methods=["POST", "OPTIONS"])
@cross_origin()
def submit_assignment(assignment_id):
    if request.method == "OPTIONS":
        return "", 200
    user_code = request.form.get("user_code")
    file_obj = request.files.get("file")
    description = request.form.get("description")
    if not user_code or not file_obj:
        return jsonify({"error": "Missing user_code or file"}), 400
    if not file_obj.filename:
        return jsonify({"error": "Empty filename provided"}), 400
    try:
        saved_name, saved_rel = save_file_to_disk(file_obj, user_code, role_hint="submission")
        submission = Submission(
            assignment_id=assignment_id,
            user_code=user_code,
            filename=saved_name,
            file_path=saved_rel,
            description=description
        )
        db.session.add(submission)
        db.session.commit()
        return jsonify({
            "message": "Submission saved",
            "submission_id": submission.id,
            "file_url": make_file_url_from_relpath(submission.file_path)
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/submissions/<assignment_id>", methods=["GET"])
def list_submissions_for_assignment(assignment_id):
    subs = Submission.query.filter_by(assignment_id=assignment_id).order_by(Submission.updated_at.desc()).all()
    result = [{
        "id": s.id,
        "user_code": s.user_code,
        "filename": s.filename,
        "file_url": make_file_url_from_relpath(s.file_path) if s.file_path else None,
        "description": s.description,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None
    } for s in subs]
    return jsonify(result)

# ----------------
# Serve document
# ----------------
@app.route("/serve-document-by-path/<path:relpath>", methods=["GET"])
def serve_document_by_path(relpath):
    safe_rel = os.path.normpath(relpath)
    if safe_rel.startswith("..") or os.path.isabs(safe_rel):
        return jsonify({"error": "Invalid path"}), 400
    abs_path = os.path.join(app.config['UPLOAD_DIR'], safe_rel)
    if not os.path.exists(abs_path):
        return jsonify({"error": "File not found"}), 404
    filename = os.path.basename(abs_path)
    return send_file(abs_path, mimetype=guess_mimetype(filename), as_attachment=True, download_name=filename)


@app.route("/api/assignments", methods=["POST", "OPTIONS"])
@cross_origin()
def create_assignment_api():
    if request.method == "OPTIONS":
        return "", 200

    lecture_id = request.form.get("lecture_id")
    assignment_id = request.form.get("assignment_id")
    title = request.form.get("title", "")
    description = request.form.get("description", "")
    deadline_iso = request.form.get("deadline_iso", "")
    file_obj = request.files.get("file")

    if not lecture_id or not assignment_id:
        return jsonify({"error": "Missing lecture_id or assignment_id"}), 400

    try:
        saved_name, saved_rel = (None, None)
        if file_obj:
            saved_name, saved_rel = save_file_to_disk(file_obj, lecture_id, role_hint="assignment")

        assignment = Assignment(
            id=assignment_id,
            lecture_id=lecture_id,
            title=title,
            description=description,
            deadline_iso=deadline_iso,
            file_filename=saved_name
        )
        db.session.merge(assignment)
        db.session.commit()

        return jsonify({
            "message": "Assignment created",
            "assignment_id": assignment.id,
            "file_url": make_file_url_from_relpath(saved_rel) if saved_rel else None
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# ----------------
# Run
# ----------------
if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true")
    app.debug = debug
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug)
