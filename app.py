import os
import json
from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai

app = Flask(__name__)
CORS(app, supports_credentials=True)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-prod")
db_url = os.environ.get("DATABASE_URL", "sqlite:///hifz_dev.db")
# pg8000 requires postgresql+pg8000:// dialect prefix
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+pg8000://", 1)
elif db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+pg8000://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get("FLASK_ENV") == "production"

db = SQLAlchemy(app)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# ──── MODELS ────
class User(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(80), unique=True, nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    hifz_data    = db.Column(db.Text, default='{}')

with app.app_context():
    db.create_all()

# ──── AUTH ────
@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json or {}
    username = data.get('username', '').strip()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not username or not email or not password:
        return jsonify({"error": "All fields are required."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already taken."}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists."}), 409

    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password)
    )
    db.session.add(user)
    db.session.commit()
    session['user_id'] = user.id
    session.permanent = True
    return jsonify({"success": True, "username": user.username})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    identifier = data.get('identifier', '').strip()  # username or email
    password   = data.get('password', '')

    user = (User.query.filter_by(username=identifier).first() or
            User.query.filter_by(email=identifier.lower()).first())

    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Incorrect username/email or password."}), 401

    session['user_id'] = user.id
    session.permanent = True
    return jsonify({"success": True, "username": user.username})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({"success": True})

@app.route('/api/me', methods=['GET'])
def me():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    user = db.session.get(User, session['user_id'])
    if not user:
        session.pop('user_id', None)
        return jsonify({"error": "User not found"}), 401
    return jsonify({"username": user.username, "email": user.email})

# ──── HIFZ DATA ────
@app.route('/api/data', methods=['GET'])
def get_data():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = db.session.get(User, session['user_id'])
    if not user:
        return jsonify({"error": "User not found"}), 401
    try:
        return jsonify({"data": json.loads(user.hifz_data or '{}')})
    except Exception:
        return jsonify({"data": {}})

@app.route('/api/data', methods=['POST'])
def save_data():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = db.session.get(User, session['user_id'])
    if not user:
        return jsonify({"error": "User not found"}), 401
    payload = request.json or {}
    state = payload.get('state')
    if state is None:
        return jsonify({"error": "No state provided"}), 400
    try:
        user.hifz_data = json.dumps(state)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# ──── ACCOUNT MANAGEMENT ────
@app.route('/api/account/update', methods=['POST'])
def account_update():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = db.session.get(User, session['user_id'])
    if not user:
        return jsonify({"error": "User not found"}), 401
    data = request.json or {}
    if 'name' in data:
        # Store display name in hifz_data profile
        import json as _json
        try:
            hd = _json.loads(user.hifz_data or '{}')
            hd.setdefault('profile', {})['name'] = data['name'].strip()
            user.hifz_data = _json.dumps(hd)
        except Exception:
            pass
    if 'username' in data:
        new_username = data['username'].strip()
        if not new_username:
            return jsonify({"error": "Username cannot be empty."}), 400
        existing = User.query.filter_by(username=new_username).first()
        if existing and existing.id != user.id:
            return jsonify({"error": "Username already taken."}), 409
        user.username = new_username
    if 'email' in data:
        new_email = data['email'].strip().lower()
        if not new_email:
            return jsonify({"error": "Email cannot be empty."}), 400
        existing = User.query.filter_by(email=new_email).first()
        if existing and existing.id != user.id:
            return jsonify({"error": "An account with this email already exists."}), 409
        user.email = new_email
    db.session.commit()
    return jsonify({"success": True, "username": user.username})

@app.route('/api/account/password', methods=['POST'])
def account_password():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = db.session.get(User, session['user_id'])
    if not user:
        return jsonify({"error": "User not found"}), 401
    data = request.json or {}
    current = data.get('currentPassword', '')
    new_pw = data.get('newPassword', '')
    if not check_password_hash(user.password_hash, current):
        return jsonify({"error": "Current password is incorrect."}), 401
    if len(new_pw) < 6:
        return jsonify({"error": "New password must be at least 6 characters."}), 400
    user.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/account/delete', methods=['POST'])
def account_delete():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = db.session.get(User, session['user_id'])
    if not user:
        return jsonify({"error": "User not found"}), 401
    data = request.json or {}
    if not check_password_hash(user.password_hash, data.get('password', '')):
        return jsonify({"error": "Incorrect password."}), 401
    db.session.delete(user)
    db.session.commit()
    session.pop('user_id', None)
    return jsonify({"success": True})

# ──── GEMINI ────
@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json() or {}
        user_message = data.get("message", "")
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(user_message)
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ──── SERVE APP ────
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/static/service-worker.js')
def service_worker():
    return app.send_static_file('service-worker.js'), 200, {
        'Content-Type': 'application/javascript',
        'Service-Worker-Allowed': '/'
    }

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
