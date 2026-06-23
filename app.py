import os
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai

app = Flask(__name__)
# Flask uses this to encrypt your login session cookies securely
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret-dev-key")

# Connect to the Supabase URL you added to Render
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Configure Gemini
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# ──── DATABASE MODELS ────
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    surahs = db.relationship('UserSurah', backref='user', lazy=True)

class UserSurah(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    surah_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default="in-pool")  # 'in-pool', 'due', 'not-added'
    history = db.Column(db.Text, default="[]") 

# Automatically build tables in Supabase if they don't exist yet
with app.app_context():
    db.create_all()

# ──── AUTHENTICATION ROUTES ────
@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    if User.query.filter_by(username=data.get('username')).first():
        return jsonify({"error": "Username already exists"}), 400
    
    hashed = generate_password_hash(data.get('password'))
    new_user = User(username=data.get('username'), password_hash=hashed)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get('username')).first()
    if user and check_password_hash(user.password_hash, data.get('password')):
        session['user_id'] = user.id
        return jsonify({"success": True})
    return jsonify({"error": "Invalid username or password"}), 401

@app.route('/api/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('home'))

# ──── SURAH TRACKING DATA ROUTES ────
@app.route('/api/surahs', methods=['GET', 'POST'])
def handle_surahs():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    if request.method == 'POST':
        data = request.json
        # Check if they already have this surah tracking profile
        existing = UserSurah.query.filter_by(user_id=session['user_id'], surah_name=data['name']).first()
        if existing:
            existing.status = data.get('status', existing.status)
            existing.history = data.get('history', existing.history)
        else:
            new_surah = UserSurah(user_id=session['user_id'], surah_name=data['name'], status=data.get('status', 'in-pool'), history=data.get('history', '[]'))
            db.session.add(new_surah)
        db.session.commit()
        return jsonify({"success": True})
    
    user_surahs = UserSurah.query.filter_by(user_id=session['user_id']).all()
    return jsonify([{"name": s.surah_name, "status": s.status, "history": s.history} for s in user_surahs])

# ──── CHAT / GEMINI ROUTE ────
@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(user_message)
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ──── HOMEPAGE ROUTING ────
@app.route('/')
def home():
    if 'user_id' not in session:
        return render_template('login.html')
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
