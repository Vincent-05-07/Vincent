import os, json, shutil, psycopg2
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# ---------------- Flask Config ----------------
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['UPLOAD_FOLDER_DOCS'] = 'uploads/documents'
app.config['UPLOAD_FOLDER_ASSIGNMENTS'] = 'uploads/assignments'
os.makedirs(app.config['UPLOAD_FOLDER_DOCS'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///files.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
CORS(app)

# ---------------- PostgreSQL Connection ----------------
def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT", "5432"),
        sslmode=os.getenv("PGSSLMODE", "require")
    )

# ---------------- Models ----------------
class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(50), nullable=False)
    cv_filename = db.Column(db.String(255), nullable=False)
    id_filename = db.Column(db.String(255), nullable=False)

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lecture_id = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    deadline_iso = db.Column(db.String(50))
    status = db.Column(db.String(20), default="open")
    file_url = db.Column(db.String(255))

with app.app_context(): db.create_all()

# ---------------- Helpers ----------------
def save_file(file, folder):
    filename = secure_filename(file.filename)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    file.save(path)
    return filename

# ---------------- Health ----------------
@app.route('/')
def index(): return jsonify({"message": "Flask API is live!"})
@app.route('/health', methods=['GET'])
def health_check():
    try: conn=get_connection(); conn.close(); return jsonify({"status":"healthy"}),200
    except Exception as e: return jsonify({"status":"unhealthy","error":str(e)}),500

# ---------------- Documents CRUD ----------------
@app.route("/documents", methods=["POST"])
def upload_documents():
    user_code = request.form.get("user_code")
    if not user_code or "cvFile" not in request.files or "idFile" not in request.files:
        return jsonify({"error":"user_code, CV and ID required"}),400
    folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    doc = Document(user_code=user_code,
                   cv_filename=save_file(request.files["cvFile"], folder),
                   id_filename=save_file(request.files["idFile"], folder))
    db.session.add(doc); db.session.commit()
    return jsonify({"message":"Documents uploaded","id":doc.id}),201

@app.route("/documents/<user_code>", methods=["GET"])
def get_documents(user_code):
    docs = Document.query.filter_by(user_code=user_code).all()
    return jsonify([{"id":d.id,"cv_filename":d.cv_filename,"id_filename":d.id_filename} for d in docs])

@app.route("/documents/<user_code>/<int:doc_id>/<string:filetype>", methods=["GET"])
def serve_document(user_code, doc_id, filetype):
    doc = Document.query.filter_by(user_code=user_code,id=doc_id).first_or_404()
    folder = os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    if filetype=="cv": return send_from_directory(folder, doc.cv_filename)
    if filetype=="id": return send_from_directory(folder, doc.id_filename)
    return jsonify({"error":"Invalid filetype"}),400

@app.route("/documents/<user_code>/<int:doc_id>", methods=["PUT"])
def update_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code,id=doc_id).first_or_404()
    folder=os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    if "cvFile" in request.files: doc.cv_filename=save_file(request.files["cvFile"], folder)
    if "idFile" in request.files: doc.id_filename=save_file(request.files["idFile"], folder)
    db.session.commit(); return jsonify({"message":"Documents updated"})

@app.route("/documents/<user_code>/<int:doc_id>", methods=["DELETE"])
def delete_document(user_code, doc_id):
    doc = Document.query.filter_by(user_code=user_code,id=doc_id).first_or_404()
    folder=os.path.join(app.config['UPLOAD_FOLDER_DOCS'], user_code)
    os.remove(os.path.join(folder, doc.cv_filename))
    os.remove(os.path.join(folder, doc.id_filename))
    db.session.delete(doc); db.session.commit()
    return jsonify({"message":"Documents deleted"})

# ---------------- Assignments CRUD ----------------
@app.route("/api/assignments", methods=["POST"])
def create_assignment():
    data = request.form; lecture_id=data.get("lecture_id"); title=data.get("title"); deadline=data.get("deadline_iso")
    if not lecture_id or not title or not deadline: return jsonify({"error":"lecture_id,title,deadline required"}),400
    file_url=None
    if "file" in request.files:
        folder=os.path.join(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], lecture_id)
        os.makedirs(folder, exist_ok=True)
        file_url=f"{folder}/{secure_filename(request.files['file'].filename)}"
        request.files['file'].save(file_url)
    a = Assignment(lecture_id=lecture_id,title=title,description=data.get("description"),deadline_iso=deadline,file_url=file_url)
    db.session.add(a); db.session.commit(); return jsonify({"message":"Assignment created","id":a.id}),201

