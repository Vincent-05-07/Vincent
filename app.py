import os
import psycopg2
from flask import Flask, request, jsonify, send_file
from io import BytesIO
from flask_cors import CORS  # <-- add this import

app = Flask(__name__)

# Only allow CORS for your dashboard origin on the image endpoints
CORS(app, resources={
    r"/get-images/*": {"origins": "http://127.0.0.1:5500"},
    r"/serve-image/*": {"origins": "http://127.0.0.1:5500"},
})

# Increase max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# 🔌 Database connection
def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT", "5432"),
        sslmode=os.getenv("PGSSLMODE", "require")
    )

# 🌐 Root route
@app.route('/')
def index():
    return jsonify({"message": "Flask API is live!"})

# ❤️ Health check
@app.route('/health', methods=['GET'])
def health_check():
    try:
        conn = get_connection()
        conn.close()
        return jsonify({"status": "healthy"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# 🖼️ Upload multiple images for a user
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

# 📁 Retrieve image URLs for a user
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

# 📤 Serve an actual image
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

# 🚀 Run the Flask app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
