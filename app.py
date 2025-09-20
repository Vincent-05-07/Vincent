import os
from datetime import datetime
from io import BytesIO
from mimetypes import guess_type

from flask import Flask, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from sqlalchemy import func
from flask_cors import CORS, cross_origin

# ----------------
# Flask app + CORS
# ----------------
app = Flask(__name__)
CORS(app, supports_credentials=True, origins="*")  # adjust origins in production

# ----------------
# Config
# ----------------
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

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
# Models
# ----------------
class FirmImage(db.Model):
    __tablename__ = "firm_images"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(80), index=True, nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    image_data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(80), index=True, nullable=False)
    cv_filename = db.Column(db.String(255), nullable=False)
    cv_data = db.Column(db.LargeBinary, nullable=False)
    id_filename = db.Column(db.String(255), nullable=False)
    id_data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class UserCV(db.Model):
    __tablename__ = "user_cv"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(80), nullable=False)
    filename = db.Column(db.String(255))
    file_path = db.Column(db.Text)
    file_data = db.Column(db.LargeBinary)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class UserIDDoc(db.Model):
    __tablename__ = "user_id_doc"
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(80), nullable=False)
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

# Create tables
with app.app_context():
    db.create_all()

# ----------------
# Helpers
# ----------------
def safe_filename(file_obj):
    if not file_obj:
        return ""
    return secure_filename(getattr(file_obj, "filename", file_obj) or "")

def guess_mimetype(filename):
    mimetype, _ = guess_type(filename)
    return mimetype or "application/octet-stream"

# ----------------
# Root & Health
# ----------------
@app.route("/")
def index():
    return jsonify({"message": "Flask API (merged) is live!"})

@app.route("/health")
def health_check():
    try:
        db.session.execute("SELECT 1")
        return jsonify({"status": "healthy", "db": "connected"}), 200
    except Exception as e:
        app.logger.exception("Health check failed")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# ----------------
