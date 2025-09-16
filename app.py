import os
import json
import shutil
from datetime import datetime
import psycopg2
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from io import BytesIO

# ----------------
# Flask Config
# ----------------
app = Flask(__name__)
# Increase max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# CORS
CORS(app, supports_credentials=True)

# ----------------
# Database Connection (from your first code)
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
# Helpers
# ----------------
def save_file_to_db(user_code, file_type, file_stream):
    """Saves a file's binary data to the database."""
    file_path = f"user_files/{user_code}/{file_type}_{datetime.utcnow().isoformat()}.bin"
    file_data = psycopg2.Binary(file_stream.read())
    
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_files (user_code, file_path, file_data)
            VALUES (%s, %s, %s)
            RETURNING file_path;
        """, (user_code, file_path, file_data))
        saved_file_path = cur.fetchone()[0]
        conn.commit()
        return saved_file_path
    finally:
        if conn:
            conn.close()

def get_file_from_db(user_code, filename):
    """Retrieves a file's binary data from the database."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT file_data FROM user_files
            WHERE user_code = %s AND file_path LIKE %s
            LIMIT 1;
        """, (user_code, f"%{filename}"))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        if conn:
            conn.close()

# ----------------
# Routes
# ----------------
@app.route('/')
def index():
    return jsonify({"message": "Merged Flask API is live!"})

@app.route('/health', methods=['GET'])
def health_check():
    try:
        conn = get_connection()
        conn.close()
        return jsonify({"status": "healthy"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# ----------------
# DOCUMENTS & ASSIGNMENTS CRUD (Refactored to use PostgreSQL)
# ----------------
@app.route("/documents", methods=["POST"])
def upload_documents():
    user_code = request.form.get("user_code")
    if not user_code or "cvFile" not in request.files or "idFile" not in request.files:
        return jsonify({"error": "user_code, CV and ID are required"}), 400

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Save files to DB and get their paths
        cv_path = save_file_to_db(user_code, "cv", request.files["cvFile"])
        id_path = save_file_to_db(user_code, "id", request.files["idFile"])

        cur.execute("""
            INSERT INTO documents (user_code, cv_path, id_path)
            VALUES (%s, %s, %s)
            RETURNING id;
        """, (user_code, cv_path, id_path))
        doc_id = cur.fetchone()[0]
        conn.commit()

        return jsonify({"message": "Documents uploaded", "id": doc_id}), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route("/documents/<user_code>", methods=["GET"])
def list_documents(user_code):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, cv_path, id_path FROM documents WHERE user_code = %s", (user_code,))
        docs = cur.fetchall()
        
        return jsonify([
            {"id": d[0], "cv_path": d[1], "id_path": d[2]} for d in docs
        ])
    finally:
        if conn:
            conn.close()

@app.route("/documents/<user_code>/<int:doc_id>/<string:filetype>", methods=["GET"])
def get_document(user_code, doc_id, filetype):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        if filetype == "cv":
            cur.execute("SELECT cv_path FROM documents WHERE user_code = %s AND id = %s", (user_code, doc_id))
        elif filetype == "id":
            cur.execute("SELECT id_path FROM documents WHERE user_code = %s AND id = %s", (user_code, doc_id))
        else:
            return jsonify({"error": "Invalid filetype"}), 400
        
        doc_path = cur.fetchone()
        if not doc_path:
            return jsonify({"error": "Document not found"}), 404
        
        file_data = get_file_from_db(user_code, os.path.basename(doc_path[0]))
        if not file_data:
            return jsonify({"error": "File data not found"}), 404

        return send_file(BytesIO(file_data), mimetype='application/octet-stream', as_attachment=True)
    finally:
        if conn:
            conn.close()
# NOTE: Other CRUD for Documents and Assignments would follow a similar pattern:
# - Connect to the database
# - Execute SQL queries
# - Commit changes or return data
# - Close the connection
# ----------------
# Run App
# ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
