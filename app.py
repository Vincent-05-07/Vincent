import os
import uuid
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from flask_cors import CORS

# ----------------
# Config
# ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
# absolute folders
app.config['UPLOAD_FOLDER_IMAGES'] = os.path.join(BASE_DIR, 'uploads', 'images')
app.config['UPLOAD_FOLDER_DOCS'] = os.path.join(BASE_DIR, 'uploads', 'documents')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'files.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

# Allow CORS from your front-end origin(s) - change as needed
CORS(app, resources={r"/*": {"origins": ["http://127.0.0.1:5500", "https://your-frontend-domain.com", "https://project-connect-x4ei.onrender.com"]}})

os.makedirs(app.config['UPLOAD_FOLDER_IMAGES'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_DOCS'], exist_ok=True)

db = SQLAlchemy(app)

# ----------------
# Database Models
# ----------------
class Picture(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(255), nullable=False)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), nullable=False)
    cv_filename = db.Column(db.String(255), nullable=False)
    id_filename = db.Column(db.String(255), nullable=False)

with app.app_context():
    db.create_all()

# ----------------
# Helpers
# ----------------
def save_file(file, folder, prefix=None):
    filename = secure_filename(file.filename)
    if prefix:
        filename = f"{prefix}_{filename}"
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    file.save(filepath)
    return filename

def make_full_url(path):
    return f"{request.host_url.rstrip('/')}{path}"

# ----------------
# Images API (compatibility with old API)
# ----------------

