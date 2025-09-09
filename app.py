import os
import psycopg2
from flask import Flask, request, jsonify, send_file, send_from_directory, url_for
from io import BytesIO
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime

# ----------------
# Flask Config
# ----------------
app = Flask(__name__)

# Max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Image upload folders for document handling
app.config['UPLOAD_FOLDER_DOCS'] = 'uploads/documents'
os.makedirs(app.config['UPLOAD_FOLDER_DOCS'], exist_ok=True)

# Submissions upload folder
app.config['UPLOAD_FOLDER_SUBMISSIONS'] = 'uploads/submissions'
os.makedirs(app.config['UPLOAD_FOLDER_SUBMISSIONS'], exist_ok=True)

# SQLAlchemy config for documents (change to Postgres if needed)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------
# CORS settings (keep existing + add API)
# ----------------
CORS(app, resources={
    r"/get-images/*": {"origins": "http://127.0.0.1:5500"},
    r"/serve-image/*": {"origins": "http://127.0.0.1:5500"},
    r"/documents/*": {"origins": "http://127.0.0.1:5500"},
    # allow API usage from frontend (adjust origin as needed)
    r"/api/*": {"origins": ["http://127.0.0.1:5500", "https://project-connect-x4ei.onrender.com", "http://localhost:5500"]},
    r"/submissions/*": {"origins": ["http://127.0.0.1:5500", "http://localhost:5500"]},
})

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
# SQLAlchemy Models (for documents + assignments + submissions)
# ----------------
class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), nullable=False)
    cv_filename = db.Column(db.String(255), nullable=False)
    id_filename = db.Column(db.String(255), nullable=False)

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    deadline = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    lecture_id = db.Column(db.String(50), nullable=False)  # lecture's user_code
    status = db.Column(db.String(50), default="open")  # open / closed
    file_name = db.Column(db.String(255), nullable=True)  # optional attachment filename

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    user_code = db.Column(db.String(50), nullable=False)  # student user code
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    file_name = db.Column(db.String(255), nullable=True)  # filename stored in uploads
    text_answer = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default="submitted")  # submitted / reviewed / graded
    grade = db.Column(db.String(64), nullable=True)
    feedback = db.Column(db.Text, nullable=True)

with app.app_context():
    db.create_all()

# ----------------
# Helper for documents & uploads
# ----------------
def save_file(file, folder):
    filename = secure_filename(file.filename)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    file.save(filepath)
    return filename

def build_file_url(path):
    # path should be a route path (not file system). We return absolute URL.
    base = request.host_url.rstrip('/')
    return f"{base}{path}"

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
# PICTURES (PostgreSQL)  -- unchanged
# ----------------
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
# DOCUMENTS (SQLAlchemy) -- unchanged
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
# ASSIGNMENTS API (new)
# ----------------

