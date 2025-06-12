from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError
import pytz
import os
import sqlalchemy

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# SQLite database configuration
db_path = os.path.join("C:\\Users\\hussa\\OneDrive\\Desktop\\SE Project\\flashcard_app\\flash_card_database.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_POOL_SIZE'] = 20
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'check_same_thread': False}}

db = SQLAlchemy(app)

# Define SQLAlchemy models
class User(db.Model):
    __tablename__ = 'login_details'
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

class Flashcard(db.Model):
    __tablename__ = 'flashcards'
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(255), nullable=False)
    answer = db.Column(db.String(255), nullable=False)
    hint = db.Column(db.String(255))
    results = db.Column(db.Integer, default=0)
    last_picked_time = db.Column(db.String(255), nullable=False)

class History(db.Model):
    __tablename__ = 'history'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Float)  # Adjust to Float if score is stored as a float

def create_user_flashcard_table(user_email):
    sanitized_email = user_email.replace('@', '_at_').replace('.', '_dot_')
    user_table_name = f"{sanitized_email}_flashcards"
    inspector = sqlalchemy.inspect(db.engine)
    if not inspector.has_table(user_table_name):
        try:
            db.session.execute(sqlalchemy.text(f"""
                CREATE TABLE IF NOT EXISTS "{user_table_name}" AS SELECT * FROM flashcards
            """))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return False, f'Failed to create table: {str(e)}'
    return True, None

@app.route('/')
def login_form():
    return render_template('login_signup.html')

@app.route('/', methods=['POST'])
def login_signup():
    if request.method == 'POST':
        if 'signup' in request.form:
            # Signup logic
            fullname = request.form['fullname']
            email = request.form['email']
            password = request.form['password']
            hashed_password = generate_password_hash(password, method='sha256')

            try:
                new_user = User(fullname=fullname, email=email, password=hashed_password)
                db.session.add(new_user)
                db.session.commit()

                # Create user-specific flashcards table for the new user
                success, message = create_user_flashcard_table(email)
                if not success:
                    flash(message, 'error')
                    return redirect(url_for('login_form'))

                flash('Signup successful! Please log in.', 'success')
                return redirect(url_for('login_form'))
            
            except sqlalchemy.exc.SQLAlchemyError as e:
                db.session.rollback()
                flash(f'Failed to sign up: {str(e)}', 'error')
                return redirect(url_for('login_form'))

        elif 'login' in request.form:
            # Login logic
            email = request.form['email']
            password = request.form['password']
            user = User.query.filter_by(email=email).first()

            if user is None:
                flash('User does not exist. Please sign up first.', 'error')
                return redirect(url_for('login_form'))

            if check_password_hash(user.password, password):
                session['user_id'] = user.id
                session['fullname'] = user.fullname
                session['email'] = user.email
                session['start_time'] = datetime.now()

                # Create user-specific flashcards table if not exists
                success, message = create_user_flashcard_table(user.email)
                if not success:
                    flash(message, 'error')
                    return redirect(url_for('login_form'))

                flash('Login successful!', 'success')
                return redirect(url_for('load_flashcards'))
            else:
                flash('Invalid email or password', 'error')
                return redirect(url_for('login_form'))

    # Default rendering of the form
    return render_template('login_signup.html')

@app.route('/logout', methods=['GET'])
def logout():
    session.clear()  # Clear session data
    flash('You have been logged out', 'info')
    return redirect(url_for('login_form'))

@app.route('/load_flashcards')
def load_flashcards():
    if 'email' in session:
        return render_template('load_flash_card.html')
    else:
        flash('Please log in to access flashcards', 'error')
        return redirect(url_for('login_form'))

@app.route('/get_flashcard', methods=['GET'])
def get_flashcard():
    user_email = session.get('email')
    
    if not user_email:
        return jsonify({'error': 'User not authenticated'})

    sanitized_email = user_email.replace('@', '_at_').replace('.', '_dot_')
    user_table_name = f"{sanitized_email}_flashcards"
    current_time = datetime.utcnow()

    try:
        # Check for flashcards with results < 2
        flashcard = db.session.execute(sqlalchemy.text(f"""
            SELECT * FROM "{user_table_name}" WHERE results < 2
            ORDER BY RANDOM() LIMIT 1
        """)).fetchone()
        
        if flashcard:
            flashcard_dict = {'question': flashcard.question}
            return jsonify(flashcard_dict)
        
        # If no flashcard found, check for flashcards with results >= 2 and last_picked_time older than 2 days
        flashcard = db.session.execute(sqlalchemy.text(f"""
            SELECT * FROM "{user_table_name}" WHERE results >= 2 AND last_picked_time <= '{(current_time - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')}'
            ORDER BY RANDOM() LIMIT 1
        """)).fetchone()

        if flashcard:
            # Reset results to 0
            db.session.execute(sqlalchemy.text(f"""
                UPDATE "{user_table_name}" SET results = 0 WHERE id = {flashcard.id}
            """))
            db.session.commit()
            flashcard_dict = {'question': flashcard.question}
            return jsonify(flashcard_dict)
        
        return jsonify({'error': 'No suitable flashcards available'})

    except sqlalchemy.exc.SQLAlchemyError as e:
        return jsonify({'error': f'Failed to fetch flashcard: {str(e)}'})


