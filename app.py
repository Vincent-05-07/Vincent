import os
import psycopg2
from flask import Flask, request, jsonify, send_file, send_from_directory
from io import BytesIO
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# ----------------
# Flask Config
# ----------------
app = Flask(__name__)

# Max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Image upload folders for document handling
app.config['UPLOAD_FOLDER_DOCS'] = 'uploads/documents'
os.makedirs(app.config['UPLOAD_FOLDER_DOCS'], exist_ok=True)

# SQLAlchemy config for documents and assignments
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------
# CORS settings
# ----------------
CORS(app, resources={r"*": {"origins": "*"}})

# ----------------
# PostgreSQL Connection (for images)
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
# SQLAlchemy Models (Documents & Assignments)
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
    description = db.Column(db.Text, nullable=True)
    deadline_iso = db.Column(db.String(50), nullable=False)
    file_path = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), default="open")  # open / closed

class AssignmentSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, nullable=False)
    user_code = db.Column(db.String(50), nullable=False)
    text_answer = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String(255), nullable=True)
    submitted_at = db.Column(db.DateTime, default=db.func.current_timestamp())

with app.app_context():
    db.create_all()

# ----------------
# Helpers
# ----------------
def save_file(file, folder):
    filename = secure_filename(file.filename)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    file.save(filepath)
    return filepath

# ----------------
# Root + Health
# ----------------
@app.route('/')
def index():
    return jsonify({"message": "Flask API is live!"})

@app.route('/health', methods=['GET'])
def health_check():
    try:
        conn = get_connection()
        conn.close()
        return jsonify({"status": "healthy"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# ----------------
# DOCUMENTS (SQLAlchemy)
# ----------------
@app.route("/documents", methods=["POST"])
def upload_documents():
    user_code = request.form.get("user_code")
    if not user_code or "cvFile" not in request.files or "idFile" not in request.files:
        return jsonify({"error": "user_code, CV and ID are required"}), 400

    cv = request.files["cvFile"]
    id_doc = request.files["idFile"]

    user_folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    cv_filename = save_file(cv, user_folder)
    id_filename = save_file(id_doc, user_folder)

    new_doc = Document(user_code=user_code, cv_filename=cv_filename, id_filename=id_filename)
    db.session.add(new_doc)
    db.session.commit()
    return jsonify({"message": "Documents uploaded", "id": new_doc.id}), 201

@app.route("/documents/<user_code>", methods=["GET"])
def get_documents(user_code):
    docs = Document.query.filter_by(user_code=user_code).all()
    return jsonify([{
        "id": d.id,
        "cv_filename": d.cv_filename,
        "id_filename": d.id_filename
    } for d in docs])

@app.route("/documents/<user_code>/<int:doc_id>/<string:filetype>", methods=["GET"])
def get_document(user_code, doc_id, filetype):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    if filetype == "cv":
        return send_from_directory(user_folder, doc.cv_filename)
    elif filetype == "id":
        return send_from_directory(user_folder, doc.id_filename)
    else:
        return jsonify({"error": "Invalid filetype. Use 'cv' or 'id'"}), 400

@app.route("/documents/<user_code>/<int:doc_id>", methods=["PUT"])
def update_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)

    if "cvFile" in request.files:
        cv = request.files["cvFile"]
        cv_filename = save_file(cv, user_folder)
        doc.cv_filename = cv_filename

    if "idFile" in request.files:
        id_doc = request.files["idFile"]
        id_filename = save_file(id_doc, user_folder)
        doc.id_filename = id_filename

    db.session.commit()
    return jsonify({"message": "Documents updated"})

@app.route("/documents/<user_code>/<int:doc_id>", methods=["DELETE"])
def delete_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    os.remove(os.path.join(user_folder, doc.cv_filename))
    os.remove(os.path.join(user_folder, doc.id_filename))
    db.session.delete(doc)
    db.session.commit()
    return jsonify({"message": "Documents deleted"})

# ----------------
# ASSIGNMENTS CRUD
# ----------------
@app.route("/api/assignments", methods=["POST"])
def create_assignment():
    lecture_id = request.form.get("lecture_id")
    title = request.form.get("title")
    description = request.form.get("description", "")
    deadline_iso = request.form.get("deadline_iso")
    file = request.files.get("file")

    if not lecture_id or not title or not deadline_iso:
        return jsonify({"error": "lecture_id, title, and deadline_iso are required"}), 400

    file_path = None
    if file:
        folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], "assignments", lecture_id)
        os.makedirs(folder, exist_ok=True)
        file_path = save_file(file, folder)

    assignment = Assignment(
        lecture_id=lecture_id,
        title=title,
        description=description,
        deadline_iso=deadline_iso,
        file_path=file_path
    )
    db.session.add(assignment)
    db.session.commit()
    return jsonify({"id": assignment.id}), 201

