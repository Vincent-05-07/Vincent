# app.py  (full updated Flask app — improved /documents handling, logging, error handlers)
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
from werkzeug.exceptions import RequestEntityTooLarge

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
# Max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max

# Upload directory (can set via env)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(BASE_DIR, "uploads", "documents"))
os.makedirs(DEFAULT_UPLOAD_DIR, exist_ok=True)
app.config['UPLOAD_DIR'] = DEFAULT_UPLOAD_DIR

# PostgreSQL config from env or fallback to SQLite
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
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'  # local fallback

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------
# CORS (permissive)
# ----------------
# Frontend now sends no credentials; keep origins="*" for simplicity.
CORS(
    app,
    supports_credentials=True,
    origins="*",
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"]
)

# ----------------
# Models
# ----------------
class FirmImage(db.Model):
    __tablename__ = "firm_images"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    image_data = db.Column(db.LargeBinary)  # legacy / optional
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), index=True, nullable=False)
    # file metadata stored on disk; DB stores filenames and relative paths
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
    file_data = db.Column(db.LargeBinary)  # still binary for assignments (you can migrate later)
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
    """
    Save uploaded file object to disk under user's folder.
    role_hint used only for filename prefix. Returns (stored_name, relative_path).
    """
    filename = safe_filename(file_obj)
    if not filename:
        # fallback name to avoid empty filenames
        filename = "uploaded_file"
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    prefix = (role_hint + "_") if role_hint else ""
    stored_name = f"{prefix}{timestamp}_{filename}"
    folder = user_upload_folder(user_code)
    full_path = os.path.join(folder, stored_name)
    app.logger.debug("Saving uploaded file to %s", full_path)
    try:
        # some FileStorage objects may not have stream or seek allowance; ignore seek errors
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
    # relpath is relative to UPLOAD_DIR; create API URL to serve it
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
    tb = traceback.format_exc()
    app.logger.error("Unhandled exception: %s\n%s", e, tb)
    if app.debug:
        return jsonify({"error": str(e), "traceback": tb}), 500
    return jsonify({"error": "Internal server error"}), 500

# ----------------
# FIRM IMAGES (unchanged)
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

@app.route("/get-images/<user_code>", methods=["GET"])
def get_images(user_code):
    try:
        rows = FirmImage.query.filter_by(user_code=user_code).all()
        urls = [f"/serve-image/{r.id}" for r in rows]
        return jsonify({"user_code": user_code, "file_paths": urls}), 200
    except Exception as e:
        app.logger.error("get_images error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/serve-image/<int:image_id>", methods=["GET"])
def serve_image(image_id):
    img = FirmImage.query.get(image_id)
    if not img:
        return jsonify({"error": "Image not found"}), 404
    return send_file(BytesIO(img.image_data), mimetype=guess_mimetype(img.filename),
                     as_attachment=False, download_name=img.filename)

