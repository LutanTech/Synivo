import eventlet
eventlet.monkey_patch()
import os
import time
import base64
import json
import uuid
import secrets
import string
from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
CORS(app, resources={r"/*": {"origins": "*"}})

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///synivo.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")
MOCK_USERS = {
    "Lutan": "000000",
    "Mesh": "123456",
    "Admin": "000000"
}

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(50))
    message = db.Column(db.Text)
    timestamp = db.Column(db.Float, default=time.time)

shared_text = ""
current_editor = None
last_typing_time = 0

def generate_random_id(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def encode_user_token(username):
    user_data = {
        "user": username,
        "token_id": generate_random_id(24),
        "session_uuid": str(uuid.uuid4()),
        "exp": time.time() + 604800
    }
    return base64.b64encode(json.dumps(user_data).encode()).decode()

def decode_user_token(token):
    try:
        data = json.loads(base64.b64decode(token).decode())
        if data['exp'] < time.time():
            return None
        return data
    except:
        return None

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if username in MOCK_USERS and MOCK_USERS[username] == password:
        token = encode_user_token(username)
        return jsonify({
            "success": True,
            "user": username,
            "token": token
        })
    return jsonify({"success": False, "error": "Invalid credentials"}), 401

@app.route("/verify", methods=["POST"])
def verify():
    token = request.json.get("token")
    user_data = decode_user_token(token)
    if user_data:
        return jsonify({"success": True, "user": user_data['user']})
    return jsonify({"success": False}), 401

@app.route("/messages")
def get_messages():
    msgs = Chat.query.order_by(Chat.timestamp.asc()).all()
    return jsonify([{ "user": m.user, "message": m.message } for m in msgs])

@socketio.on("join")
def handle_join(data):
    emit("update_text", shared_text)
    emit("editor_status", current_editor, broadcast=True)

@socketio.on("request_edit")
def handle_request_edit(data):
    global current_editor, last_typing_time
    user = data.get("user")
    if current_editor is None:
        current_editor = user
        last_typing_time = time.time()
        emit("editor_status", current_editor, broadcast=True)

@socketio.on("text_update")
def handle_text_update(data):
    global shared_text, last_typing_time
    if data.get("user") == current_editor:
        shared_text = data.get("text", "")
        last_typing_time = time.time()
        emit("update_text", shared_text, broadcast=True)

@socketio.on("chat_message")
def handle_chat_message(data):
    user = data.get("user")
    message = data.get("message")
    if user and message:
        msg = Chat(user=user, message=message)
        db.session.add(msg)
        db.session.commit()
        emit("chat_message", data, broadcast=True)

@socketio.on("stop_edit")
def handle_stop_edit():
    global current_editor
    current_editor = None
    emit("editor_status", None, broadcast=True)

def idle_monitor():
    global current_editor, last_typing_time
    while True:
        socketio.sleep(5)
        if current_editor:
            if time.time() - last_typing_time > 60:
                current_editor = None
                socketio.emit("editor_status", None)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    socketio.start_background_task(idle_monitor)

    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)