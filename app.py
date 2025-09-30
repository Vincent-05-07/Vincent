import os
from datetime import datetime
from io import BytesIO
from mimetypes import guess_type

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

import os
import json
import traceback

import mimetypes


#the imports for images
import psycopg2
#import for images

from flask import Flask, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError

from werkzeug.utils import secure_filename
from sqlalchemy import func
from flask_cors import CORS, cross_origin

# ----------------
# Flask App
# ----------------
app = Flask(__name__)
CORS(app, supports_credentials=True, origins="*")


# ----------------
# Config
# ----------------
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max

def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT", "5432"),
        sslmode=os.getenv("PGSSLMODE", "require")
    )
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
# CORS
# ----------------
# Use a more robust CORS configuration that explicitly supports credentials
# and sets allowed methods.
CORS(
    app,
    supports_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"]
)

# ----------------
# Models
# ----------------
# --- Model: matches your CREATE TABLE firm_proofs SQL ---

class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    file_name = db.Column(db.String(255), nullable=True)   # store original filename
    file_data = db.Column(db.LargeBinary, nullable=True)   # store actual file bytes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "file_name": self.file_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at
            # ⚠️ don't include file_data here (too large for JSON)
        }


class FirmProof(db.Model):
    __tablename__ = "firm_proofs"

    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), nullable=False, unique=True, index=True)

    # original filename provided by client (human-friendly)
    original_filename = db.Column(db.String(255), nullable=True)

    # logical/file path or sanitized filename (used by your serving logic)
    file_path = db.Column(db.String(255), nullable=False)

    # raw bytes stored in DB
    file_data = db.Column(db.LargeBinary, nullable=False)

    # detected or provided mime type
    mime_type = db.Column(db.String(100), nullable=True)

    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def to_meta(self, backend_base=None):
        """
        Helper to return a serializable metadata dict.
        If backend_base is provided, will construct full file_url from file id.
        """
        file_url = f"/serve-firm-proof/{self.id}"
        if backend_base:
            file_url = backend_base.rstrip("/") + file_url
        return {
            "id": self.id,
            "user_code": self.user_code,
            "original_filename": self.original_filename,
            "filename": self.file_path,
            "mime_type": self.mime_type,
            "file_url": file_url,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None
        }

    
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

class UserCV(db.Model):
    __tablename__ = "user_cv"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(255))
    file_path = db.Column(db.Text)
    file_data = db.Column(db.LargeBinary)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class UserIDDoc(db.Model):
    __tablename__ = "user_id_doc"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(255))
    file_path = db.Column(db.Text)
    file_data = db.Column(db.LargeBinary)
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
# Root + Health
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
# FIRM IMAGES
# ----------------



# ------------------ UserCV CRUD ------------------

# Create / Upload CV


# Read / Download CV
@app.route("/serve-cv/<int:cv_id>", methods=["GET"])
def serve_cv(cv_id):
    doc = UserCV.query.get(cv_id)
    if not doc:
        return jsonify({"error": "CV not found"}), 404
    return send_file(BytesIO(doc.file_data), mimetype=guess_mimetype(doc.filename),
                     as_attachment=True, download_name=doc.filename)

