import os
import psycopg2
from flask import Flask, request, jsonify, send_file
from io import BytesIO
from flask_cors import CORS

app = Flask(__name__)

# Allow CORS for all origins for testing
CORS(app, resources={r"/*": {"origins": "*"}})

# Increase max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Database connection
def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT", "5432"),
        sslmode=os.getenv("PGSSLMODE", "require")
    )

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

# CREATE - Upload images
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

# READ - Get all images for a user
@app.route('/get-images/<user_code>', methods=['GET'])
def get_images(user_code):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT file_path FROM firm_images WHERE user_code = %s", (user_code,))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        base_url = request.host_url.rstrip('/')
        urls = [f"{base_url}/serve-image/{user_code}/{os.path.basename(row[0])}" for row in rows]

        return jsonify({"user_code": user_code, "file_paths": urls}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# READ - Serve a single image
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

        return send_file(BytesIO(row[0]), mimetype='image/jpeg')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# UPDATE - Replace an image
@app.route('/update-image/<user_code>/<filename>', methods=['PUT'])
def update_image(user_code, filename):
    if 'image' not in request.files:
        return jsonify({"error": "Missing image file"}), 400

    try:
        new_image = request.files['image']
        image_data = psycopg2.Binary(new_image.read())
        file_path = f"wil-firm-pics/{user_code}/{filename}"

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE firm_images
            SET image_data = %s
            WHERE user_code = %s AND file_path LIKE %s
        """, (image_data, user_code, f"%{filename}"))

        if cur.rowcount == 0:
            return jsonify({"error": "Image not found"}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"message": f"Image {filename} updated for {user_code}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# DELETE - Delete a specific image
@app.route('/delete-image/<user_code>/<filename>', methods=['DELETE'])
def delete_image(user_code, filename):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM firm_images
            WHERE user_code = %s AND file_path LIKE %s
        """, (user_code, f"%{filename}"))

        if cur.rowcount == 0:
            return jsonify({"error": "Image not found"}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"message": f"Image {filename} deleted for {user_code}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# DELETE - Delete all images for a user
@app.route('/delete-all-images/<user_code>', methods=['DELETE'])
def delete_all_images(user_code):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM firm_images WHERE user_code = %s", (user_code,))
        deleted_count = cur.rowcount

        if deleted_count == 0:
            return jsonify({"error": "No images found"}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"message": f"All {deleted_count} images deleted for {user_code}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
