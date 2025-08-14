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

# SQLAlchemy config for documents (change to Postgres if needed)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------
# CORS settings
# ----------------
CORS(app, resources={
    r"/get-images/*": {"origins": "http://127.0.0.1:5500"},
    r"/serve-image/*": {"origins": "http://127.0.0.1:5500"},
    r"/documents/*": {"origins": "http://127.0.0.1:5500"}
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
# SQLAlchemy Models (for documents)
# ----------------
class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), nullable=False)
    cv_filename = db.Column(db.String(255), nullable=False)
    id_filename = db.Column(db.String(255), nullable=False)

with app.app_context():
    db.create_all()

# ----------------
# Helper for documents
# ----------------
def save_file(file, folder):
    filename = secure_filename(file.filename)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    file.save(filepath)
    return filename

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
# PICTURES (PostgreSQL)
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
# Run
# ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
