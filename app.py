from flask import Flask, render_template_string, request, jsonify, redirect, url_for, flash, session
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

# ---------------- LLM MODEL ----------------
pipe = pipeline("text-generation", model="tiiuae/falcon-rw-1b", trust_remote_code=True)

def generate_llm(prompt, max_new_tokens=50):
    result = pipe(prompt, max_new_tokens=max_new_tokens, do_sample=True, temperature=0.7, top_p=0.9)
    return result[0]["generated_text"]

# ---------------- PROMPTS ----------------
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
    return render_template_string('''
        <h2>Login or Signup</h2>
        <form method="post">
            Full Name (Signup): <input name="fullname"><br>
            Email: <input name="email"><br>
            Password: <input name="password" type="password"><br>
            <button name="signup" type="submit">Signup</button>
            <button name="login" type="submit">Login</button>
        </form>
    ''')

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
            return redirect(url_for('login_form'))
        except:
            db.session.rollback()
            return "Signup failed."
    elif 'login' in request.form:
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password, password):
            return "Login failed."
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
        return render_template_string('''
            <h3>Flashcard Trainer</h3>
            <button onclick="fetchWord()">New Word</button>
            <p id="question">Question:</p>
            <input id="user_input"><button onclick="verify()">Check</button>
            <p id="hint"></p>
            <script>
                let currentWord = "";
                async function fetchWord() {
                    const res = await fetch("/generate_flashcard");
                    const data = await res.json();
                    currentWord = data.question;
                    document.getElementById("question").innerText = "Question: " + currentWord;
                }
                async function verify() {
                    const user = document.getElementById("user_input").value;
                    const res = await fetch("/verify_answer", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({question: currentWord, user_answer: user, correct_answer: currentWord})
                    });
                    const data = await res.json();
                    alert(data.correct ? "Correct!" : "Try again. " + data.response);
                }
            </script>
        ''')
    return redirect(url_for('login_form'))

@app.route('/generate_flashcard')
def generate_flashcard():
    prompt = few_shot_flashcard_prompt()
    response = generate_llm(prompt, max_new_tokens=10)
    word = response.strip().split("German:")[-1].strip().split("\n")[0]
    return jsonify({"question": word})

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

# ---------------- MAIN ----------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Ensures tables are created
    app.run()