@app.route("/api/assignments", methods=["GET"])
def list_assignments():
    lecture_id=request.args.get("lecture_id"); q=Assignment.query
    if lecture_id: q=q.filter_by(lecture_id=lecture_id)
    return jsonify([{"id":a.id,"lecture_id":a.lecture_id,"title":a.title,"description":a.description,"deadline_iso":a.deadline_iso,"status":a.status,"file_url":a.file_url} for a in q.all()])

@app.route("/api/assignments/<int:assignment_id>", methods=["PATCH"])
def update_assignment(assignment_id):
    a=Assignment.query.get_or_404(assignment_id); d=request.get_json()
    a.title=d.get("title",a.title); a.description=d.get("description",a.description)
    a.deadline_iso=d.get("deadline_iso",a.deadline_iso); a.status=d.get("status",a.status)
    db.session.commit(); return jsonify({"message":"Assignment updated"})

@app.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
def delete_assignment(assignment_id):
    a=Assignment.query.get_or_404(assignment_id); db.session.delete(a); db.session.commit()
    return jsonify({"message":"Assignment deleted"})

# ---------------- Assignment Submissions ----------------
@app.route("/api/assignments/<assignment_id>/submissions", methods=["PUT"])
def update_submission(assignment_id):
    user_code=request.form.get("user_code"); 
    if not user_code: return jsonify({"error":"user_code required"}),400
    folder=os.path.join(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], assignment_id, user_code)
    os.makedirs(folder, exist_ok=True)
    metadata_path=os.path.join(folder,"metadata.json"); metadata={}
    if os.path.exists(metadata_path):
        with open(metadata_path,"r") as f: metadata=json.load(f)
    if "description" in request.form: metadata["description"]=request.form.get("description")
    metadata["updated_at"]=datetime.utcnow().isoformat()
    if "file" in request.files:
        f=request.files["file"]; filename=secure_filename(f.filename); f.save(os.path.join(folder,filename)); metadata["file"]=filename
    with open(metadata_path,"w") as f: json.dump(metadata,f)
    return jsonify({"message":"Submission updated","metadata":metadata})

@app.route("/api/assignments/<assignment_id>/submissions", methods=["DELETE"])
def delete_submission(assignment_id):
    user_code=request.args.get("user_code")
    if not user_code: return jsonify({"error":"user_code required"}),400
    folder=os.path.join(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], assignment_id, user_code)
    if not os.path.exists(folder): return jsonify({"error":"Submission not found"}),404
    shutil.rmtree(folder); return jsonify({"message":f"Submission deleted for user {user_code}"})

# ---------------- Images (PostgreSQL) ----------------
@app.route('/update-image/<user_code>/<filename>', methods=['PUT'])
def update_image(user_code, filename):
    if "file" not in request.files: return jsonify({"error":"No file uploaded"}),400
    new_file=request.files["file"]
    try:
        conn=get_connection(); cur=conn.cursor()
        cur.execute("SELECT id FROM firm_images WHERE user_code=%s AND file_path LIKE %s",(user_code,f"%{filename}"))
        row=cur.fetchone()
        if not row: return jsonify({"error":"Image not found"}),404
        cur.execute("UPDATE firm_images SET image_data=%s WHERE id=%s",(psycopg2.Binary(new_file.read()),row[0]))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"message":f"Image {filename} updated for user {user_code}"}),200
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route('/delete-image/<user_code>/<filename>', methods=['DELETE'])
def delete_image(user_code, filename):
    try:
        conn=get_connection(); cur=conn.cursor()
        cur.execute("DELETE FROM firm_images WHERE user_code=%s AND file_path LIKE %s",(user_code,f"%{filename}"))
        deleted=cur.rowcount; conn.commit(); cur.close(); conn.close()
        if deleted==0: return jsonify({"error":"Image not found"}),404
        return jsonify({"message":f"Image {filename} deleted for user {user_code}"}),200
    except Exception as e: return jsonify({"error":str(e)}),500

# ---------------- Run ----------------
if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)))
