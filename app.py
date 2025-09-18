# app.py  (refactored: separate CV/ID tables, no binary image storage, separate upload endpoints)
import os
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
# CORS - permissive for your frontend (no credentials used)
# ----------------
CORS(app, resources={r"/*": {"origins": "*"}})

# ----------------
# Models
# ----------------
class FirmImage(db.Model):
    __tablename__ = "firm_images"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    file_path = db.Column(db.String(1024), nullable=False)  # relative path under UPLOAD_DIR
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
    # Keep assignment id as a string (Firebase may provide logical ids);
    # This model is optional if you're moving assignments fully to Firebase.
    id = db.Column(db.String(50), primary_key=True)
    lecture_id = db.Column(db.String(50), index=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    deadline_iso = db.Column(db.String(50))
    status = db.Column(db.String(20), default="open")
    file_filename = db.Column(db.String(255))
    file_data = db.Column(db.LargeBinary)  # <-- you can remove this if you won't store assignment file blobs
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Submission(db.Model):
    __tablename__ = "submissions"
    id = db.Column(db.Integer, primary_key=True)
    # assignment_id is plain string (no FK). You said you'd store assignment metadata in Firebase.
    assignment_id = db.Column(db.String(50), nullable=False, index=True)
    user_code = db.Column(db.String(50), nullable=False, index=True)
    filename = db.Column(db.String(255))
    file_path = db.Column(db.String(1024))  # store location on disk
    description = db.Column(db.Text)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# Create tables if not exist
with app.app_context():
    db.create_all()
    app.logger.debug("Database initialized; UPLOAD_DIR=%s", app.config['UPLOAD_DIR'])
    if not os.access(app.config['UPLOAD_DIR'], os.W_OK):
        app.logger.warning("UPLOAD_DIR %s may not be writable by the process", app.config['UPLOAD_DIR'])

# ----------------
# Helpers
# ----------------
def safe_filename(file_obj):
    if not file_obj:
        return ""
    # file_obj could be a werkzeug FileStorage or a string
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
    """
    Saves the uploaded file to disk under UPLOAD_DIR/<user_code>/<role_hint>_<timestamp>_<filename>
    Returns (stored_name, rel_path) where rel_path is relative to UPLOAD_DIR.
    """
    filename = safe_filename(file_obj)
    if not filename:
        filename = "uploaded_file"
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    prefix = (role_hint + "_") if role_hint else ""
    stored_name = f"{prefix}{timestamp}_{filename}"
    folder = user_upload_folder(user_code)
    full_path = os.path.join(folder, stored_name)
    app.logger.debug("Saving uploaded file to %s", full_path)
    try:
        try:
            # sometimes FileStorage has .stream
            file_obj.stream.seek(0)
        except Exception:
            app.logger.debug("file_obj.stream.seek not supported; continuing")
        file_obj.save(full_path)
    except Exception as e:
        app.logger.error("Failed to save uploaded file to disk: %s", e)
        raise
    rel_path = os.path.relpath(full_path, app.config['UPLOAD_DIR'])
    return stored_name, rel_path

def make_file_url_from_relpath(relpath):
    # The path parameter will be URL-encoded by the client; keep route consistent
    return f"/serve-document-by-path/{relpath}"

# ----------------
# Error handlers
# ----------------
@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    app.logger.error("RequestEntityTooLarge: %s", e)
    return jsonify({"error": "File too large. Max size is 50 MB."}), 413

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    # If this is an HTTPException (404, 400, etc.), return its native status & message
    if isinstance(e, HTTPException):
        app.logger.debug("HTTPException handled: code=%s description=%s", e.code, e.description)
        return jsonify({"error": e.description}), e.code
    # Otherwise treat as 500
    tb = traceback.format_exc()
    app.logger.error("Unhandled exception: %s\n%s", e, tb)
    if app.debug:
        return jsonify({"error": str(e), "traceback": tb}), 500
    return jsonify({"error": "Internal server error"}), 500

# ----------------
# Basic routes
# ----------------
@app.route("/")
def index():
    return jsonify({"message": "Flask API (Postgres/Neon) is live!"})

@app.route("/health")
def health_check():
    try:
        db.session.execute("SELECT 1")
        return jsonify({"status": "healthy", "db": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# ----------------
# Images endpoint (store path only, not binary in DB)
# ----------------
@app.route("/upload-images", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_images():
    if request.method == "OPTIONS":
        return "", 200
    user_code = request.form.get("user_code")
    images = request.files.getlist("images")
    if not user_code or not images:
        return jsonify({"error": "Missing user_code or images"}), 400
    created = []
    try:
        for idx, image_file in enumerate(images, start=1):
            filename = safe_filename(image_file)
            ext = os.path.splitext(filename)[1] or ".jpg"
            filename_with_index = f"image_{idx}{ext}"
            # Save to disk with role hint 'firmimg'
            saved_name, rel_path = save_file_to_disk(image_file, user_code, role_hint="firmimg")
            # Store DB record with relative path
            file_path = os.path.join("wil-firm-pics", str(user_code), saved_name)
            # Normalize relative path under UPLOAD_DIR
            # Note: save_file_to_disk returns rel_path relative to UPLOAD_DIR
            img = FirmImage(user_code=user_code, file_path=rel_path, filename=saved_name)
            db.session.add(img)
            db.session.flush()
            created.append({"id": img.id, "file_path": make_file_url_from_relpath(img.file_path)})
        db.session.commit()
        return jsonify({"message": f"{len(created)} images saved", "file_paths": created}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error("upload_images error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ----------------
# CV / ID upload endpoints (separate tables)
# ----------------
@app.route("/upload-cv", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_cv():
    if request.method == "OPTIONS":
        return "", 200
    user_code = request.form.get("user_code")
    file_obj = request.files.get("cvFile") or request.files.get("file")
    if not user_code or not file_obj:
        return jsonify({"error": "Missing user_code or cvFile"}), 400
    if not file_obj.filename:
        return jsonify({"error": "Empty filename provided"}), 400
    try:
        saved_name, saved_rel = save_file_to_disk(file_obj, user_code, role_hint="cv")
        cv = UserCV(user_code=user_code, filename=saved_name, file_path=saved_rel)
        db.session.add(cv)
        db.session.commit()
        return jsonify({
            "message": "CV uploaded",
            "id": cv.id,
            "file_url": make_file_url_from_relpath(cv.file_path)
        }), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error("upload_cv error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/upload-id", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_id():
    if request.method == "OPTIONS":
        return "", 200
    user_code = request.form.get("user_code")
    file_obj = request.files.get("idFile") or request.files.get("file")
    if not user_code or not file_obj:
        return jsonify({"error": "Missing user_code or idFile"}), 400
    if not file_obj.filename:
        return jsonify({"error": "Empty filename provided"}), 400
    try:
        saved_name, saved_rel = save_file_to_disk(file_obj, user_code, role_hint="id")
        iddoc = UserIDDoc(user_code=user_code, filename=saved_name, file_path=saved_rel)
        db.session.add(iddoc)
        db.session.commit()
        return jsonify({
            "message": "ID uploaded",
            "id": iddoc.id,
            "file_url": make_file_url_from_relpath(iddoc.file_path)
        }), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error("upload_id error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ----------------
# List CVs and IDs by user
# ----------------
@app.route("/user-cvs/<user_code>", methods=["GET"])
def list_user_cvs(user_code):
    try:
        cvs = UserCV.query.filter_by(user_code=user_code).order_by(UserCV.uploaded_at.desc()).all()
        result = [{
            "id": c.id,
            "filename": c.filename,
            "file_url": make_file_url_from_relpath(c.file_path),
            "uploaded_at": c.uploaded_at.isoformat() if c.uploaded_at else None
        } for c in cvs]
        return jsonify(result)
    except Exception as e:
        app.logger.error("list_user_cvs error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/user-ids/<user_code>", methods=["GET"])
def list_user_ids(user_code):
    try:
        ids = UserIDDoc.query.filter_by(user_code=user_code).order_by(UserIDDoc.uploaded_at.desc()).all()
        result = [{
            "id": i.id,
            "filename": i.filename,
            "file_url": make_file_url_from_relpath(i.file_path),
            "uploaded_at": i.uploaded_at.isoformat() if i.uploaded_at else None
        } for i in ids]
        return jsonify(result)
    except Exception as e:
        app.logger.error("list_user_ids error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ----------------
# Submissions endpoint (store path only)
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
        # Note: you can write metadata mapping (submission -> assignment) to Firebase here.
        return jsonify({
            "message": "Submission saved",
            "submission_id": submission.id,
            "file_url": make_file_url_from_relpath(submission.file_path)
        }), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error("submit_assignment error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/submissions/<assignment_id>", methods=["GET"])
def list_submissions_for_assignment(assignment_id):
    try:
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
    except Exception as e:
        app.logger.error("list_submissions_for_assignment error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ----------------
# Serve document by relative path under UPLOAD_DIR
# ----------------
@app.route("/serve-document-by-path/<path:relpath>", methods=["GET"])
def serve_document_by_path(relpath):
    # Normalize and prevent path traversal
    safe_rel = os.path.normpath(relpath)
    # Reject attempts to escape upload dir
    if safe_rel.startswith("..") or os.path.isabs(safe_rel):
        return jsonify({"error": "Invalid path"}), 400
    abs_path = os.path.join(app.config['UPLOAD_DIR'], safe_rel)
    if not os.path.exists(abs_path):
        return jsonify({"error": "File not found"}), 404
    filename = os.path.basename(abs_path)
    return send_file(abs_path, mimetype=guess_mimetype(filename), as_attachment=True, download_name=filename)

# ----------------
# Optional: cleanup endpoints or utilities
# ----------------
@app.route("/delete-user-file", methods=["POST"])
@cross_origin()
def delete_user_file():
    """
    Example helper: delete a stored file by specifying table and id.
    Body (json): { "table": "cv"|"id"|"submission"|"image", "record_id": <int> }
    NOTE: This is a utility and should be protected in production.
    """
    data = request.get_json() or {}
    table = data.get("table")
    record_id = data.get("record_id")
    if not table or not record_id:
        return jsonify({"error": "Missing table or record_id"}), 400
    try:
        if table == "cv":
            rec = UserCV.query.get(record_id)
        elif table == "id":
            rec = UserIDDoc.query.get(record_id)
        elif table == "submission":
            rec = Submission.query.get(record_id)
        elif table == "image":
            rec = FirmImage.query.get(record_id)
        else:
            return jsonify({"error": "Invalid table"}), 400
        if not rec:
            return jsonify({"error": "Record not found"}), 404
        # remove file from disk if path present
        rel = getattr(rec, "file_path", None)
        if rel:
            abs_path = os.path.join(app.config['UPLOAD_DIR'], rel)
            try:
                if os.path.exists(abs_path):
                    os.remove(abs_path)
            except Exception as e:
                app.logger.warning("Could not remove file %s: %s", abs_path, e)
        db.session.delete(rec)
        db.session.commit()
        return jsonify({"message": "Deleted"}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error("delete_user_file error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# Run
if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true")
    app.debug = debug
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug)