# Upload multiple images (POST /upload-images)
# form fields: user_code, images (multiple)
@app.route('/upload-images', methods=['POST'])
def upload_images():
    user_code = request.form.get('user_code')
    images = request.files.getlist('images')
    if not user_code or not images:
        return jsonify({"error": "Missing user_code or images"}), 400

    try:
        user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
        file_paths = []
        for img in images:
            # prefix with uuid to avoid collisions
            unique_prefix = uuid.uuid4().hex
            filename = save_file(img, user_folder, prefix=unique_prefix)
            # store DB record
            pic = Picture(user_code=user_code, filename=filename)
            db.session.add(pic)
            db.session.flush()  # get id if needed
            file_paths.append(f"{request.host_url.rstrip('/')}/serve-image/{user_code}/{filename}")
        db.session.commit()
        return jsonify({"message": f"{len(images)} images uploaded", "file_paths": file_paths}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# Get image URLs for a user (GET /get-images/<user_code>)
@app.route('/get-images/<user_code>', methods=['GET'])
def get_images(user_code):
    try:
        pics = Picture.query.filter_by(user_code=user_code).all()
        urls = [f"{request.host_url.rstrip('/')}/serve-image/{p.user_code}/{p.filename}" for p in pics]
        return jsonify({"user_code": user_code, "file_paths": urls}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Serve the actual image (GET /serve-image/<user_code>/<filename>)
@app.route('/serve-image/<user_code>/<filename>', methods=['GET'])
def serve_image(user_code, filename):
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
    # send_from_directory handles path traversal protection
    return send_from_directory(user_folder, filename)

# Individual picture CRUD (optional endpoints kept for parity)
@app.route("/pictures", methods=["POST"])
def upload_picture_single():
    user_code = request.form.get("user_code")
    if not user_code or "image" not in request.files:
        return jsonify({"error": "user_code and image are required"}), 400
    image = request.files["image"]
    try:
        user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
        filename = save_file(image, user_folder, prefix=uuid.uuid4().hex)
        new_pic = Picture(user_code=user_code, filename=filename)
        db.session.add(new_pic)
        db.session.commit()
        return jsonify({"message": "Image uploaded", "id": new_pic.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/pictures/<user_code>", methods=["GET"])
def list_pictures(user_code):
    pics = Picture.query.filter_by(user_code=user_code).all()
    return jsonify([{"id": p.id, "filename": p.filename} for p in pics])

@app.route("/pictures/<user_code>/<int:pic_id>", methods=["GET"])
def get_picture_by_id(user_code, pic_id):
    pic = Picture.query.filter_by(user_code=user_code, id=pic_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
    return send_from_directory(user_folder, pic.filename)

@app.route("/pictures/<user_code>/<int:pic_id>", methods=["PUT"])
def update_picture(user_code, pic_id):
    pic = Picture.query.filter_by(user_code=user_code, id=pic_id).first_or_404()
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    image = request.files["image"]
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
    filename = save_file(image, user_folder, prefix=uuid.uuid4().hex)
    pic.filename = filename
    db.session.commit()
    return jsonify({"message": "Image updated"})

@app.route("/pictures/<user_code>/<int:pic_id>", methods=["DELETE"])
def delete_picture(user_code, pic_id):
    pic = Picture.query.filter_by(user_code=user_code, id=pic_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
    try:
        os.remove(os.path.join(user_folder, pic.filename))
    except Exception:
        pass
    db.session.delete(pic)
    db.session.commit()
    return jsonify({"message": "Image deleted"})

# ----------------
# Documents API (CV + ID)
# ----------------

# Create documents (POST /documents) - cvFile, idFile, user_code
@app.route("/documents", methods=["POST"])
def upload_documents():
    user_code = request.form.get("user_code")
    if not user_code or "cvFile" not in request.files or "idFile" not in request.files:
        return jsonify({"error": "user_code, CV and ID are required"}), 400

    cv = request.files["cvFile"]
    id_doc = request.files["idFile"]

    try:
        user_folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
        cv_filename = save_file(cv, user_folder, prefix=uuid.uuid4().hex)
        id_filename = save_file(id_doc, user_folder, prefix=uuid.uuid4().hex)

        new_doc = Document(user_code=user_code, cv_filename=cv_filename, id_filename=id_filename)
        db.session.add(new_doc)
        db.session.commit()

        # Build full URLs for retrieval
        cv_url = f"{request.host_url.rstrip('/')}/serve-document/{user_code}/{new_doc.id}/cv"
        id_url = f"{request.host_url.rstrip('/')}/serve-document/{user_code}/{new_doc.id}/id"

        return jsonify({"message": "Documents uploaded", "id": new_doc.id, "cv_url": cv_url, "id_url": id_url}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# Read all documents for user - returns URLs
@app.route("/documents/<user_code>", methods=["GET"])
def get_documents(user_code):
    docs = Document.query.filter_by(user_code=user_code).all()
    items = []
    for d in docs:
        items.append({
            "id": d.id,
            "cv_url": f"{request.host_url.rstrip('/')}/serve-document/{user_code}/{d.id}/cv",
            "id_url": f"{request.host_url.rstrip('/')}/serve-document/{user_code}/{d.id}/id"
        })
    return jsonify(items)

# Serve document file (download)
@app.route("/serve-document/<user_code>/<int:doc_id>/<string:filetype>", methods=["GET"])
def serve_document(user_code, doc_id, filetype):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    if filetype == "cv":
        return send_from_directory(user_folder, doc.cv_filename, as_attachment=True)
    elif filetype == "id":
        return send_from_directory(user_folder, doc.id_filename, as_attachment=True)
    else:
        return jsonify({"error": "Invalid filetype. Use 'cv' or 'id'"}), 400

# Update document metadata/files
@app.route("/documents/<user_code>/<int:doc_id>", methods=["PUT"])
def update_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)

    if "cvFile" in request.files:
        cv = request.files["cvFile"]
        cv_filename = save_file(cv, user_folder, prefix=uuid.uuid4().hex)
        doc.cv_filename = cv_filename

    if "idFile" in request.files:
        id_doc = request.files["idFile"]
        id_filename = save_file(id_doc, user_folder, prefix=uuid.uuid4().hex)
        doc.id_filename = id_filename

    db.session.commit()
    return jsonify({"message": "Documents updated"})

# Delete document
@app.route("/documents/<user_code>/<int:doc_id>", methods=["DELETE"])
def delete_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code, id=doc_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    try:
        os.remove(os.path.join(user_folder, doc.cv_filename))
    except Exception:
        pass
    try:
        os.remove(os.path.join(user_folder, doc.id_filename))
    except Exception:
        pass
    db.session.delete(doc)
    db.session.commit()
    return jsonify({"message": "Documents deleted"})

# ----------------
# Health check
# ----------------
@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
