from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from transformers import pipeline
import os
import pytz

# ---------------- APP INIT ----------------
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# ---------------- DATABASE CONFIG ----------------
db_path = "flash_card_database.db"
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ---------------- DATABASE MODELS ----------------
class User(db.Model):
    __tablename__ = 'login_details'
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

class History(db.Model):
    __tablename__ = 'history'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Float)

# ---------------- PROMPT GENERATORS ----------------
def few_shot_flashcard_prompt():
    return (
        "You are a German-English vocabulary tutor. Give one German word only. Do not explain or translate.\n\n"
        "Example 1:\nGerman: Hund\n\n"
        "Example 2:\nGerman: Apfel\n\n"
        "Now give another German word:\nGerman:"
    )

def few_shot_hint_prompt(word):
    return (
        "You are helping learners understand German vocabulary. Give short English hints.\n\n"
        "Word: Hund\nHint: A common pet that barks.\n"
        "Word: Apfel\nHint: A sweet red or green fruit.\n"
        f"Word: {word}\nHint:"
    )

def few_shot_verify_prompt(word, user_answer, correct_answer):
    return (
        "You are a vocabulary tutor. Accept small spelling mistakes and missing articles.\n\n"
        "Word: Hund\nUser: dog\nCorrect: dog\nResult: Yes\n"
        "Word: Apfel\nUser: a apple\nCorrect: apple\nResult: Yes\n"
        f"Word: {word}\nUser: {user_answer}\nCorrect: {correct_answer}\nResult:"
    )

# ---------------- ROUTES ----------------
@app.route('/')
def login_form():
    return render_template("login_signup.html")

@app.route('/', methods=['POST'])
def login_signup():
    if 'signup' in request.form:
        fullname = request.form['fullname']
        email = request.form['email']
        password = request.form['password']
        hashed = generate_password_hash(password, method='sha256')
        try:
            new_user = User(fullname=fullname, email=email, password=hashed)
            db.session.add(new_user)
            db.session.commit()
            flash("Signup successful. Please login.", "success")
        except:
            db.session.rollback()
            flash("Signup failed. Email might already be registered.", "error")
        return redirect(url_for('login_form'))

    elif 'login' in request.form:
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password, password):
            flash("Invalid credentials", "error")
            return redirect(url_for('login_form'))
        session['user_id'] = user.id
        session['fullname'] = user.fullname
        session['email'] = user.email
        return redirect(url_for('load_flashcards'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_form'))

@app.route('/load_flashcards')
def load_flashcards():
    if 'email' in session:
        return render_template("load_flash_card.html")
    return redirect(url_for('login_form'))

@app.route('/generate_flashcard')
def generate_flashcard():
    prompt = few_shot_flashcard_prompt()
    response = generate_llm(prompt, max_new_tokens=10)
    word = response.strip().split("German:")[-1].strip().split("\n")[0]
    return jsonify({"question": word})

@app.route('/get_hint', methods=['POST'])
def get_hint():
    data = request.get_json()
    word = data.get("question", "")
    prompt = few_shot_hint_prompt(word)
    response = generate_llm(prompt)
    return jsonify({"hint": response.strip().split("Hint:")[-1].strip()})

@app.route('/verify_answer', methods=['POST'])
def verify_answer():
    data = request.get_json()
    word = data.get("question")
    user_answer = data.get("user_answer")
    correct_translation = data.get("correct_answer", word)
    prompt = few_shot_verify_prompt(word, user_answer, correct_translation)
    response = generate_llm(prompt)
    verdict = "yes" in response.lower()
    return jsonify({"correct": verdict, "response": response.strip()})

@app.route('/save_history', methods=['POST'])
def save_history():
    data = request.get_json()
    score = data.get('score_percentage')
    email = session.get('email')
    if not email or score is None:
        return jsonify({'error': 'Missing info'}), 400
    try:
        new_entry = History(email=email, score=score, timestamp=datetime.utcnow())
        db.session.add(new_entry)
        db.session.commit()
        return jsonify({'message': 'Saved'}), 200
    except:
        db.session.rollback()
        return jsonify({'error': 'DB error'}), 500

@app.route('/view_history')
def view_history():
    email = session.get('email')
    if not email:
        return jsonify({'error': 'Not logged in'}), 401
    sessions = History.query.filter_by(email=email).order_by(History.timestamp.desc()).limit(10).all()
    tz = pytz.timezone('Europe/Berlin')
    return jsonify({
        'history': [{
            'timestamp': s.timestamp.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S'),
            'score': float(s.score)
        } for s in sessions]
    })

# ---------------- ENTRY POINT ----------------
if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()

    print("Device set to use cpu")

    # Load the Falcon model pipeline
    pipe = pipeline("text-generation", model="tiiuae/falcon-rw-1b", trust_remote_code=True)

    def generate_llm(prompt, max_new_tokens=50):
        result = pipe(prompt, max_new_tokens=max_new_tokens, do_sample=True, temperature=0.7, top_p=0.9)
        return result[0]["generated_text"]

    with app.app_context():
        db.create_all()

    app.run()