@app.route("/api/assignments", methods=["POST"])
def create_assignment():
    """
    Expects multipart/form-data (optional file) or JSON.
    Required fields: title, description, deadline_iso, lecture_id
    """
    try:
        # TODO: verify authentication / token here
        if request.content_type and request.content_type.startswith("multipart/form-data"):
            title = request.form.get("title")
            description = request.form.get("description")
            deadline_iso = request.form.get("deadline_iso")
            lecture_id = request.form.get("lecture_id")
            file = request.files.get("file")
        else:
            payload = request.get_json() or {}
            title = payload.get("title")
            description = payload.get("description")
            deadline_iso = payload.get("deadline_iso")
            lecture_id = payload.get("lecture_id")
            file = None

        if not (title and description and deadline_iso and lecture_id):
            return jsonify({"error": "title, description, deadline_iso and lecture_id are required"}), 400

        try:
            deadline = datetime.fromisoformat(deadline_iso)
        except Exception:
            # fallback parse
            deadline = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00")) if deadline_iso.endswith("Z") else datetime.fromisoformat(deadline_iso)

        filename = None
        if file:
            folder = os.path.join(app.config['UPLOAD_FOLDER_SUBMISSIONS'], "assignments", lecture_id)
            os.makedirs(folder, exist_ok=True)
            filename = save_file(file, folder)

        assignment = Assignment(
            title=title,
            description=description,
            deadline=deadline,
            lecture_id=lecture_id,
            file_name=filename
        )
        db.session.add(assignment)
        db.session.commit()

        # build file_url if present
        file_url = None
        if filename:
            # serving path for assignment attachment
            file_url = url_for('serve_assignment_file', lecture_id=lecture_id, filename=filename, _external=True)

        return jsonify({
            "id": assignment.id,
            "title": assignment.title,
            "description": assignment.description,
            "deadline_iso": assignment.deadline.isoformat(),
            "status": assignment.status,
            "lecture_id": assignment.lecture_id,
            "file_url": file_url
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/assignments", methods=["GET"])
def list_assignments():
    """
    Optional query param: lecture_id=...
    Returns a list of assignments for the lecture.
    """
    try:
        lecture_id = request.args.get("lecture_id")
        if lecture_id:
            assignments = Assignment.query.filter_by(lecture_id=lecture_id).order_by(Assignment.created_at.desc()).all()
        else:
            assignments = Assignment.query.order_by(Assignment.created_at.desc()).all()

        out = []
        for a in assignments:
            file_url = url_for('serve_assignment_file', lecture_id=a.lecture_id, filename=a.file_name, _external=True) if a.file_name else None
            out.append({
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "deadline_iso": a.deadline.isoformat(),
                "status": a.status,
                "lecture_id": a.lecture_id,
                "file_url": file_url
            })
        return jsonify(out), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/assignments/<int:assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    a = Assignment.query.get_or_404(assignment_id)
    file_url = url_for('serve_assignment_file', lecture_id=a.lecture_id, filename=a.file_name, _external=True) if a.file_name else None
    return jsonify({
        "id": a.id,
        "title": a.title,
        "description": a.description,
        "deadline_iso": a.deadline.isoformat(),
        "status": a.status,
        "lecture_id": a.lecture_id,
        "file_url": file_url
    }), 200

@app.route("/api/assignments/<int:assignment_id>", methods=["PATCH"])
def update_assignment(assignment_id):
    """
    Accepts JSON or multipart form
    Allowed fields: title, description, deadline_iso, status
    """
    try:
        a = Assignment.query.get_or_404(assignment_id)

        if request.content_type and request.content_type.startswith("multipart/form-data"):
            title = request.form.get("title")
            description = request.form.get("description")
            deadline_iso = request.form.get("deadline_iso")
            status = request.form.get("status")
            file = request.files.get("file")
        else:
            payload = request.get_json() or {}
            title = payload.get("title")
            description = payload.get("description")
            deadline_iso = payload.get("deadline_iso")
            status = payload.get("status")
            file = None

        if title:
            a.title = title
        if description:
            a.description = description
        if deadline_iso:
            try:
                a.deadline = datetime.fromisoformat(deadline_iso)
            except Exception:
                a.deadline = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00")) if deadline_iso.endswith("Z") else datetime.fromisoformat(deadline_iso)
        if status:
            a.status = status

        if file:
            # save new file in assignment folder (lecture scope)
            folder = os.path.join(app.config['UPLOAD_FOLDER_SUBMISSIONS'], "assignments", a.lecture_id)
            os.makedirs(folder, exist_ok=True)
            filename = save_file(file, folder)
            a.file_name = filename

        db.session.commit()

        file_url = url_for('serve_assignment_file', lecture_id=a.lecture_id, filename=a.file_name, _external=True) if a.file_name else None
        return jsonify({
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "deadline_iso": a.deadline.isoformat(),
            "status": a.status,
            "lecture_id": a.lecture_id,
            "file_url": file_url
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Serve assignment attachment file (if any)
@app.route("/api/assignments/files/<lecture_id>/<filename>", methods=["GET"])
def serve_assignment_file(lecture_id, filename):
    folder = os.path.join(app.config['UPLOAD_FOLDER_SUBMISSIONS'], "assignments", lecture_id)
    if not os.path.exists(os.path.join(folder, filename)):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(folder, filename, as_attachment=False)

# ----------------
# SUBMISSIONS API (new)
# ----------------

@app.route("/api/assignments/<int:assignment_id>/submissions", methods=["POST"])
def submit_assignment(assignment_id):
    """
    Student submits for an assignment.
    Accepts multipart/form-data:
      - user_code (required)
      - file (optional)
      - text_answer (optional)
    """
    try:
        assignment = Assignment.query.get_or_404(assignment_id)
        user_code = request.form.get("user_code")
        text_answer = request.form.get("text_answer")
        file = request.files.get("file")

        if not user_code:
            return jsonify({"error": "user_code is required"}), 400

        filename = None
        if file:
            sub_folder = os.path.join(app.config['UPLOAD_FOLDER_SUBMISSIONS'], str(assignment_id), user_code)
            os.makedirs(sub_folder, exist_ok=True)
            filename = save_file(file, sub_folder)

        submission = Submission(
            assignment_id=assignment_id,
            user_code=user_code,
            file_name=filename,
            text_answer=text_answer,
            status="submitted"
        )
        db.session.add(submission)
        db.session.commit()

        file_url = None
        if filename:
            file_url = url_for('serve_submission_file', assignment_id=assignment_id, user_code=user_code, filename=filename, _external=True)

        return jsonify({
            "id": submission.id,
            "assignment_id": submission.assignment_id,
            "user_code": submission.user_code,
            "submitted_at": submission.submitted_at.isoformat(),
            "file_url": file_url,
            "text_answer": submission.text_answer,
            "status": submission.status
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/assignments/<int:assignment_id>/submissions", methods=["GET"])
def list_submissions(assignment_id):
    """
    Lecturer lists submissions for an assignment.
    Optional filter: user_code=...
    """
    try:
        assignment = Assignment.query.get_or_404(assignment_id)
        user_code_filter = request.args.get("user_code")

        query = Submission.query.filter_by(assignment_id=assignment_id)
        if user_code_filter:
            query = query.filter_by(user_code=user_code_filter)
        subs = query.order_by(Submission.submitted_at.desc()).all()

        out = []
        for s in subs:
            file_url = url_for('serve_submission_file', assignment_id=assignment_id, user_code=s.user_code, filename=s.file_name, _external=True) if s.file_name else None
            out.append({
                "id": s.id,
                "assignment_id": s.assignment_id,
                "user_code": s.user_code,
                "submitted_at": s.submitted_at.isoformat(),
                "file_url": file_url,
                "text_answer": s.text_answer,
                "status": s.status,
                "grade": s.grade,
                "feedback": s.feedback
            })
        return jsonify(out), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/assignments/<int:assignment_id>/submissions/<int:submission_id>", methods=["GET"])
def get_submission(assignment_id, submission_id):
    s = Submission.query.filter_by(assignment_id=assignment_id, id=submission_id).first_or_404()
    file_url = url_for('serve_submission_file', assignment_id=assignment_id, user_code=s.user_code, filename=s.file_name, _external=True) if s.file_name else None
    return jsonify({
        "id": s.id,
        "assignment_id": s.assignment_id,
        "user_code": s.user_code,
        "submitted_at": s.submitted_at.isoformat(),
        "file_url": file_url,
        "text_answer": s.text_answer,
        "status": s.status,
        "grade": s.grade,
        "feedback": s.feedback
    }), 200

@app.route("/api/assignments/<int:assignment_id>/submissions/<int:submission_id>", methods=["PATCH"])
def update_submission(assignment_id, submission_id):
    """
    Lecturer updates submission: status / grade / feedback
    Accepts JSON { status, grade, feedback }
    """
    try:
        s = Submission.query.filter_by(assignment_id=assignment_id, id=submission_id).first_or_404()
        payload = request.get_json() or {}
        status = payload.get("status")
        grade = payload.get("grade")
        feedback = payload.get("feedback")

        if status:
            s.status = status
        if grade:
            s.grade = grade
        if feedback:
            s.feedback = feedback

        db.session.commit()
        return jsonify({"message": "Submission updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/submissions/file/<int:assignment_id>/<user_code>/<filename>", methods=["GET"])
def serve_submission_file(assignment_id, user_code, filename):
    folder = os.path.join(app.config['UPLOAD_FOLDER_SUBMISSIONS'], str(assignment_id), user_code)
    path = os.path.join(folder, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(folder, filename, as_attachment=False)

# ----------------
# Run
# ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
