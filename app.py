import os
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Root upload folder
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Allowed extensions (can be extended)
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "docx", "txt"}

# Ensure root uploads folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


# --- Utility ---
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def ensure_folder(folder):
    path = os.path.join(app.config["UPLOAD_FOLDER"], folder)
    os.makedirs(path, exist_ok=True)
    return path


# ------------------ CREATE ------------------
@app.route("/upload/<file_type>", methods=["POST"])
def upload_file(file_type):
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        folder = ensure_folder(file_type)
        filepath = os.path.join(folder, filename)
        file.save(filepath)
        return jsonify({
            "message": f"{file_type.capitalize()} uploaded successfully",
            "path": filepath
        }), 201

    return jsonify({"error": "File type not allowed"}), 400


# ------------------ READ ------------------
@app.route("/files/<file_type>", methods=["GET"])
def list_files(file_type):
    folder = os.path.join(app.config["UPLOAD_FOLDER"], file_type)
    if not os.path.exists(folder):
        return jsonify([])
    files = os.listdir(folder)
    return jsonify(files)


@app.route("/files/<file_type>/<filename>", methods=["GET"])
def get_file(file_type, filename):
    folder = os.path.join(app.config["UPLOAD_FOLDER"], file_type)
    if not os.path.exists(os.path.join(folder, filename)):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(folder, filename)


# ------------------ UPDATE ------------------
@app.route("/update/<file_type>/<filename>", methods=["PUT"])
def update_file(file_type, filename):
    folder = os.path.join(app.config["UPLOAD_FOLDER"], file_type)
    old_file_path = os.path.join(folder, filename)

    if not os.path.exists(old_file_path):
        return jsonify({"error": "File not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No new file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file and allowed_file(file.filename):
        os.remove(old_file_path)
        new_filename = secure_filename(file.filename)
        new_file_path = os.path.join(folder, new_filename)
        file.save(new_file_path)
        return jsonify({
            "message": f"{file_type.capitalize()} updated successfully",
            "new_path": new_file_path
        }), 200

    return jsonify({"error": "File type not allowed"}), 400


# ------------------ DELETE ------------------
@app.route("/delete/<file_type>/<filename>", methods=["DELETE"])
def delete_file(file_type, filename):
    folder = os.path.join(app.config["UPLOAD_FOLDER"], file_type)
    file_path = os.path.join(folder, filename)

    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    os.remove(file_path)
    return jsonify({"message": f"{file_type.capitalize()} deleted successfully"}), 200


# ------------------ NEW: GET IMAGES ------------------
@app.route("/get-images/<user_code>", methods=["GET"])
def get_images(user_code):
    """
    Return all images uploaded for a given user_code.
    Files are expected inside: uploads/images/<user_code>/
    """
    folder = os.path.join(app.config["UPLOAD_FOLDER"], "images", user_code)

    if not os.path.exists(folder):
        return jsonify({"file_paths": []})  # No images yet

    files = [f for f in os.listdir(folder) if allowed_file(f)]
    file_paths = [
        request.host_url.rstrip("/") + f"/files/images/{user_code}/{f}"
        for f in files
    ]
    return jsonify({"file_paths": file_paths})


# ------------------ RUN ------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
