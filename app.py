import os
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# ----------------
# Config
# ----------------
app = Flask(__name__)
app.config['UPLOAD_FOLDER_IMAGES'] = 'uploads/images'
app.config['UPLOAD_FOLDER_DOCS'] = 'uploads/documents'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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
# Helper
# ----------------
def save_file(file, folder):
    filename = secure_filename(file.filename)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    file.save(filepath)
    return filename

# ----------------
# CRUD - Pictures
# ----------------

# Create
@app.route("/pictures", methods=["POST"])
def upload_picture():
    user_code = request.form.get("user_code")
    if not user_code or "image" not in request.files:
        return jsonify({"error": "user_code and image are required"}), 400

    image = request.files["image"]
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
    filename = save_file(image, user_folder)

    new_pic = Picture(user_code=user_code, filename=filename)
    db.session.add(new_pic)
    db.session.commit()
    return jsonify({"message": "Image uploaded", "id": new_pic.id}), 201

# Read all for user
@app.route("/pictures/<user_code>", methods=["GET"])
def get_pictures(user_code):
    pics = Picture.query.filter_by(user_code=user_code).all()
    return jsonify([{"id": p.id, "filename": p.filename} for p in pics])

# Read one
@app.route("/pictures/<user_code>/<int:pic_id>", methods=["GET"])
def get_picture(user_code, pic_id):
    pic = Picture.query.filter_by(user_code=user_code, id=pic_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
    return send_from_directory(user_folder, pic.filename)

# Update
@app.route("/pictures/<user_code>/<int:pic_id>", methods=["PUT"])
def update_picture(user_code, pic_id):
    pic = Picture.query.filter_by(user_code=user_code, id=pic_id).first_or_404()
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400

    image = request.files["image"]
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
    filename = save_file(image, user_folder)
    pic.filename = filename
    db.session.commit()
    return jsonify({"message": "Image updated"})

# Delete
@app.route("/pictures/<user_code>/<int:pic_id>", methods=["DELETE"])
def delete_picture(user_code, pic_id):
    pic = Picture.query.filter_by(user_code=user_code, id=pic_id).first_or_404()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], user_code)
    os.remove(os.path.join(user_folder, pic.filename))
    db.session.delete(pic)
    db.session.commit()
    return jsonify({"message": "Image deleted"})

# ----------------
# CRUD - Documents (CV + ID)
# ----------------

# Create
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

# Read all for user
@app.route("/documents/<user_code>", methods=["GET"])
def get_documents(user_code):
    docs = Document.query.filter_by(user_code=user_code).all()
    return jsonify([{
        "id": d.id,
        "cv_filename": d.cv_filename,
        "id_filename": d.id_filename
    } for d in docs])

# Read one (download CV or ID)
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

# Update
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

# Delete
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
# Health check
# ----------------
@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    app.run(debug=True)