@app.route("/api/assignments", methods=["GET"])
def list_assignments():
    lecture_id = request.args.get("lecture_id")
    if not lecture_id:
        return jsonify({"error": "lecture_id is required"}), 400
    assignments = Assignment.query.filter_by(lecture_id=lecture_id).all()
    return jsonify([{
        "id": a.id,
        "lecture_id": a.lecture_id,
        "title": a.title,
        "description": a.description,
        "deadline_iso": a.deadline_iso,
        "file_url": f"{request.host_url.rstrip('/')}/documents/assignments/{a.lecture_id}/{os.path.basename(a.file_path)}" if a.file_path else None,
        "status": a.status
    } for a in assignments])

@app.route("/api/assignments/<int:assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    a = Assignment.query.get_or_404(assignment_id)
    return jsonify({
        "id": a.id,
        "lecture_id": a.lecture_id,
        "title": a.title,
        "description": a.description,
        "deadline_iso": a.deadline_iso,
        "file_url": f"{request.host_url.rstrip('/')}/documents/assignments/{a.lecture_id}/{os.path.basename(a.file_path)}" if a.file_path else None,
        "status": a.status
    })

@app.route("/api/assignments/<int:assignment_id>", methods=["PATCH"])
def update_assignment(assignment_id):
    a = Assignment.query.get_or_404(assignment_id)
    data = request.get_json() or {}

    a.title = data.get("title", a.title)
    a.description = data.get("description", a.description)
    a.deadline_iso = data.get("deadline_iso", a.deadline_iso)
    a.status = data.get("status", a.status)
    db.session.commit()
    return jsonify({"message": "Assignment updated"})

@app.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
def delete_assignment(assignment_id):
    a = Assignment.query.get_or_404(assignment_id)
    if a.file_path and os.path.exists(a.file_path):
        os.remove(a.file_path)
    db.session.delete(a)
    db.session.commit()
    return jsonify({"message": "Assignment deleted"})

# ----------------
# SUBMISSIONS
# ----------------
@app.route("/api/assignments/<int:assignment_id>/submissions", methods=["POST"])
def submit_assignment(assignment_id):
    user_code = request.form.get("user_code")
    text_answer = request.form.get("text_answer", "")
    file = request.files.get("file")

    if not user_code:
        return jsonify({"error": "user_code is required"}), 400

    file_path = None
    if file:
        folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], "assignments", str(assignment_id), user_code)
        os.makedirs(folder, exist_ok=True)
        file_path = save_file(file, folder)

    submission = AssignmentSubmission(
        assignment_id=assignment_id,
        user_code=user_code,
        text_answer=text_answer,
        file_path=file_path
    )
    db.session.add(submission)
    db.session.commit()

    file_url = f"{request.host_url.rstrip('/')}/documents/assignments/{assignment_id}/{user_code}/{os.path.basename(file_path)}" if file_path else None
    return jsonify({
        "id": submission.id,
        "assignment_id": assignment_id,
        "user_code": user_code,
        "file_url": file_url
    }), 201

@app.route("/api/assignments/<int:assignment_id>/submissions", methods=["GET"])
def list_submissions(assignment_id):
    submissions = AssignmentSubmission.query.filter_by(assignment_id=assignment_id).all()
    return jsonify([{
        "id": s.id,
        "assignment_id": s.assignment_id,
        "user_code": s.user_code,
        "text_answer": s.text_answer,
        "file_url": f"{request.host_url.rstrip('/')}/documents/assignments/{s.assignment_id}/{s.user_code}/{os.path.basename(s.file_path)}" if s.file_path else None,
        "submitted_at": s.submitted_at
    } for s in submissions])

# Serve assignment files
@app.route("/documents/assignments/<assignment_id>/<user_code>/<filename>", methods=["GET"])
def serve_assignment_file(assignment_id, user_code, filename):
    folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], "assignments", assignment_id, user_code)
    return send_from_directory(folder, filename)

# ----------------
# Run
# ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
