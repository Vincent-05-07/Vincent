import os
import mimetypes
from datetime import datetime
from io import BytesIO

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from sqlalchemy import func

from flask_cors import CORS

CORS(
    app,
    resources={r"/*": {"origins": "http://127.0.0.1:5500"}},
    supports_credentials=True,
    methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]
)

# ----------------
# Config & App
# ----------------
app = Flask(__name__)

# Max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Build SQLAlchemy DB URI from env vars. If not provided, fallback to SQLite for local testing.
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
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'  # fallback for local dev

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


# Create tables if they don't exist
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


@app.route("/health", methods=["GET"])
def health_check():
    try:
        db.session.execute("SELECT 1")
        return jsonify({"status": "healthy", "db": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


# =========================================================
# FIRM IMAGES
# =========================================================
@app.route("/upload-images", methods=["POST"])
def upload_images():
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
            img = FirmImage(
                user_code=user_code,
                file_path=file_path,
                filename=filename_with_index,
                image_data=data
            )
            db.session.add(img)
            db.session.flush()  # ensure id
            created.append({"id": img.id, "file_path": file_path})
        db.session.commit()

        # return relative URLs (Option A)
        urls = [f"/serve-image/{c['id']}" for c in created]
        return jsonify({"message": f"{len(created)} images saved", "file_paths": urls}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/get-images/<user_code>", methods=["GET"])
def get_images(user_code):
    try:
        rows = FirmImage.query.filter_by(user_code=user_code).all()
        urls = [f"/serve-image/{r.id}" for r in rows]
        return jsonify({"user_code": user_code, "file_paths": urls}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/serve-image/<int:image_id>", methods=["GET"])
def serve_image(image_id):
    img = FirmImage.query.get(image_id)
    if not img:
        return jsonify({"error": "Image not found"}), 404
    return send_file(BytesIO(img.image_data), mimetype=guess_mimetype(img.filename),
                     as_attachment=False, download_name=img.filename)


# =========================================================
# DOCUMENTS (CV & ID)
# =========================================================
@app.route("/documents", methods=["POST"])
def upload_documents():
    user_code = request.form.get("user_code")
    if not user_code or "cvFile" not in request.files or "idFile" not in request.files:
        return jsonify({"error": "user_code, CV and ID are required"}), 400
    try:
        cv = request.files["cvFile"]
        idf = request.files["idFile"]
        doc = Document(
            user_code=user_code,
            cv_filename=safe_filename(cv),
            cv_data=cv.read(),
            id_filename=safe_filename(idf),
            id_data=idf.read()
        )
        db.session.add(doc)
        db.session.commit()
        return jsonify({"message": "Documents uploaded", "id": doc.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/documents/<user_code>", methods=["GET"])
def list_documents(user_code):
    docs = Document.query.filter_by(user_code=user_code).all()
    result = []
    for d in docs:
        result.append({
            "id": d.id,
            "cv_filename": d.cv_filename,
            "cv_url": f"/serve-document/{d.id}/cv",
            "id_filename": d.id_filename,
            "id_url": f"/serve-document/{d.id}/id",
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None
        })
    return jsonify(result)


@app.route("/serve-document/<int:doc_id>/<string:filetype>", methods=["GET"])
def serve_document(doc_id, filetype):
    doc = Document.query.get(doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    if filetype == "cv":
        return send_file(BytesIO(doc.cv_data), mimetype=guess_mimetype(doc.cv_filename),
                         as_attachment=True, download_name=doc.cv_filename)
    elif filetype == "id":
        return send_file(BytesIO(doc.id_data), mimetype=guess_mimetype(doc.id_filename),
                         as_attachment=True, download_name=doc.id_filename)
    else:
        return jsonify({"error": "Invalid filetype"}), 400


@app.route("/documents/<user_code>/<int:doc_id>", methods=["PUT"])
def update_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    try:
        if "cvFile" in request.files:
            cv = request.files["cvFile"]
            doc.cv_filename = safe_filename(cv)
            doc.cv_data = cv.read()
        if "idFile" in request.files:
            idf = request.files["idFile"]
            doc.id_filename = safe_filename(idf)
            doc.id_data = idf.read()
        db.session.commit()
        return jsonify({"message": "Documents updated"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/documents/<user_code>/<int:doc_id>", methods=["DELETE"])
def delete_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    try:
        db.session.delete(doc)
        db.session.commit()
        return jsonify({"message": "Documents deleted"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# =========================================================
# ASSIGNMENTS
# =========================================================
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

        # return relative file_url
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


@app.route("/serve-assignment-file/<int:assignment_id>", methods=["GET"])
def serve_assignment_file(assignment_id):
    a = Assignment.query.get(assignment_id)
    if not a or not a.file_data:
        return jsonify({"error": "File not found"}), 404
    return send_file(BytesIO(a.file_data), mimetype=guess_mimetype(a.file_filename),
                     as_attachment=True, download_name=a.file_filename)


@app.route("/api/assignments/<int:assignment_id>", methods=["PATCH"])
def update_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json()
    try:
        assignment.title = data.get("title", assignment.title)
        assignment.description = data.get("description", assignment.description)
        assignment.deadline_iso = data.get("deadline_iso", assignment.deadline_iso)
        assignment.status = data.get("status", assignment.status)
        db.session.commit()
        return jsonify({"message": "Assignment updated"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
def delete_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    try:
        db.session.delete(assignment)
        db.session.commit()
        return jsonify({"message": "Assignment deleted"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# =========================================================
# SUBMISSIONS
# =========================================================
@app.route("/api/assignments/<int:assignment_id>/submissions", methods=["PUT"])
def update_submission(assignment_id):
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

        # bump updated_at manually (DB also handles onupdate)
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
    # lists all submissions for a given assignment
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


@app.route("/api/submissions/<int:submission_id>", methods=["GET"])
def get_submission(submission_id):
    s = Submission.query.get_or_404(submission_id)
    return jsonify({
        "id": s.id,
        "assignment_id": s.assignment_id,
        "user_code": s.user_code,
        "filename": s.filename,
        "file_url": f"/serve-submission-file/{s.id}" if s.filename else None,
        "description": s.description,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None
    })


@app.route("/api/assignments/<int:assignment_id>/submissions", methods=["DELETE"])
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug)
