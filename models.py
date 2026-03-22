from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'Users'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    failed_attempts = db.Column(db.Integer, default=0)
    is_locked = db.Column(db.Boolean, default=False)
    reset_token = db.Column(db.String(255), nullable=True)
    reset_expires = db.Column(db.DateTime, nullable=True)

    student_profile = db.relationship('Student', backref='user', uselist=False)
    admin_profile = db.relationship('Admin', backref='user', uselist=False)


class Student(db.Model):
    __tablename__ = 'Students'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, unique=True)
    student_number = db.Column(db.String(50), unique=True, nullable=False)
    faculty_name = db.Column(db.String(100), nullable=False)
    department_name = db.Column(db.String(100), nullable=False)
    level_of_study = db.Column(db.String(50), nullable=False)

    applications = db.relationship('Application', backref='student', lazy=True)

class Admin(db.Model):
    __tablename__ = 'Admins'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, unique=True)
    staff_number = db.Column(db.String(50), unique=True, nullable=True)
    department = db.Column(db.String(100), nullable=True)



class Scholarship(db.Model):
    __tablename__ = 'Scholarships'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    requirements = db.Column(db.Text, nullable=False)
    deadline = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    department = db.Column(db.String(100), nullable=False) 
    level_of_study = db.Column(db.String(50), nullable=False)
    
    applications = db.relationship('Application', backref='scholarship', lazy=True)


class Application(db.Model):
    __tablename__ = 'Applications'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.id'), nullable=False)
    scholarship_id = db.Column(db.Integer, db.ForeignKey('Scholarships.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='Submitted')
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    reason = db.Column(db.Text, nullable=True)
    form = db.relationship('ApplicationForm', backref='application', uselist=False)


class Notification(db.Model):
    __tablename__ = 'Notifications'
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.Text, nullable=False)
    recipient_role = db.Column(db.String(20), nullable=False)

class Document(db.Model):
    __tablename__ = 'Documents'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class ProfileDocument(db.Model):
    __tablename__ = 'ProfileDocuments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.id'), nullable=False)
    doc_type = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(255), nullable=False)
    is_certified = db.Column(db.Boolean, default=False)
    certified_date = db.Column(db.Date, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class ApplicationForm(db.Model):
    __tablename__ = 'ApplicationForms'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('Applications.id'), nullable=False, unique=True)

    # Part 1: Personal Information
    full_name = db.Column(db.String(150), nullable=False)
    date_of_birth = db.Column(db.String(20), nullable=True)
    nationality = db.Column(db.String(100), nullable=True)
    country_of_residence = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), nullable=False)
    phone_number = db.Column(db.String(30), nullable=True)
    mailing_address = db.Column(db.Text, nullable=True)
    linkedin_url = db.Column(db.String(255), nullable=True)
    portfolio_url = db.Column(db.String(255), nullable=True)
    is_phd_student = db.Column(db.Boolean, default=False)
    orcid_id = db.Column(db.String(100), nullable=True)

    # Part 2: Academic Background
    current_highest_degree = db.Column(db.String(150), nullable=True)
    current_degree_title = db.Column(db.String(150), nullable=True)
    current_institution_name = db.Column(db.String(150), nullable=True)
    current_location = db.Column(db.String(150), nullable=True)
    current_dates_attended = db.Column(db.String(150), nullable=True)
    current_gpa_grade = db.Column(db.String(100), nullable=True)
    thesis_dissertation_title = db.Column(db.String(255), nullable=True)
    supervisor_name = db.Column(db.String(150), nullable=True)

    previous_degree = db.Column(db.String(150), nullable=True)
    previous_degree_title = db.Column(db.String(150), nullable=True)
    previous_institution_name = db.Column(db.String(150), nullable=True)
    previous_location = db.Column(db.String(150), nullable=True)
    previous_dates_attended = db.Column(db.String(150), nullable=True)

    # Part 3: Proposed Course of Study
    program_applying_for = db.Column(db.String(150), nullable=True)
    proposed_level_of_study = db.Column(db.String(100), nullable=True)
    proposed_program_title = db.Column(db.String(200), nullable=True)
    proposed_universities = db.Column(db.Text, nullable=True)
    proposed_start_date = db.Column(db.String(50), nullable=True)
    anticipated_completion_date = db.Column(db.String(50), nullable=True)

    proposed_thesis_title = db.Column(db.String(255), nullable=True)
    research_question_aim = db.Column(db.Text, nullable=True)
    proposed_methodology = db.Column(db.Text, nullable=True)
    significance_expected_outcomes = db.Column(db.Text, nullable=True)
    potential_supervisors = db.Column(db.Text, nullable=True)

    motivation = db.Column(db.Text, nullable=True)
    career_goals = db.Column(db.Text, nullable=True)
    why_this_program_university = db.Column(db.Text, nullable=True)
    why_you = db.Column(db.Text, nullable=True)
    relevant_experiences = db.Column(db.Text, nullable=True)

    # Part 4: Supporting Information
    work_experience = db.Column(db.Text, nullable=True)
    research_experience = db.Column(db.Text, nullable=True)
    publications_presentations = db.Column(db.Text, nullable=True)
    volunteering_extracurricular = db.Column(db.Text, nullable=True)
    awards_prizes = db.Column(db.Text, nullable=True)
    skills_languages = db.Column(db.Text, nullable=True)

    # Part 5: Referees
    ref1_name_title = db.Column(db.String(150), nullable=True)
    ref1_institution = db.Column(db.String(150), nullable=True)
    ref1_department = db.Column(db.String(150), nullable=True)
    ref1_email = db.Column(db.String(120), nullable=True)
    ref1_phone = db.Column(db.String(30), nullable=True)
    ref1_relationship = db.Column(db.String(150), nullable=True)
    ref1_known_duration = db.Column(db.String(100), nullable=True)

    ref2_name_title = db.Column(db.String(150), nullable=True)
    ref2_institution = db.Column(db.String(150), nullable=True)
    ref2_department = db.Column(db.String(150), nullable=True)
    ref2_email = db.Column(db.String(120), nullable=True)
    ref2_phone = db.Column(db.String(30), nullable=True)
    ref2_relationship = db.Column(db.String(150), nullable=True)
    ref2_known_duration = db.Column(db.String(100), nullable=True)

    ref3_name_title = db.Column(db.String(150), nullable=True)
    ref3_institution = db.Column(db.String(150), nullable=True)
    ref3_department = db.Column(db.String(150), nullable=True)
    ref3_email = db.Column(db.String(120), nullable=True)
    ref3_phone = db.Column(db.String(30), nullable=True)
    ref3_relationship = db.Column(db.String(150), nullable=True)
    ref3_known_duration = db.Column(db.String(100), nullable=True)

    # Part 6: Attachments
    attachments_summary = db.Column(db.Text, nullable=True)

    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
