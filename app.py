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
    filename = db.Column(db.String(255), nullable=False)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cv_filename = db.Column(db.String(255), nullable=False)
    id_filename = db.Column(db.String(255), nullable=False)

with app.app_context():
    db.create_all()

# ----------------
# Helper
# ----------------
def save_file(file, folder):
    filename = secure_filename(file.filename)
    filepath = os.path.join(folder, filename)
    file.save(filepath)
    return filename

# ----------------
# CRUD - Pictures
# ----------------

# Create
@app.route("/pictures", methods=["POST"])
def upload_picture():
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    image = request.files["image"]
    filename = save_file(image, app.config['UPLOAD_FOLDER_IMAGES'])
    new_pic = Picture(filename=filename)
    db.session.add(new_pic)
    db.session.commit()
    return jsonify({"message": "Image uploaded", "id": new_pic.id}), 201

# Read all
@app.route("/pictures", methods=["GET"])
def get_pictures():
    pics = Picture.query.all()
    return jsonify([{"id": p.id, "filename": p.filename} for p in pics])

# Read one
@app.route("/pictures/<int:pic_id>", methods=["GET"])
def get_picture(pic_id):
    pic = Picture.query.get_or_404(pic_id)
    return send_from_directory(app.config['UPLOAD_FOLDER_IMAGES'], pic.filename)

# Update
@app.route("/pictures/<int:pic_id>", methods=["PUT"])
def update_picture(pic_id):
    pic = Picture.query.get_or_404(pic_id)
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    image = request.files["image"]
    filename = save_file(image, app.config['UPLOAD_FOLDER_IMAGES'])
    pic.filename = filename
    db.session.commit()
    return jsonify({"message": "Image updated"})

# Delete
@app.route("/pictures/<int:pic_id>", methods=["DELETE"])
def delete_picture(pic_id):
    pic = Picture.query.get_or_404(pic_id)
    os.remove(os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], pic.filename))
    db.session.delete(pic)
    db.session.commit()
    return jsonify({"message": "Image deleted"})

# ----------------
# CRUD - Documents (CV + ID)
# ----------------

# Create
@app.route("/documents", methods=["POST"])
def upload_documents():
    if "cvFile" not in request.files or "idFile" not in request.files:
        return jsonify({"error": "Both CV and ID must be provided"}), 400
    cv = request.files["cvFile"]
    id_doc = request.files["idFile"]

    cv_filename = save_file(cv, app.config['UPLOAD_FOLDER_DOCS'])
    id_filename = save_file(id_doc, app.config['UPLOAD_FOLDER_DOCS'])

    new_doc = Document(cv_filename=cv_filename, id_filename=id_filename)
    db.session.add(new_doc)
    db.session.commit()
    return jsonify({"message": "Documents uploaded", "id": new_doc.id}), 201

# Read all
@app.route("/documents", methods=["GET"])
def get_documents():
    docs = Document.query.all()
    return jsonify([{
        "id": d.id,
        "cv_filename": d.cv_filename,
        "id_filename": d.id_filename
    } for d in docs])

# Read one (download CV or ID)
@app.route("/documents/<int:doc_id>/<string:filetype>", methods=["GET"])
def get_document(doc_id, filetype):
    doc = Document.query.get_or_404(doc_id)
    if filetype == "cv":
        return send_from_directory(app.config['UPLOAD_FOLDER_DOCS'], doc.cv_filename)
    elif filetype == "id":
        return send_from_directory(app.config['UPLOAD_FOLDER_DOCS'], doc.id_filename)
    else:
        return jsonify({"error": "Invalid filetype. Use 'cv' or 'id'"}), 400

# Update
@app.route("/documents/<int:doc_id>", methods=["PUT"])
def update_document(doc_id):
    doc = Document.query.get_or_404(doc_id)

    if "cvFile" in request.files:
        cv = request.files["cvFile"]
        cv_filename = save_file(cv, app.config['UPLOAD_FOLDER_DOCS'])
        doc.cv_filename = cv_filename

    if "idFile" in request.files:
        id_doc = request.files["idFile"]
        id_filename = save_file(id_doc, app.config['UPLOAD_FOLDER_DOCS'])
        doc.id_filename = id_filename

    db.session.commit()
    return jsonify({"message": "Documents updated"})

# Delete
@app.route("/documents/<int:doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    doc = Document.query.get_or_404(doc_id)
    os.remove(os.path.join(app.config['UPLOAD_FOLDER_DOCS'], doc.cv_filename))
    os.remove(os.path.join(app.config['UPLOAD_FOLDER_DOCS'], doc.id_filename))
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