# ----------------
# DOCUMENTS (CV & ID) - disk-backed storage, creates new row for single-file uploads
# ----------------
@app.route("/documents", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_documents():
    """
    Supports:
    - Both files: 'cvFile' and 'idFile' -> saves both, creates new DB row
    - Single file: 'file' with form 'file_type'='cv'|'id' -> saves and creates a new DB row
    - Single file: 'file' without file_type -> server will attempt to infer by mime/type (image -> id, doc/pdf -> cv)
    """
    if request.method == "OPTIONS":
        return "", 200

    try:
        app.logger.info("Documents upload request: form=%s files=%s", dict(request.form), list(request.files.keys()))
    except Exception:
        app.logger.info("Documents upload request (couldn't stringify form/files)")

    user_code = request.form.get("user_code")
    if not user_code:
        app.logger.warning("Missing user_code in request.form")
        return jsonify({"error": "user_code is required"}), 400

    # Mode 1: both files provided
    if "cvFile" in request.files and "idFile" in request.files:
        try:
            cv = request.files["cvFile"]
            idf = request.files["idFile"]

            if not cv.filename or not idf.filename:
                return jsonify({"error": "Empty filename provided"}), 400

            cv_name, cv_rel = save_file_to_disk(cv, user_code, role_hint="cv")
            id_name, id_rel = save_file_to_disk(idf, user_code, role_hint="id")

            doc = Document(
                user_code=user_code,
                cv_filename=cv_name,
                cv_path=cv_rel,
                id_filename=id_name,
                id_path=id_rel
            )
            db.session.add(doc)
            db.session.commit()

            return jsonify({
                "message": "Both documents uploaded",
                "id": doc.id,
                "cv_url": make_file_url_from_relpath(doc.cv_path),
                "id_url": make_file_url_from_relpath(doc.id_path)
            }), 201

        except Exception as e:
            db.session.rollback()
            app.logger.error("Error uploading both documents: %s\n%s", e, traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    # Mode 2: single upload (generic 'file')
    if "file" in request.files:
        file_obj = request.files["file"]
        file_type = (request.form.get("file_type") or request.form.get("type") or "").lower().strip()

        # Try to infer if no explicit file_type
        if not file_type:
            mim = guess_mimetype(safe_filename(file_obj))
            file_type = "id" if mim.startswith("image/") else "cv"

        try:
            if not file_obj.filename:
                return jsonify({"error": "Empty filename provided"}), 400

            role_hint = "cv" if file_type == "cv" else "id"
            saved_name, saved_rel = save_file_to_disk(file_obj, user_code, role_hint=role_hint)

            # Create a new document row (you said creating two rows for separate uploads is acceptable)
            doc = Document(user_code=user_code)
            if file_type == "cv":
                doc.cv_filename = saved_name
                doc.cv_path = saved_rel
            else:
                doc.id_filename = saved_name
                doc.id_path = saved_rel

            db.session.add(doc)
            db.session.commit()

            return jsonify({
                "message": f"{file_type.upper()} uploaded",
                "id": doc.id,
                "file_role": file_type,
                "file_url": make_file_url_from_relpath(saved_rel)
            }), 201
        except Exception as e:
            db.session.rollback()
            app.logger.error("Error uploading single file: %s\n%s", e, traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    # If reached here, no files found
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
    """
    Legacy endpoint: serves the requested file for a Document record.
    filetype: 'cv' or 'id'
    """
    doc = Document.query.get(doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404

    if filetype == "cv":
        if not doc.cv_path:
            return jsonify({"error": "CV not found"}), 404
        abs_path = os.path.join(app.config['UPLOAD_DIR'], doc.cv_path)
        if not os.path.exists(abs_path):
            return jsonify({"error": "CV file missing on server"}), 404
        return send_file(abs_path, mimetype=guess_mimetype(doc.cv_filename), as_attachment=True, download_name=doc.cv_filename)

    elif filetype == "id":
        if not doc.id_path:
            return jsonify({"error": "ID not found"}), 404
        abs_path = os.path.join(app.config['UPLOAD_DIR'], doc.id_path)
        if not os.path.exists(abs_path):
            return jsonify({"error": "ID file missing on server"}), 404
        return send_file(abs_path, mimetype=guess_mimetype(doc.id_filename), as_attachment=True, download_name=doc.id_filename)
    else:
        return jsonify({"error": "Invalid filetype"}), 400

@app.route("/serve-document-by-path/<path:relpath>", methods=["GET"])
def serve_document_by_path(relpath):
    """
    Serve a file by its relative path under UPLOAD_DIR.
    """
    safe_rel = os.path.normpath(relpath)
    if safe_rel.startswith(".."):
        return jsonify({"error": "Invalid path"}), 400
    abs_path = os.path.join(app.config['UPLOAD_DIR'], safe_rel)
    if not os.path.exists(abs_path):
        return jsonify({"error": "File not found"}), 404
    filename = os.path.basename(abs_path)
    return send_file(abs_path, mimetype=guess_mimetype(filename), as_attachment=True, download_name=filename)

# ----------------
# ASSIGNMENTS (unchanged)
# ----------------
@app.route("/api/assignments", methods=["POST", "OPTIONS"])
@cross_origin()
def create_assignment():
    if request.method == "OPTIONS":
        return "", 200
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
        assignment_id = request.form.get("id") or str(int(datetime.utcnow().timestamp()*1000))
        assignment = Assignment(
            id=assignment_id,
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
        app.logger.error("create_assignment error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/api/assignments", methods=["GET"])
def list_assignments():
    lecture_id = request.args.get("lecture_id")
    query = Assignment.query
    if lecture_id:
        query = query.filter_by(lecture_id=lecture_id)
    assignments = query.all()
    result = []
    for a in assignments:
        result.append({
            "id": a.id,
            "lecture_id": a.lecture_id,
            "title": a.title,
            "description": a.description,
            "deadline_iso": a.deadline_iso,
            "status": a.status,
            "file_url": f"/serve-assignment-file/{a.id}" if a.file_filename else None,
            "created_at": a.created_at.isoformat() if a.created_at else None
        })
    return jsonify({"assignments": result})

@app.route("/serve-assignment-file/<assignment_id>", methods=["GET"])
def serve_assignment_file(assignment_id):
    a = Assignment.query.get(assignment_id)
    if not a or not a.file_data:
        return jsonify({"error": "File not found"}), 404
    return send_file(BytesIO(a.file_data), mimetype=guess_mimetype(a.file_filename),
                     as_attachment=True, download_name=a.file_filename)

# ----------------
# SUBMISSIONS (unchanged)
# ----------------
@app.route("/api/assignments/<assignment_id>/submissions", methods=["PUT", "OPTIONS"])
@cross_origin()
def update_submission(assignment_id):
    if request.method == "OPTIONS":
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
        return jsonify({"message": "Submission updated", "id": sub.id, "updated_at": sub.updated_at.isoformat(), "file_url": file_url}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error("update_submission error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/api/assignments/<assignment_id>/submissions", methods=["GET"])
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

@app.route("/api/assignments/<assignment_id>/submissions", methods=["DELETE"])
def delete_submission(assignment_id):
    user_code = request.args.get("user_code")
    if not user_code:
        return jsonify({"error": "user_code required"}), 400
    sub = Submission.query.filter_by(assignment_id=assignment_id, user_code=user_code).first()
    if not sub:
        return jsonify({"error": "Submission not found"}), 404
    try:
        db.session.delete(sub)
        db.session.commit()
        return jsonify({"message": f"Submission deleted for user {user_code}"}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error("delete_submission error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

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
    app.debug = debug
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug)
