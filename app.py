# app.py - COMPLETE updated Flask app with all fixes
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, SelectField
from wtforms.validators import DataRequired, Length
from werkzeug.utils import secure_filename
from PIL import Image
import os
import secrets
from datetime import datetime

import os
from dotenv import load_dotenv
load_dotenv()



app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-fallback-super-secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Ensure directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Models
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False, default='Anonymous')
    content = db.Column(db.Text, nullable=False)
    image_file = db.Column(db.String(100), nullable=True)
    category = db.Column(db.String(20), default='social')  # 'problem' or 'social'
    thread_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # for problems

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=False)
    room = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Forms
class PostForm(FlaskForm):
    title = StringField('Title', validators=[Length(max=100)])
    content = TextAreaField('Content', validators=[DataRequired()])
    category = SelectField('Category', choices=[('social', 'Social'), ('problem', 'Problem')], default='social')
    submit = SubmitField('Post')

class ReportForm(FlaskForm):
    title = StringField('Problem Title', validators=[DataRequired(), Length(max=100)])
    content = TextAreaField('Description', validators=[DataRequired()])
    submit = SubmitField('Report')

class ChatJoinForm(FlaskForm):
    username = StringField('Username (anonymous)', validators=[DataRequired(), Length(min=1, max=50)])
    room = StringField('Room Code', validators=[DataRequired(), Length(min=1, max=50)])
    submit = SubmitField('Join Chat')

# Helper: Save & resize image
def save_image(form_image):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_image.filename)
    image_fn = random_hex + f_ext.lower()
    path = os.path.join(app.config['UPLOAD_FOLDER'], image_fn)
    
    i = Image.open(form_image)
    i.thumbnail((500, 500), Image.Resampling.LANCZOS)
    i.save(path, optimize=True, quality=85)
    return image_fn

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/social')
def social():
    threads = Post.query.filter_by(thread_id=None, category='social').order_by(Post.timestamp.desc()).limit(20).all()
    return render_template('social.html', threads=threads)

@app.route('/social/thread/<int:id>')
def thread(id):
    op_post = Post.query.get_or_404(id)
    posts = Post.query.filter_by(thread_id=id).order_by(Post.timestamp.asc()).all()
    return render_template('thread.html', op_post=op_post, posts=posts)

@app.route('/post', methods=['GET', 'POST'])
def post():
    form = PostForm()
    if request.method == 'POST':
        title = request.form.get('title', 'Anonymous')[:100]
        content = request.form.get('content', '')
        if not content.strip():
            flash('Content required!', 'error')
            return render_template('post.html', form=form)
        category = request.form.get('category', 'social')
        thread_id = request.form.get('thread_id')
        image_file = None
        
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                try:
                    image_file = save_image(file)
                except:
                    flash('Image upload failed!', 'error')
        
        new_post = Post(title=title, content=content, category=category,
                        thread_id=int(thread_id) if thread_id else None,
                        image_file=image_file)
        db.session.add(new_post)
        db.session.commit()
        flash('Posted anonymously!', 'success')
        
        if thread_id:
            return redirect(url_for('thread', id=int(thread_id)))
        elif category == 'problem':
            return redirect(url_for('index'))
        return redirect(url_for('social'))
    
    return render_template('post.html', form=form)

@app.route('/report', methods=['GET', 'POST'])
def report():
    form = ReportForm()
    if form.validate_on_submit():
        new_post = Post(title=form.title.data, content=form.content.data,
                        category='problem', status='pending')
        db.session.add(new_post)
        db.session.commit()
        flash('Report sent to authorities anonymously!', 'success')
        return redirect(url_for('index'))
    return render_template('report.html', form=form)

@app.route('/admin')
def admin():
    problems = Post.query.filter_by(category='problem').order_by(Post.timestamp.desc()).all()
    return render_template('admin.html', problems=problems)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['password'] == os.environ.get('ADMIN_PASSWORD') or 'admin123':
            session['admin_logged'] = True
            flash('Logged in!', 'success')
            return redirect(url_for('admin'))
        flash('Wrong password!', 'error')
    return render_template('admin_login.html')

@app.route('/admin/update/<int:post_id>', methods=['POST'])
def update_post(post_id):
    if not session.get('admin_logged'):
        flash('Admin login required!', 'error')
        return redirect(url_for('admin'))
    post = Post.query.get_or_404(post_id)
    post.status = request.form['status']
    db.session.commit()
    flash('Status updated!', 'success')
    return redirect(url_for('admin'))

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    form = ChatJoinForm()
    if form.validate_on_submit():
        session['chat_username'] = form.username.data
        session['chat_room'] = form.room.data
        return redirect(url_for('chat_room', room=form.room.data))
    return render_template('chat_join.html', form=form)

@app.route('/chat/<room>')
def chat_room(room):
    if 'chat_username' not in session or session['chat_room'] != room:
        return redirect(url_for('chat'))
    messages = ChatMessage.query.filter_by(room=room).order_by(ChatMessage.timestamp.asc()).limit(100).all()
    return render_template('chat_room.html', room=room, messages=messages, username=session['chat_username'])

# Socket.IO Events
@socketio.on('join')
def on_join():
    room = session.get('chat_room')
    if room:
        join_room(room)
        emit('status', {'msg': f"{session['chat_username']} joined the room"}, to=room)

@socketio.on('message')
def handle_message(data):
    room = session.get('chat_room')
    if room and data.get('message'):
        msg = ChatMessage(username=session['chat_username'], 
                         message=data['message'][:500],  # Limit length
                         room=room)
        db.session.add(msg)
        db.session.commit()
        emit('message', {'msg': f"{session['chat_username']}: {data['message']}"}, to=room)

@socketio.on('leave')
def on_leave():
    room = session.get('chat_room')
    username = session.get('chat_username', 'Someone')
    if room:
        leave_room(room)
        emit('status', {'msg': f"{username} left the room"}, to=room)
        session.pop('chat_username', None)
        session.pop('chat_room', None)
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
