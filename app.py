# app.py  (fixed: proper CORS usage, HTTPException handling, logging)
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
# Use resources dict and origins "*" (keeps it permissive)
CORS(app, resources={r"/*": {"origins": "*"}})

# ----------------
# Models
# ----------------
class FirmImage(db.Model):
    __tablename__ = "firm_images"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    image_data = db.Column(db.LargeBinary)  # legacy/optional
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    cv_filename = db.Column(db.String(255), nullable=True)
    cv_path = db.Column(db.String(1024), nullable=True)
    id_filename = db.Column(db.String(255), nullable=True)
    id_path = db.Column(db.String(1024), nullable=True)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Assignment(db.Model):
    __tablename__ = "assignments"
    id = db.Column(db.String(50), primary_key=True)
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
    assignment_id = db.Column(db.String(50), nullable=False, index=True)
    user_code = db.Column(db.String(50), nullable=False, index=True)
    filename = db.Column(db.String(255))
    file_data = db.Column(db.LargeBinary)
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
    app.logger.debug("Saving uploaded file to %s", full_path)
    try:
        try:
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
# upload-images (same as before)
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
            file_path = f"wil-firm-pics/{user_code}/{filename_with_index}"
            data = image_file.read()
            img = FirmImage(user_code=user_code, file_path=file_path, filename=filename_with_index, image_data=data)
            db.session.add(img)
            db.session.flush()
            created.append({"id": img.id, "file_path": file_path})
        db.session.commit()
        urls = [f"/serve-image/{c['id']}" for c in created]
        return jsonify({"message": f"{len(created)} images saved", "file_paths": urls}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error("upload_images error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ----------------
# DOCUMENTS endpoints (disk-backed)
# ----------------
@app.route("/documents", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_documents():
    if request.method == "OPTIONS":
        return "", 200

    try:
        app.logger.info("Documents upload request: form=%s files=%s", dict(request.form), list(request.files.keys()))
    except Exception:
        app.logger.info("Documents upload request (couldn't stringify form/files)")

    user_code = request.form.get("user_code")
    if not user_code:
        return jsonify({"error": "user_code is required"}), 400

    # both files
    if "cvFile" in request.files and "idFile" in request.files:
        try:
            cv = request.files["cvFile"]; idf = request.files["idFile"]
            if not cv.filename or not idf.filename:
                return jsonify({"error": "Empty filename provided"}), 400
            cv_name, cv_rel = save_file_to_disk(cv, user_code, role_hint="cv")
            id_name, id_rel = save_file_to_disk(idf, user_code, role_hint="id")
            doc = Document(user_code=user_code, cv_filename=cv_name, cv_path=cv_rel, id_filename=id_name, id_path=id_rel)
            db.session.add(doc); db.session.commit()
            return jsonify({"message": "Both documents uploaded", "id": doc.id, "cv_url": make_file_url_from_relpath(doc.cv_path), "id_url": make_file_url_from_relpath(doc.id_path)}), 201
        except Exception as e:
            db.session.rollback()
            app.logger.error("Error uploading both documents: %s\n%s", e, traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    # single generic file
    if "file" in request.files:
        file_obj = request.files["file"]
        file_type = (request.form.get("file_type") or request.form.get("type") or "").lower().strip()
        if not file_type:
            mim = guess_mimetype(safe_filename(file_obj))
            file_type = "id" if mim.startswith("image/") else "cv"
        try:
            if not file_obj.filename:
                return jsonify({"error": "Empty filename provided"}), 400
            role_hint = "cv" if file_type == "cv" else "id"
            saved_name, saved_rel = save_file_to_disk(file_obj, user_code, role_hint=role_hint)
            # create a new row (your preference was OK to create two rows)
            doc = Document(user_code=user_code)
            if file_type == "cv":
                doc.cv_filename = saved_name; doc.cv_path = saved_rel
            else:
                doc.id_filename = saved_name; doc.id_path = saved_rel
            db.session.add(doc); db.session.commit()
            return jsonify({"message": f"{file_type.upper()} uploaded", "id": doc.id, "file_role": file_type, "file_url": make_file_url_from_relpath(saved_rel)}), 201
        except Exception as e:
            db.session.rollback()
            app.logger.error("Error uploading single file: %s\n%s", e, traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "No files provided. Expect cvFile+idFile or single 'file'."}), 400

@app.route("/documents/<user_code>", methods=["GET"])
def list_documents(user_code):
    try:
        docs = Document.query.filter_by(user_code=user_code).all()
        result = []
        for d in docs:
            result.append({
                "id": d.id,
                "cv_filename": d.cv_filename,
                "cv_url": make_file_url_from_relpath(d.cv_path) if d.cv_path else None,
                "id_filename": d.id_filename,
                "id_url": make_file_url_from_relpath(d.id_path) if d.id_path else None,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None
            })
        return jsonify(result)
    except Exception as e:
        app.logger.error("list_documents error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/serve-document/<int:doc_id>/<string:filetype>", methods=["GET"])
def serve_document(doc_id, filetype):
    doc = Document.query.get(doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    if filetype == "cv":
        if not doc.cv_path: return jsonify({"error": "CV not found"}), 404
        abs_path = os.path.join(app.config['UPLOAD_DIR'], doc.cv_path)
        if not os.path.exists(abs_path): return jsonify({"error": "CV file missing on server"}), 404
        return send_file(abs_path, mimetype=guess_mimetype(doc.cv_filename), as_attachment=True, download_name=doc.cv_filename)
    elif filetype == "id":
        if not doc.id_path: return jsonify({"error": "ID not found"}), 404
        abs_path = os.path.join(app.config['UPLOAD_DIR'], doc.id_path)
        if not os.path.exists(abs_path): return jsonify({"error": "ID file missing on server"}), 404
        return send_file(abs_path, mimetype=guess_mimetype(doc.id_filename), as_attachment=True, download_name=doc.id_filename)
    else:
        return jsonify({"error": "Invalid filetype"}), 400

@app.route("/serve-document-by-path/<path:relpath>", methods=["GET"])
def serve_document_by_path(relpath):
    safe_rel = os.path.normpath(relpath)
    if safe_rel.startswith(".."):
        return jsonify({"error": "Invalid path"}), 400
    abs_path = os.path.join(app.config['UPLOAD_DIR'], safe_rel)
    if not os.path.exists(abs_path):
        return jsonify({"error": "File not found"}), 404
    filename = os.path.basename(abs_path)
    return send_file(abs_path, mimetype=guess_mimetype(filename), as_attachment=True, download_name=filename)

# ... (assignments/submissions routes unchanged; omitted here for brevity, keep as before) ...

# Run
if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true")
    app.debug = debug
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug)
