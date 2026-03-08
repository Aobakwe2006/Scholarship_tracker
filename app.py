from flask import Flask, render_template,request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user, login_required
from models import db, Student, Admin, Scholarship, Application

app = Flask (__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:yourpassword@localhost/scholarship_db'
app.config['SECRET_KEY'] = 'your_secret_key_here'
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return Student.query.get(int(user_id) or Admin.query.get(int(user_id)))



# The Routings 


@app.route("/")
def index():
    all_scholarships = Scholarship.query.all()
    return render_template ("index.html, scholarship = all_scholarships")

@app.route('/apply/<int:scholarship_id>')
@login_required
def apply(scholarship_id):
    scholarship = Scholarship.query.get_or_404(scholarship_id)
    return render_template('apply.html', scholarship=scholarship)

@app.route("/login")
def login():
    return render_template ("login")

if __name__=="__main__":
    app.run(debug = True)
