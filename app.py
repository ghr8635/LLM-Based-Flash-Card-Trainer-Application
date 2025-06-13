from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import pytz
import sqlalchemy
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Database config
db_path = os.path.join("C:\\Users\\hussa\\OneDrive\\Desktop\\SE Project\\flashcard_app\\flash_card_database.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'check_same_thread': False}}
db = SQLAlchemy(app)

# Models
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

# ---------------- LLM LOADING ----------------
model_id = "meta-llama/Llama-2-7b-chat-hf"
access_token = "hf_xxx_your_token_here"
tokenizer = AutoTokenizer.from_pretrained(model_id, use_auth_token=access_token)
model = AutoModelForCausalLM.from_pretrained(model_id, use_auth_token=access_token, device_map="auto", torch_dtype="auto")
model.eval()

def generate_llm(prompt, max_new_tokens=50):
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True, temperature=0.7, top_p=0.95)
    return tokenizer.decode(output[0], skip_special_tokens=True)

# ---------------- LLM PROMPTS ----------------
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
        "Example:\nWord: Hund\nHint: A common pet that barks.\n\n"
        "Word: Apfel\nHint: A sweet red or green fruit.\n\n"
        f"Word: {word}\nHint:"
    )

def few_shot_verify_prompt(word, user_answer, correct_answer):
    return (
        "You are a vocabulary tutor. Accept small spelling mistakes and missing articles.\n\n"
        "Example:\nWord: Hund\nUser: dog\nCorrect: dog\nResult: Yes\n\n"
        "Word: Apfel\nUser: a apple\nCorrect: apple\nResult: Yes\n\n"
        f"Word: {word}\nUser: {user_answer}\nCorrect: {correct_answer}\nResult:"
    )

# ---------------- ROUTES ----------------
@app.route('/')
def login_form():
    return render_template('login_signup.html')

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
            flash('Signup successful! Please log in.', 'success')
        except sqlalchemy.exc.SQLAlchemyError as e:
            db.session.rollback()
            flash(f'Signup failed: {str(e)}', 'error')
        return redirect(url_for('login_form'))

    elif 'login' in request.form:
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if not user:
            flash('User does not exist.', 'error')
            return redirect(url_for('login_form'))
        if check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['fullname'] = user.fullname
            session['email'] = user.email
            flash('Login successful!', 'success')
            return redirect(url_for('load_flashcards'))
        else:
            flash('Invalid credentials.', 'error')
            return redirect(url_for('login_form'))

@app.route('/logout', methods=['GET'])
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('login_form'))

@app.route('/load_flashcards')
def load_flashcards():
    if 'email' in session:
        return render_template('load_flash_card.html')
    flash('Please log in.', 'error')
    return redirect(url_for('login_form'))

@app.route('/generate_flashcard', methods=['GET'])
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
    correct_translation = data.get("correct_answer", word)  # placeholder match

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
        return jsonify({'error': 'Missing info.'}), 400
    try:
        new_entry = History(email=email, score=score, timestamp=datetime.utcnow())
        db.session.add(new_entry)
        db.session.commit()
        return jsonify({'message': 'Saved.'}), 200
    except:
        db.session.rollback()
        return jsonify({'error': 'DB error'}), 500

@app.route('/view_history')
def view_history():
    email = session.get('email')
    if not email:
        return jsonify({'error': 'Not logged in'})
    sessions = History.query.filter_by(email=email).order_by(History.timestamp.desc()).limit(10).all()
    tz = pytz.timezone('Europe/Berlin')
    return jsonify({
        'history': [{
            'timestamp': s.timestamp.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S'),
            'score': float(s.score)
        } for s in sessions]
    })

if __name__ == '__main__':
    app.run(debug=True)