# Update CV
@app.route("/cv/<int:cv_id>", methods=["PUT", "OPTIONS"])
@cross_origin()
def update_cv(cv_id):
    if request.method == "OPTIONS":
        return "", 200  # Preflight response

    doc = UserCV.query.get(cv_id)
    if not doc:
        return jsonify({"error": "CV not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "Filename missing"}), 400

        doc.filename = secure_filename(file.filename)
        doc.file_data = file.read()
        db.session.commit()
        return jsonify({"message": "CV updated", "id": doc.id}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

# Delete CV
@app.route("/cv/<int:cv_id>", methods=["DELETE", "OPTIONS"])
@cross_origin()
def delete_cv(cv_id):
    if request.method == "OPTIONS":
        return "", 200  # Preflight response

    doc = UserCV.query.get(cv_id)
    if not doc:
        return jsonify({"error": "CV not found"}), 404

    try:
        db.session.delete(doc)
        db.session.commit()
        return jsonify({"message": "CV deleted"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Internal server error", "details": str(e)}), 500



# ------------------ UserIDDoc CRUD ------------------

import traceback
# ... keep your other imports and app/db setup ...

# Create / Upload CV (fixed)
@app.route("/cv", methods=["POST"])
def upload_cv():
    try:
        user_code = request.form.get("user_code")
        if not user_code:
            return jsonify({"error": "user_code is required"}), 400

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "Filename missing"}), 400

        filename = secure_filename(file.filename)
        cv = UserCV(user_code=user_code, filename=filename, file_data=file.read())
        db.session.add(cv)
        db.session.commit()
        return jsonify({"message": "CV uploaded", "id": cv.id}), 201

    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error uploading CV")
        # Return a safe error message; don't expose internals in production
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


# Create / Upload ID (fixed)
@app.route("/id-doc", methods=["POST"])
def upload_id_doc():
    try:
        user_code = request.form.get("user_code")
        if not user_code:
            return jsonify({"error": "user_code is required"}), 400

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "Filename missing"}), 400

        filename = secure_filename(file.filename)
        id_doc = UserIDDoc(user_code=user_code, filename=filename, file_data=file.read())
        db.session.add(id_doc)
        db.session.commit()
        return jsonify({"message": "ID uploaded", "id": id_doc.id}), 201

    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error uploading ID document")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

# Read / Download ID
@app.route("/serve-id/<int:id_id>", methods=["GET"])
def serve_id(id_id):
    doc = UserIDDoc.query.get(id_id)
    if not doc:
        return jsonify({"error": "ID not found"}), 404
    return send_file(BytesIO(doc.file_data), mimetype=guess_mimetype(doc.filename),
                     as_attachment=True, download_name=doc.filename)

# Update ID
@app.route("/id-doc/<int:id_id>", methods=["PUT", "OPTIONS"])
@cross_origin()
def update_id_doc(id_id):
    if request.method == "OPTIONS":
        return "", 200

    doc = UserIDDoc.query.get(id_id)
    if not doc:
        return jsonify({"error": "ID not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "Filename missing"}), 400

        doc.filename = secure_filename(file.filename)
        doc.file_data = file.read()
        db.session.commit()
        return jsonify({"message": "ID updated", "id": doc.id}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

@app.route("/view-submission/<int:submission_id>", methods=["GET"])
def view_submission(submission_id):
    """
    Serve a submission for inline viewing in the browser if supported.
    """
    sub = Submission.query.get(submission_id)
    if not sub or not sub.file_data:
        return jsonify({"error": "Submission not found"}), 404

    # Guess the MIME type
    mimetype = guess_mimetype(sub.filename)

    # Determine if the file can be viewed inline (browser-friendly)
    viewable_types = [
        "application/pdf",  # PDF
        "image/png", "image/jpeg", "image/jpg", "image/gif",  # Images
        "text/plain",  # Text
        "text/html"  # HTML
    ]
    as_attachment = mimetype not in viewable_types

    return send_file(
        BytesIO(sub.file_data),
        mimetype=mimetype,
        as_attachment=as_attachment,  # False for inline view
        download_name=sub.filename
    )

@app.route("/api/assignments/<assignment_id>/submissions/<int:submission_id>", methods=["DELETE", "OPTIONS"])
@cross_origin()
def delete_submission(assignment_id, submission_id):
    if request.method == "OPTIONS":
        return "", 200

    sub = Submission.query.get(submission_id)
    if not sub or sub.assignment_id != assignment_id:
        return jsonify({"error": "Submission not found"}), 404

    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404

    if assignment.status != "open":
        return jsonify({"error": "Cannot delete submission for a closed assignment"}), 400

    try:
        db.session.delete(sub)
        db.session.commit()
        return jsonify({"message": "Submission deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ----------------- View CV Inline -----------------
def guess_mimetype(filename):
    mimetype, _ = guess_type(filename)
    return mimetype or 'application/octet-stream'


# ----------------- View CV Inline -----------------
@app.route("/view-cv/<int:cv_id>", methods=["GET"])
def view_cv(cv_id):
    doc = UserCV.query.get(cv_id)
    if not doc:
        return jsonify({"error": "CV not found"}), 404

    mimetype = guess_mimetype(doc.filename)

    return send_file(
        BytesIO(doc.file_data),
        mimetype=mimetype,
        as_attachment=False,   # Inline view
        download_name=doc.filename
    )


# ----------------- View ID Inline -----------------
@app.route("/view-id/<int:id_id>", methods=["GET"])
def view_id(id_id):
    doc = UserIDDoc.query.get(id_id)
    if not doc:
        return jsonify({"error": "ID not found"}), 404

    mimetype = guess_mimetype(doc.filename)

    return send_file(
        BytesIO(doc.file_data),
        mimetype=mimetype,
        as_attachment=False,  # Inline view
        download_name=doc.filename
    )


# Delete ID
@app.route("/id-doc/<int:id_id>", methods=["DELETE", "OPTIONS"])
@cross_origin()
def delete_id_doc(id_id):
    if request.method == "OPTIONS":
        return "", 200

    doc = UserIDDoc.query.get(id_id)
    if not doc:
        return jsonify({"error": "ID not found"}), 404

    try:
        db.session.delete(doc)
        db.session.commit()
        return jsonify({"message": "ID deleted"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

# ----------------
# ASSIGNMENTS
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

from flask import url_for

@app.route("/api/assignments/<assignment_id>", methods=["PUT", "OPTIONS"])
@cross_origin()
def update_assignment(assignment_id):
    if request.method == "OPTIONS":
        return "", 200  # Preflight CORS

    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404

    # Metadata from form fields
    title = request.form.get("title")
    description = request.form.get("description")
    deadline_iso = request.form.get("deadline_iso")
    status = request.form.get("status")

    if title:
        assignment.title = title
    if description:
        assignment.description = description
    if deadline_iso:
        assignment.deadline_iso = deadline_iso
    if status:
        assignment.status = status

    # Handle file (optional)
    if "file" in request.files:
        file = request.files["file"]
        if file and file.filename.strip() != "":
            assignment.file_filename = secure_filename(file.filename)
            assignment.file_data = file.read()

    try:
        db.session.commit()
        file_url = f"/serve-assignment-file/{assignment.id}" if assignment.file_filename else None
        return jsonify({
            "message": "Assignment updated successfully",
            "id": assignment.id,
            "title": assignment.title,
            "description": assignment.description,
            "deadline_iso": assignment.deadline_iso,
            "status": assignment.status,
            "file_url": file_url
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Failed updating assignment")
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500


# ----------------
# SUBMISSIONS
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

@app.route("/api/assignments/<assignment_id>", methods=["DELETE", "OPTIONS"])
@cross_origin()
def delete_assignment(assignment_id):
    # Handle preflight OPTIONS request for CORS
    if request.method == "OPTIONS":
        return "", 200

    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404

    try:
        db.session.delete(assignment)
        db.session.commit()
        return jsonify({"message": "Assignment deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/serve-submission-file/<int:submission_id>", methods=["GET"])
def serve_submission_file(submission_id):
    s = Submission.query.get(submission_id)
    if not s or not s.file_data:
        return jsonify({"error": "File not found"}), 404
    return send_file(BytesIO(s.file_data), mimetype=guess_mimetype(s.filename),
                     as_attachment=True, download_name=s.filename)


#this is the code for the images
# Only allow CORS for your dashboard origin on the image endpoints
CORS(app, resources={
    r"/get-images/*": {"origins": "http://127.0.0.1:5500"},
    r"/serve-image/*": {"origins": "http://127.0.0.1:5500"},
})


# 🖼️ Upload multiple images for a user
@app.route('/upload-images', methods=['POST'])
def upload_images():
    user_code = request.form.get('user_code')
    images = request.files.getlist('images')
    if not user_code or not images:
        return jsonify({"error": "Missing user_code or images"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor()
        records = []
        for index, image_file in enumerate(images, start=1):
            file_path = f"wil-firm-pics/{user_code}/image_{index}.jpg"
            image_data = psycopg2.Binary(image_file.read())
            records.append((user_code, file_path, image_data))

        cur.executemany("""
            INSERT INTO firm_images (user_code, file_path, image_data)
            VALUES (%s, %s, %s)
        """, records)

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({
            "message": f"{len(images)} images saved for user {user_code}",
            "file_paths": [r[1] for r in records]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 📁 Retrieve image URLs for a user
@app.route('/get-images/<user_code>', methods=['GET'])
def get_images(user_code):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT file_path FROM firm_images WHERE user_code = %s
        """, (user_code,))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        base_url = request.host_url.rstrip('/')
        urls = [
            f"{base_url}/serve-image/{user_code}/{os.path.basename(row[0])}"
            for row in rows
        ]
        return jsonify({
            "user_code": user_code,
            "file_paths": urls
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 📤 Serve an actual image
@app.route('/serve-image/<user_code>/<filename>', methods=['GET'])
def serve_image(user_code, filename):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT image_data FROM firm_images
            WHERE user_code = %s AND file_path LIKE %s
            LIMIT 1
        """, (user_code, f"%{filename}"))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return jsonify({"error": "Image not found"}), 404

        return send_file(
            BytesIO(row[0]),
            mimetype='image/jpeg',
            as_attachment=False
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------
# CREATE / UPLOAD
# ----------------

def guess_mimetype(filename, fallback=None):
    """
    Try to guess mime type from filename; fallback to provided mime or application/octet-stream.
    """
    if not filename:
        return fallback or "application/octet-stream"
    mtype, _ = mimetypes.guess_type(filename)
    return mtype or fallback or "application/octet-stream"


# ----------------
# UPLOAD / CREATE
# ----------------
@app.route("/firm-proof", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_firm_proof():
    if request.method == "OPTIONS":
        return "", 200

    try:
        user_code = request.form.get("user_code")
        if not user_code:
            return jsonify({"error": "user_code is required"}), 400

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename.strip() == "":
            return jsonify({"error": "Filename missing"}), 400

        # store both original filename and a secure/safe file_path
        original_fn = file.filename
        safe_fn = secure_filename(original_fn)

        # optional: prepend user_code to file_path to avoid filename collisions
        # file_path = f"{user_code}/{safe_fn}"
        file_path = safe_fn

        mime = file.mimetype or guess_mimetype(original_fn)

        # Prevent duplicate (if desired - keeps UNIQUE constraint semantic)
        existing = FirmProof.query.filter_by(user_code=user_code).first()
        if existing:
            return jsonify({"error": "Proof already uploaded for this firm"}), 400

        proof = FirmProof(
            user_code=user_code,
            original_filename=original_fn,
            file_path=file_path,
            mime_type=mime,
            file_data=file.read()
        )
        db.session.add(proof)
        db.session.commit()

        # return metadata (including new id, filename, mime_type)
        return jsonify({
            "message": "Proof uploaded",
            "id": proof.id,
            "user_code": proof.user_code,
            "original_filename": proof.original_filename,
            "filename": proof.file_path,
            "mime_type": proof.mime_type,
            "file_url": f"/serve-firm-proof/{proof.id}",
            "uploaded_at": proof.uploaded_at.isoformat() if proof.uploaded_at else None
        }), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception("DB error uploading firm proof")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error uploading firm proof")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


# ----------------
# READ / LIST BY USER
# ----------------
@app.route("/firm-proof/<user_code>", methods=["GET", "OPTIONS"])
@cross_origin()
def get_firm_proof(user_code):
    if request.method == "OPTIONS":
        return "", 200

    proof = FirmProof.query.filter_by(user_code=user_code).first()
    if not proof:
        return jsonify({"error": "Proof not found"}), 404

    return jsonify({
        "id": proof.id,
        "user_code": proof.user_code,
        "original_filename": proof.original_filename,
        "filename": proof.file_path,
        "mime_type": proof.mime_type,
        "file_url": f"/serve-firm-proof/{proof.id}",
        "uploaded_at": proof.uploaded_at.isoformat() if proof.uploaded_at else None
    }), 200


# ----------------
# SERVE FILE (INLINE OR DOWNLOAD)
# ----------------
@app.route("/serve-firm-proof/<int:proof_id>", methods=["GET", "OPTIONS"])
@cross_origin()
def serve_firm_proof(proof_id):
    if request.method == "OPTIONS":
        return "", 200

    proof = FirmProof.query.get(proof_id)
    if not proof:
        return jsonify({"error": "Proof not found"}), 404

    as_attachment = request.args.get("download", "false").lower() == "true"
    mimetype = proof.mime_type or guess_mimetype(proof.original_filename)
    return send_file(
        BytesIO(proof.file_data),
        mimetype=mimetype,
        as_attachment=as_attachment,
        download_name=proof.original_filename or proof.file_path
    )


# ----------------
# UPDATE / REPLACE
# ----------------
@app.route("/firm-proof/<int:proof_id>", methods=["PUT", "OPTIONS"])
@cross_origin()
def update_firm_proof(proof_id):
    if request.method == "OPTIONS":
        return "", 200

    proof = FirmProof.query.get(proof_id)
    if not proof:
        return jsonify({"error": "Proof not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        file = request.files["file"]
        if file.filename.strip() == "":
            return jsonify({"error": "Filename missing"}), 400

        original_fn = file.filename
        safe_fn = secure_filename(original_fn)
        proof.original_filename = original_fn
        proof.file_path = safe_fn
        proof.mime_type = file.mimetype or guess_mimetype(original_fn)
        proof.file_data = file.read()
        proof.uploaded_at = datetime.utcnow()
        db.session.commit()
        return jsonify({
            "message": "Proof updated",
            "id": proof.id,
            "original_filename": proof.original_filename,
            "filename": proof.file_path,
            "mime_type": proof.mime_type,
            "uploaded_at": proof.uploaded_at.isoformat() if proof.uploaded_at else None
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception("DB error updating firm proof")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error updating firm proof")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


# ----------------
# DELETE
# ----------------
@app.route("/firm-proof/<int:proof_id>", methods=["DELETE", "OPTIONS"])
@cross_origin()
def delete_firm_proof(proof_id):
    if request.method == "OPTIONS":
        return "", 200

    proof = FirmProof.query.get(proof_id)
    if not proof:
        return jsonify({"error": "Proof not found"}), 404

    try:
        db.session.delete(proof)
        db.session.commit()
        return jsonify({"message": "Proof deleted"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception("DB error deleting firm proof")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error deleting firm proof")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

# ----------------
# CREATE JOB
# ----------------
@app.route("/api/jobs", methods=["POST", "OPTIONS"])
@cross_origin()
def create_job():
    if request.method == "OPTIONS":
        return "", 200

    title = request.form.get("title")
    description = request.form.get("description")
    file = request.files.get("file")

    if not title:
        return jsonify({"error": "Title is required"}), 400

    job = Job(title=title, description=description)

    if file:
        original_fn = file.filename
        safe_fn = secure_filename(original_fn)
        job.file_name = original_fn
        job.file_path = safe_fn
        job.mime_type = file.mimetype or mimetypes.guess_type(original_fn)[0]
        job.file_data = file.read()
        job.uploaded_at = datetime.utcnow()

    try:
        db.session.add(job)
        db.session.commit()
        return jsonify(job.to_dict()), 201
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception("DB error creating job")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

# ----------------
# READ ALL JOBS
# ----------------
@app.route("/api/jobs", methods=["GET", "OPTIONS"])
@cross_origin()
def get_jobs():
    if request.method == "OPTIONS":
        return "", 200
    jobs = Job.query.all()
    return jsonify([job.to_dict() for job in jobs]), 200

# ----------------
# READ ONE JOB
# ----------------
@app.route("/api/jobs/<int:job_id>", methods=["GET", "OPTIONS"])
@cross_origin()
def get_job(job_id):
    if request.method == "OPTIONS":
        return "", 200
    job = Job.query.get_or_404(job_id)
    return jsonify(job.to_dict()), 200

# ----------------
# DOWNLOAD JOB FILE
# ----------------
@app.route("/api/jobs/<int:job_id>/download", methods=["GET", "OPTIONS"])
@cross_origin()
def download_job_file(job_id):
    if request.method == "OPTIONS":
        return "", 200
    job = Job.query.get_or_404(job_id)
    if not job.file_data:
        return jsonify({"error": "No file uploaded"}), 404

    mime_type = job.mime_type or mimetypes.guess_type(job.file_name or "file.bin")[0]
    return send_file(
        BytesIO(job.file_data),
        mimetype=mime_type or "application/octet-stream",
        as_attachment=True,
        download_name=job.file_name or "downloaded_file"
    )

# ----------------
# UPDATE JOB
# ----------------
@app.route("/api/jobs/<int:job_id>", methods=["PUT", "OPTIONS"])
@cross_origin()
def update_job(job_id):
    if request.method == "OPTIONS":
        return "", 200

    job = Job.query.get_or_404(job_id)
    data = request.form
    file = request.files.get("file")

    job.title = data.get("title", job.title)
    job.description = data.get("description", job.description)

    if file:
        original_fn = file.filename
        safe_fn = secure_filename(original_fn)
        job.file_name = original_fn
        job.file_path = safe_fn
        job.mime_type = file.mimetype or mimetypes.guess_type(original_fn)[0]
        job.file_data = file.read()
        job.uploaded_at = datetime.utcnow()

    try:
        db.session.commit()
        return jsonify(job.to_dict()), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception("DB error updating job")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

# ----------------
# DELETE JOB
# ----------------
@app.route("/api/jobs/<int:job_id>", methods=["DELETE", "OPTIONS"])
@cross_origin()
def delete_job(job_id):
    if request.method == "OPTIONS":
        return "", 200

    job = Job.query.get_or_404(job_id)
    try:
        db.session.delete(job)
        db.session.commit()
        return jsonify({"message": "Job deleted"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.exception("DB error deleting job")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


# ======================================================
# CRUD: Profile Pictures stored in PostgreSQL BYTEA
# ======================================================

@app.route("/profile-picture/<string:user_id>", methods=["GET", "OPTIONS"])
@cross_origin()
def get_profile_picture(user_id):
    if request.method == "OPTIONS":
        return "", 200
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT profile_picture FROM users WHERE id = %s;", (user_id,))
        result = cursor.fetchone()
        cursor.close()
        if result and result[0]:
            return send_file(io.BytesIO(result[0]), mimetype="image/jpeg")
        return jsonify({"message": "No profile picture found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/profile-picture/<string:user_id>", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_profile_picture(user_id):
    if request.method == "OPTIONS":
        return "", 200
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    image = request.files["image"].read()
    if not image:
        return jsonify({"error": "Empty file"}), 400

    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET profile_picture = %s WHERE id = %s;",
            (psycopg2.Binary(image), user_id)
        )
        conn.commit()
        cursor.close()
        return jsonify({"message": "Profile picture uploaded"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/profile-picture/<string:user_id>", methods=["PUT", "OPTIONS"])
@cross_origin()
def update_profile_picture(user_id):
    if request.method == "OPTIONS":
        return "", 200
    return upload_profile_picture(user_id)  # reuse POST logic


@app.route("/profile-picture/<string:user_id>", methods=["DELETE", "OPTIONS"])
@cross_origin()
def delete_profile_picture(user_id):
    if request.method == "OPTIONS":
        return "", 200
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET profile_picture = NULL WHERE id = %s;", (user_id,)
        )
        conn.commit()
        cursor.close()
        return jsonify({"message": "Profile picture deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


BREVO_KEY = os.getenv("BREVO_API_KEY", "21Zfm4c68p3FhC0N")  # replace fallback or remove once env var used

configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = BREVO_KEY
api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

@app.route('/send-email', methods=['POST'])
def send_email():
    # log request for debugging
    try:
        app.logger.info("send-email invoked; headers=%s", dict(request.headers))
        raw = request.get_data(as_text=True)
        app.logger.debug("send-email raw body: %s", raw[:2000])
    except Exception:
        app.logger.exception("Failed reading request raw body")

    # parse JSON
    data = request.get_json(silent=True)
    if not data:
        # try fallback to parse text
        try:
            data = json.loads(raw) if raw else None
        except Exception:
            data = None

    if not data:
        app.logger.warning("send-email: no JSON payload; request.data=%s", (raw or "")[:1000])
        return jsonify({"status": "error", "message": "No JSON payload provided"}), 400

    # required fields
    company_email = data.get("companyEmail")
    company_name = data.get("companyName")
    user_name = data.get("userName")

    missing = [k for k, v in (("companyEmail", company_email), ("companyName", company_name), ("userName", user_name)) if not v]
    if missing:
        app.logger.warning("send-email: missing fields %s", missing)
        return jsonify({"status": "error", "message": f"Missing required fields: {', '.join(missing)}"}), 400

    # IMPORTANT: Brevo requires this sender to be VERIFIED in the Brevo dashboard
    sender_email = data.get("from_email", "your_verified@domain.com")  # change to your verified sender
    sender_name = data.get("from_name", "WELAP System")

    # Compose email content
    subject = data.get("subject", "Action Required: Complete Your Signup")
    html_body = data.get("htmlBody") or f"""
      <p>Dear <strong>{company_name}</strong>,</p>
      <p>{user_name} has manually added your firm to our platform. Please complete the signup process.</p>
      <p>Kind regards,<br><strong>Vincent Civic Platform</strong></p>
    """
    text_body = data.get("textBody") or f"Dear {company_name},\n\n{user_name} has manually added your firm to our platform. Please complete the signup process.\n\nKind regards,\nVincent Civic Platform"

    email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": company_email}],
        sender={"name": sender_name, "email": sender_email},
        subject=subject,
        html_content=html_body,
        text_content=text_body
    )

    try:
        resp = api_instance.send_transac_email(email)
        # Log Brevo response object for debugging
        app.logger.info("Brevo send_transac_email success: %s", getattr(resp, "__dict__", str(resp)) )
        # return resp as JSON-friendly structure if possible
        try:
            # some SDK responses are models; try to convert to dict via to_dict if available
            body = resp.to_dict() if hasattr(resp, "to_dict") else str(resp)
        except Exception:
            body = str(resp)
        return jsonify({"status": "success", "brevo_response": body}), 200

    except ApiException as e:
        # ApiException from sib_api_v3_sdk often contains a body with details
        app.logger.exception("Brevo ApiException while sending email")
        err_info = {"status": "error", "message": "Brevo ApiException", "type": e.__class__.__name__}
        # add structured fields if present (be careful in production)
        try:
            err_info["api_status"] = getattr(e, "status", None)
            err_info["api_body"] = getattr(e, "body", None)
        except Exception:
            pass
        return jsonify(err_info), 500

    except Exception as e:
        # catch-all
        app.logger.exception("Unhandled exception in send-email")
        return jsonify({
            "status": "error",
            "message": "Unhandled exception in send-email",
            "error": str(e),
            "type": e.__class__.__name__,
            "traceback": traceback.format_exc().splitlines()[-10:]  # last 10 lines of trace
        }), 500
        
# ----------------
# Run App
# ----------------
if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug)