# FIRM IMAGES (upload / list / serve)
# ----------------
@app.route("/upload-images", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_images():
    """
    POST form-data:
      - user_code (string)
      - images[] (file)  (multiple allowed)
    Returns JSON with created image ids and serve URLs.
    """
    if request.method == "OPTIONS":
        return "", 200

    user_code = request.form.get("user_code")
    images = request.files.getlist("images")
    if not user_code or not images:
        return jsonify({"error": "Missing user_code or images"}), 400

    created = []
    try:
        for idx, image_file in enumerate(images, start=1):
            filename = safe_filename(image_file) or f"image_{idx}.jpg"
            ext = os.path.splitext(filename)[1] or ".jpg"
            filename_with_index = f"image_{idx}{ext}"
            file_path = f"wil-firm-pics/{user_code}/{filename_with_index}"
            data = image_file.read()
            img = FirmImage(user_code=user_code, file_path=file_path, filename=filename_with_index, image_data=data)
            db.session.add(img)
            db.session.flush()  # get id
            created.append({"id": img.id, "file_path": file_path})
        db.session.commit()
        base = request.host_url.rstrip('/')
        urls = [f"{base}/serve-image/{c['id']}" for c in created]
        return jsonify({"message": f"{len(created)} images saved", "files": created, "file_paths": urls}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error uploading images")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

@app.route("/get-images/<user_code>", methods=["GET"])
def get_images(user_code):
    """
    Returns JSON: { user_code, file_paths: ["/serve-image/<id>", ...] }
    If none found returns an empty list (200) to be friendly to front-end.
    """
    try:
        imgs = FirmImage.query.filter_by(user_code=user_code).all()
        base = request.host_url.rstrip('/')
        urls = [f"{base}/serve-image/{img.id}" for img in imgs]
        return jsonify({"user_code": user_code, "file_paths": urls}), 200
    except Exception as e:
        app.logger.exception("Error in get_images")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

@app.route("/serve-image/<int:image_id>", methods=["GET"])
def serve_image(image_id):
    """
    Serve binary image for given image id.
    """
    try:
        img = FirmImage.query.get(image_id)
        if not img:
            return jsonify({"error": "Image not found"}), 404
        mimetype = guess_mimetype(img.filename)
        return send_file(BytesIO(img.image_data), mimetype=mimetype, as_attachment=False, download_name=img.filename)
    except Exception as e:
        app.logger.exception("Error serving image")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

# ----------------
# UserCV CRUD
# ----------------
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
        filename = safe_filename(file)
        cv = UserCV(user_code=user_code, filename=filename, file_data=file.read())
        db.session.add(cv)
        db.session.commit()
        return jsonify({"message": "CV uploaded", "id": cv.id}), 201
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error uploading CV")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

@app.route("/serve-cv/<int:cv_id>", methods=["GET"])
def serve_cv(cv_id):
    doc = UserCV.query.get(cv_id)
    if not doc:
        return jsonify({"error": "CV not found"}), 404
    return send_file(BytesIO(doc.file_data), mimetype=guess_mimetype(doc.filename),
                     as_attachment=True, download_name=doc.filename)

@app.route("/cv/<int:cv_id>", methods=["PUT"])
def update_cv(cv_id):
    doc = UserCV.query.get(cv_id)
    if not doc:
        return jsonify({"error": "CV not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Filename missing"}), 400
    doc.filename = safe_filename(file)
    doc.file_data = file.read()
    db.session.commit()
    return jsonify({"message": "CV updated", "id": doc.id})

@app.route("/cv/<int:cv_id>", methods=["DELETE"])
def delete_cv(cv_id):
    doc = UserCV.query.get(cv_id)
    if not doc:
        return jsonify({"error": "CV not found"}), 404
    db.session.delete(doc)
    db.session.commit()
    return jsonify({"message": "CV deleted"}), 200

# ----------------
# UserIDDoc CRUD
# ----------------
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
        filename = safe_filename(file)
        id_doc = UserIDDoc(user_code=user_code, filename=filename, file_data=file.read())
        db.session.add(id_doc)
        db.session.commit()
        return jsonify({"message": "ID uploaded", "id": id_doc.id}), 201
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error uploading ID document")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

@app.route("/serve-id/<int:id_id>", methods=["GET"])
def serve_id(id_id):
    doc = UserIDDoc.query.get(id_id)
    if not doc:
        return jsonify({"error": "ID not found"}), 404
    return send_file(BytesIO(doc.file_data), mimetype=guess_mimetype(doc.filename),
                     as_attachment=True, download_name=doc.filename)

@app.route("/id-doc/<int:id_id>", methods=["PUT"])
def update_id_doc(id_id):
    doc = UserIDDoc.query.get(id_id)
    if not doc:
        return jsonify({"error": "ID not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Filename missing"}), 400
    doc.filename = safe_filename(file)
    doc.file_data = file.read()
    db.session.commit()
    return jsonify({"message": "ID updated", "id": doc.id})

@app.route("/id-doc/<int:id_id>", methods=["DELETE"])
def delete_id_doc(id_id):
    doc = UserIDDoc.query.get(id_id)
    if not doc:
        return jsonify({"error": "ID not found"}), 404
    db.session.delete(doc)
    db.session.commit()
    return jsonify({"message": "ID deleted"}), 200

# ----------------
# Documents (combined CV + ID upload)
# ----------------
@app.route("/documents", methods=["POST", "OPTIONS"])
@cross_origin()
def upload_documents():
    if request.method == "OPTIONS":
        return "", 200
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
        app.logger.exception("Error uploading documents")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

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

# ----------------
# Assignments
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
        app.logger.exception("Error creating assignment")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

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
# Submissions
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
        app.logger.exception("Error updating submission")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

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
        app.logger.exception("Error deleting submission")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

@app.route("/serve-submission-file/<int:submission_id>", methods=["GET"])
def serve_submission_file(submission_id):
    s = Submission.query.get(submission_id)
    if not s or not s.file_data:
        return jsonify({"error": "File not found"}), 404
    return send_file(BytesIO(s.file_data), mimetype=guess_mimetype(s.filename),
                     as_attachment=True, download_name=s.filename)

@app.route("/view-submission/<int:submission_id>", methods=["GET"])
def view_submission(submission_id):
    sub = Submission.query.get(submission_id)
    if not sub or not sub.file_data:
        return jsonify({"error": "Submission not found"}), 404
    mimetype = guess_mimetype(sub.filename)
    viewable_types = ["application/pdf", "image/png", "image/jpeg", "image/jpg", "image/gif", "text/plain", "text/html"]
    as_attachment = mimetype not in viewable_types
    return send_file(BytesIO(sub.file_data), mimetype=mimetype, as_attachment=as_attachment, download_name=sub.filename)

# ----------------
# CV / ID inline view helpers
# ----------------
@app.route("/view-cv/<int:cv_id>", methods=["GET"])
def view_cv(cv_id):
    doc = UserCV.query.get(cv_id)
    if not doc:
        return jsonify({"error": "CV not found"}), 404
    mimetype = guess_mimetype(doc.filename)
    return send_file(BytesIO(doc.file_data), mimetype=mimetype, as_attachment=False, download_name=doc.filename)

@app.route("/view-id/<int:id_id>", methods=["GET"])
def view_id(id_id):
    doc = UserIDDoc.query.get(id_id)
    if not doc:
        return jsonify({"error": "ID not found"}), 404
    mimetype = guess_mimetype(doc.filename)
    return send_file(BytesIO(doc.file_data), mimetype=mimetype, as_attachment=False, download_name=doc.filename)

# ----------------
# Run
# ----------------
if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug)
