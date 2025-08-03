import os
import psycopg2
from flask import Flask, request, jsonify

app = Flask(__name__)

# 🔌 Database connection function
def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT", "5432"),
        sslmode=os.getenv("PGSSLMODE", "require")
    )

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

        for index, image_file in enumerate(images, start=1):
            file_path = f"wil-firm-pics/{user_code}/image_{index}.jpg"
            image_data = image_file.read()

            cur.execute("""
                INSERT INTO firm_images (user_code, file_path, image_data)
                VALUES (%s, %s, %s)
            """, (user_code, file_path, psycopg2.Binary(image_data)))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "message": f"{len(images)} images saved for user {user_code}",
            "file_paths": [f"wil-firm-pics/{user_code}/image_{i+1}.jpg" for i in range(len(images))]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 📁 Retrieve image file paths by user_code
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

        return jsonify({
            "user_code": user_code,
            "file_paths": [row[0] for row in rows]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 🚀 Run the Flask app (Render-compatible)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))