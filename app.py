import os
import json
import shutil
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# ----------------
# Flask Config
# ----------------
app = Flask(__name__)

# Max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Upload folders
app.config['UPLOAD_FOLDER_DOCS'] = 'uploads/documents'
app.config['UPLOAD_FOLDER_ASSIGNMENTS'] = 'uploads/assignments'
os.makedirs(app.config['UPLOAD_FOLDER_DOCS'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], exist_ok=True)

# SQLite DB
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# CORS
CORS(app, resources={r"/api/*": {"origins": ["http://127.0.0.1:5500", "http://localhost:5500", "https://project-connect-x4ei.onrender.com"]}}, supports_credentials=True)

# ----------------
# SQLAlchemy Models
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
    file_url = db.Column(db.String(255))

with app.app_context():
    db.create_all()

# ----------------
# Helpers
# ----------------
def save_file(file, folder):
    os.makedirs(folder, exist_ok=True)
    filename = secure_filename(file.filename)
    file_path = os.path.join(folder, filename)
    file.save(file_path)
    return filename

# ----------------
# Routes
# ----------------

@app.route('/')
def index():
    return jsonify({"message": "Flask API is live!"})

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

# ----------------
# DOCUMENTS CRUD
# ----------------
@app.route("/documents", methods=["POST"])
def upload_documents():
    user_code = request.form.get("user_code")
    if not user_code or "cvFile" not in request.files or "idFile" not in request.files:
        return jsonify({"error": "user_code, CV and ID are required"}), 400

    user_folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    cv_filename = save_file(request.files["cvFile"], user_folder)
    id_filename = save_file(request.files["idFile"], user_folder)

    doc = Document(user_code=user_code, cv_filename=cv_filename, id_filename=id_filename)
    db.session.add(doc)
    db.session.commit()
    return jsonify({"message": "Documents uploaded", "id": doc.id}), 201

@app.route("/documents/<user_code>", methods=["GET"])
def list_documents(user_code):
    docs = Document.query.filter_by(user_code=user_code).all()
    return jsonify([{"id": d.id, "cv_filename": d.cv_filename, "id_filename": d.id_filename} for d in docs])

@app.route("/documents/<user_code>/<int:doc_id>/<string:filetype>", methods=["GET"])
def get_document(user_code, doc_id, filetype):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    if filetype == "cv":
        return send_from_directory(folder, doc.cv_filename)
    elif filetype == "id":
        return send_from_directory(folder, doc.id_filename)
    else:
        return jsonify({"error": "Invalid filetype"}), 400

@app.route("/documents/<user_code>/<int:doc_id>", methods=["PUT"])
def update_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)

    if "cvFile" in request.files:
        doc.cv_filename = save_file(request.files["cvFile"], folder)
    if "idFile" in request.files:
        doc.id_filename = save_file(request.files["idFile"], folder)

    db.session.commit()
    return jsonify({"message": "Documents updated"})

@app.route("/documents/<user_code>/<int:doc_id>", methods=["DELETE"])
def delete_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    os.remove(os.path.join(folder, doc.cv_filename))
    os.remove(os.path.join(folder, doc.id_filename))
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
    deadline_iso = request.form.get("deadline_iso")
    description = request.form.get("description")
    if not lecture_id or not title or not deadline_iso:
        return jsonify({"error": "lecture_id, title, deadline_iso required"}), 400

    file_url = None
    if "file" in request.files:
        folder = os.path.join(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], lecture_id)
        filename = save_file(request.files["file"], folder)
        file_url = os.path.join(folder, filename)

    assignment = Assignment(
        lecture_id=lecture_id,
        title=title,
        description=description,
        deadline_iso=deadline_iso,
        file_url=file_url
    )
    db.session.add(assignment)
    db.session.commit()
    return jsonify({"message": "Assignment created", "id": assignment.id}), 201

@app.route("/api/assignments", methods=["GET"])
def list_assignments():
    lecture_id = request.args.get("lecture_id")
    query = Assignment.query
    if lecture_id:
        query = query.filter_by(lecture_id=lecture_id)
    assignments = query.all()
    return jsonify([{
        "id": a.id,
        "lecture_id": a.lecture_id,
        "title": a.title,
        "description": a.description,
        "deadline_iso": a.deadline_iso,
        "status": a.status,
        "file_url": a.file_url
    } for a in assignments])

@app.route("/api/assignments/<int:assignment_id>", methods=["PATCH"])
def update_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json()
    assignment.title = data.get("title", assignment.title)
    assignment.description = data.get("description", assignment.description)
    assignment.deadline_iso = data.get("deadline_iso", assignment.deadline_iso)
    assignment.status = data.get("status", assignment.status)
    db.session.commit()
    return jsonify({"message": "Assignment updated"})

@app.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
def delete_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    db.session.delete(assignment)
    db.session.commit()
    return jsonify({"message": "Assignment deleted"})

# ----------------
# ASSIGNMENT SUBMISSIONS
# ----------------
@app.route("/api/assignments/<assignment_id>/submissions", methods=["PUT"])
def update_submission(assignment_id):
    user_code = request.form.get("user_code")
    if not user_code:
        return jsonify({"error": "user_code required"}), 400

    folder = os.path.join(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], assignment_id, user_code)
    os.makedirs(folder, exist_ok=True)
    metadata_path = os.path.join(folder, "metadata.json")

    metadata = {}
    if os.path.exists(metadata_path):
        with open(metadata_path) as f:
            metadata = json.load(f)

    if "file" in request.files:
        file = request.files["file"]
        filename = save_file(file, folder)
        metadata["file"] = filename
        metadata["updated_at"] = datetime.utcnow().isoformat()

    if "description" in request.form:
        metadata["description"] = request.form["description"]

    with open(metadata_path, "w") as f:
        json.dump(metadata, f)

    return jsonify({"message": "Submission updated", "metadata": metadata})

@app.route("/api/assignments/<assignment_id>/submissions", methods=["DELETE"])
def delete_submission(assignment_id):
    user_code = request.args.get("user_code")
    if not user_code:
        return jsonify({"error": "user_code required"}), 400
    folder = os.path.join(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], assignment_id, user_code)
    if os.path.exists(folder):
        shutil.rmtree(folder)
        return jsonify({"message": f"Submission deleted for user {user_code}"})
    return jsonify({"error": "Submission not found"}), 404

# ----------------
# Run App
# ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