@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    user_email = session.get('email')

    if not user_email:
        return jsonify({'error': 'User not authenticated'})

    data = request.get_json()
    question = data.get('question')
    user_answer = data.get('userAnswer')

    sanitized_email = user_email.replace('@', '_at_').replace('.', '_dot_')
    user_table_name = f"{sanitized_email}_flashcards"

    try:
        # Fetch the flashcard
        flashcard = db.session.execute(text(f"""
            SELECT *, CAST(last_picked_time AS DATETIME) AS last_picked_time
            FROM "{user_table_name}" WHERE question = :question
        """), {'question': question}).fetchone()

        if not flashcard:
            return jsonify({'error': 'Flashcard not found'})

        correct = user_answer.strip().lower() == flashcard.answer.strip().lower()

        # Get current UTC date
        current_date = datetime.utcnow().date()

        # Get last picked time from flashcard and convert to date
        last_picked_date = flashcard.last_picked_time.date() if flashcard.last_picked_time else None

        # Update flashcard details based on the correctness of the answer and date check
        if correct and last_picked_date != current_date:
            new_results = flashcard.results + 1
        elif not correct:
            new_results = max(flashcard.results - 1, 0)
        else:
            new_results = flashcard.results  # No change if correct and same day

        new_last_picked_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        db.session.execute(text(f"""
            UPDATE "{user_table_name}"
            SET results = :results, last_picked_time = :last_picked_time
            WHERE id = :id
        """), {'results': new_results, 'last_picked_time': new_last_picked_time, 'id': flashcard.id})

        db.session.commit()

        return jsonify({'correct': correct, 'correctAnswer': flashcard.answer})

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to submit answer: {str(e)}'})
    
@app.route('/get_hint', methods=['POST'])
def get_hint():
    user_email = session.get('email')
    
    if not user_email:
        return jsonify({'error': 'User not authenticated'})

    data = request.get_json()
    question = data.get('question')
    
    sanitized_email = user_email.replace('@', '_at_').replace('.', '_dot_')
    user_table_name = f"{sanitized_email}_flashcards"

    try:
        flashcard = db.session.execute(sqlalchemy.text(f"""
            SELECT * FROM "{user_table_name}" WHERE question = :question
        """), {'question': question}).fetchone()

        if flashcard:
            return jsonify({'hint': flashcard.hint})
        else:
            return jsonify({'error': 'Hint not found'})

    except sqlalchemy.exc.SQLAlchemyError as e:
        return jsonify({'error': f'Failed to fetch hint: {str(e)}'})


@app.route('/view_history', methods=['GET'])
def view_history():
    user_email = session.get('email')

    if not user_email:
        return jsonify({'error': 'User not authenticated'})

    try:
        history_sessions = History.query.filter_by(email=user_email).order_by(History.timestamp.desc()).limit(10).all()

        if history_sessions:
            german_timezone = pytz.timezone('Europe/Berlin')
            history_data = [{
                'timestamp': session.timestamp.astimezone(german_timezone).strftime('%Y-%m-%d %H:%M:%S'),
                'score': float(session.score)  # Convert to float if necessary
            } for session in history_sessions]

            return jsonify({'history': history_data})

        else:
            return jsonify({'error': 'No history found for the user.'}), 404

    except sqlalchemy.exc.SQLAlchemyError as e:
        return jsonify({'error': f'Failed to fetch history: {str(e)}'})


@app.route('/save_history', methods=['POST'])
def save_history():
    if request.method == 'POST':
        data = request.get_json()
        score_percentage = data.get('score_percentage')

        user_email = session.get('email')

        if user_email is None or score_percentage is None:
            return jsonify({'error': 'Email or score_percentage missing.'}), 400

        try:
            new_history = History(email=user_email, score=score_percentage, timestamp=datetime.utcnow())
            db.session.add(new_history)
            db.session.commit()
            return jsonify({'message': 'History saved successfully.'}), 200

        except sqlalchemy.exc.SQLAlchemyError as e:
            db.session.rollback()
            return jsonify({'error': f'Failed to save history: {str(e)}'}), 500

    else:
        return jsonify({'error': 'Method not allowed.'}), 405


if __name__ == '__main__':
    app.run(debug=True)
