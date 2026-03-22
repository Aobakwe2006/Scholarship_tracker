import os
import uuid
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from collections import defaultdict, deque


from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from sqlalchemy import or_
from werkzeug.utils import secure_filename
from models import db, User, Student, Admin, Scholarship, Application, ApplicationForm, Notification, Document, \
    ProfileDocument


app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///scholarship_tracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'mysecretkey'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB limit
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# If you run behind HTTPS, set this to True
app.config['SESSION_COOKIE_SECURE'] = False
# Email (read from environment; keeps secrets out of code)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', '587'))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME',
                                             'scolarshiptracker@gmail.com')  # e.g., scolarshiptracker@gmail.com
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'isoghhwafajyhnza')  # Gmail App Password (16 chars)
app.config['MAIL_FROM_NAME'] = os.environ.get('MAIL_FROM_NAME', 'Scholarship Tracker')

DEPARTMENT_LABELS = {
    'IT': 'Information Technology',
    'IS': 'Information Systems',
    'FIM': 'Finance and Information Management',
    'FA': 'Financial Accounting',
    'ICM': 'Information and Corporate Management',
    'MA': 'Management Accounting',
    'AT': 'Auditing and Taxation'
}

REQUIRED_PROFILE_DOCS = {
    'certified_id': 'Certified ID',
    'academic_record': 'Academic Record',
    'letter_of_completion': 'Letter of Completion',
    'proof_of_registration': 'Proof of Registration',
    'bank_statement': 'Bank Statement',
    'proof_of_residence': 'Proof of Residence'
}
# -----------------------------
# Models / DB setup
# -----------------------------
db.init_app(app)


# Ensure new security columns exist (SQLite-friendly)
def _ensure_user_security_columns():
    try:
        inspector = db.inspect(db.engine)
        cols = {c['name'] for c in inspector.get_columns('Users')}
        with db.engine.begin() as conn:
            if 'failed_attempts' not in cols:
                conn.execute(db.text("ALTER TABLE Users ADD COLUMN failed_attempts INTEGER DEFAULT 0"))
            if 'is_locked' not in cols:
                conn.execute(db.text("ALTER TABLE Users ADD COLUMN is_locked BOOLEAN DEFAULT 0"))
            if 'reset_token' not in cols:
                conn.execute(db.text("ALTER TABLE Users ADD COLUMN reset_token VARCHAR(255)"))
            if 'reset_expires' not in cols:
                conn.execute(db.text("ALTER TABLE Users ADD COLUMN reset_expires DATETIME"))
    except Exception:
        # if table doesn't exist yet or other issue, ignore; create_all will handle initial creation
        pass


# Ensure tables/columns exist when app imports (covers flask run)
with app.app_context():
    db.create_all()
    _ensure_user_security_columns()

# -----------------------------
# Simple in-memory rate limiter (per process)
# -----------------------------
_rate_windows = {
    'login': (5, 60),  # 5 requests per 60 seconds
    'register': (5, 60),
}
_rate_buckets = defaultdict(lambda: deque())


def _rate_limited(action_key, client_id):
    limit, window = _rate_windows.get(action_key, (0, 0))
    if limit == 0:
        return False
    bucket = _rate_buckets[(action_key, client_id)]
    now = datetime.utcnow().timestamp()
    # prune
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def _notify(role, message):
    """Light helper to create a notification for a role string."""
    note = Notification(message=message, recipient_role=role)
    db.session.add(note)
    db.session.commit()
    _notify_email(role, message)


def _notify_email(role, message):
    """Send email if mail creds are configured. role can be 'admin' or 'student:{id}'."""
    username = app.config['MAIL_USERNAME']
    password = app.config['MAIL_PASSWORD']
    if not username or not password:
        return  # email not configured
    _send_email(role, message, username, password)


def _send_email(role_or_recipients, message, username=None, password=None, subject="Scholarship Tracker Notification"):
    username = username or app.config['MAIL_USERNAME']
    password = password or app.config['MAIL_PASSWORD']
    if not username or not password:
        return

    recipients = []
    subject = "Scholarship Tracker Notification"

    role = role_or_recipients
    if isinstance(role_or_recipients, (list, tuple, set)):
        recipients = list(role_or_recipients)
    elif role == 'admin':
        admins = User.query.filter_by(role='admin').all()
        recipients = [a.email for a in admins if a.email]
    elif role.startswith('student:'):
        try:
            student_id = int(role.split(':')[1])
            student = Student.query.get(student_id)
            if student and student.user and student.user.email:
                recipients = [student.user.email]
        except (ValueError, IndexError):
            return
    else:
        return

    if not recipients:
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"{app.config['MAIL_FROM_NAME']} <{username}>"
    msg['To'] = ", ".join(recipients)
    msg.set_content(message)

    try:
        with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
            if app.config['MAIL_USE_TLS']:
                server.starttls()
            server.login(username, password)
            server.send_message(msg)
    except Exception as exc:
        # Log to console so we can debug email issues without breaking the app flow
        print(f"[EMAIL ERROR] {exc}")


@app.route("/")
def index():
    _refresh_scholarship_statuses()
    scholarships = Scholarship.query.filter_by(status='Open').all()
    return render_template('index.html', scholarships=scholarships)


# -----------------------------
# HOME ROUTE
# -----------------------------

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))

    return redirect(url_for('student_dashboard'))


# -----------------------------
# REGISTER STUDENT
# -----------------------------

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        client_id = request.remote_addr or 'anonymous'
        if _rate_limited('register', client_id):
            error = "Too many registration attempts. Please wait a moment and try again."
            return render_template('register.html', error=error)

        # Check POPI consent - server side validation
        popi_consent = request.form.get('popi_consent')
        if popi_consent != 'yes':
            error = "You must consent to the POPI Act to register."
            return render_template('register.html', error=error)

        full_name = request.form['full_name']
        student_number = request.form['student_number']
        faculty_name = request.form['faculty_name']
        department_name = request.form['department_name']
        level_of_study = request.form['level_of_study']
        email = request.form['email']
        phone_number = request.form['phone_number']
        password = request.form['password']

        issues = _password_issues(password)
        if issues:
            error = "Password must " + ", ".join(issues[:-1]) + (" and " if len(issues) > 1 else "") + issues[-1] + "."
            return render_template('register.html', error=error)

        # Basic format validation
        if not (student_number.isdigit() and len(student_number) == 8):
            error = "Student number must be exactly 8 digits."
        elif not (phone_number.isdigit() and len(phone_number) == 10):
            error = "Phone number must be exactly 10 digits."

        if error:
            return render_template('register.html', error=error)

        existing_user = User.query.filter(
            (User.email == email) | (User.phone_number == phone_number)
        ).first()

        if existing_user:
            error = "Email or phone number already exists. Please use another one."
            return render_template('register.html', error=error)

        existing_student = Student.query.filter_by(student_number=student_number).first()
        if existing_student:
            error = "Student number already exists."
            return render_template('register.html', error=error)

        new_user = User(
            full_name=full_name,
            email=email,
            phone_number=phone_number,
            password_hash=password,
            role='student'
        )

        db.session.add(new_user)
        db.session.commit()

        new_student = Student(
            user_id=new_user.id,
            student_number=student_number,
            faculty_name=faculty_name,
            department_name=department_name,
            level_of_study=level_of_study
        )

        db.session.add(new_student)
        db.session.commit()

        return redirect(url_for('login'))

    return render_template('register.html', error=error)


# -----------------------------
# LOGIN
# -----------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if request.method == 'POST':
        _ensure_user_security_columns()
        client_id = request.remote_addr or 'anonymous'
        if _rate_limited('login', client_id):
            error = "Too many login attempts. Please wait a moment and try again."
            return render_template('login.html', error=error)

        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and user.is_locked:
            error = "Account is locked due to too many failed attempts. Please contact admin."
        elif user and user.password_hash == password:
            user.failed_attempts = 0
            session.permanent = True
            session['user_id'] = user.id
            session['user_name'] = user.full_name
            session['role'] = user.role
            db.session.commit()

            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))

            return redirect(url_for('student_dashboard'))
        else:
            # login failed
            if user:
                user.failed_attempts = (user.failed_attempts or 0) + 1
                if user.failed_attempts >= 5:
                    user.is_locked = True
                    error = "Account locked after too many failed attempts. Contact admin to unlock."
                else:
                    error = "Invalid email or password"
                db.session.commit()
            else:
                error = "Invalid email or password"

    return render_template('login.html', error=error)


# -----------------------------
# STUDENT DASHBOARD
# -----------------------------

@app.route('/student_dashboard')
def student_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'student':
        return "Access denied"

    student = Student.query.filter_by(user_id=session['user_id']).first()

    return render_template(
        'student_dashboard.html',
        name=session.get('user_name'),
        student=student
    )


# -----------------------------
# STUDENT: VIEW & APPLY TO SCHOLARSHIPS
# -----------------------------

@app.route('/student/scholarships')
def student_scholarships():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'student':
        return "Access denied"

    _refresh_scholarship_statuses()
    user = User.query.get(session['user_id'])
    student = Student.query.filter_by(user_id=session['user_id']).first()

    student_dept = DEPARTMENT_LABELS.get(student.department_name, student.department_name)

    scholarships = Scholarship.query.filter_by(
        status='Open',
        department=student_dept
    ).all()

    existing_applications = {app.scholarship_id for app in student.applications}
    docs = ProfileDocument.query.filter_by(student_id=student.id).all()

    return render_template(
        'student_scholarships.html',
        user=user,
        student=student,
        scholarships=scholarships,
        existing_applications=existing_applications,
        docs=docs,
        message=request.args.get('message')
    )


@app.route('/apply/<int:scholarship_id>', methods=['POST'])
def apply_scholarship(scholarship_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'student':
        return "Access denied"

    user = User.query.get(session['user_id'])
    student = Student.query.filter_by(user_id=session['user_id']).first_or_404()
    scholarship = Scholarship.query.get_or_404(scholarship_id)

    if scholarship.status != 'Open':
        return redirect(url_for(
            'student_scholarships',
            message='This scholarship is closed.'
        ))

    existing_application = Application.query.filter_by(
        student_id=student.id,
        scholarship_id=scholarship.id
    ).first()

    if existing_application:
        return redirect(url_for(
            'student_scholarships',
            message='You have already applied for this scholarship.'
        ))

    new_application = Application(
        student_id=student.id,
        scholarship_id=scholarship.id,
        status='Submitted'
    )
    db.session.add(new_application)
    db.session.commit()

    uploaded_docs = ProfileDocument.query.filter_by(student_id=student.id).all()
    attachments_summary = ", ".join(
        [f"{doc.doc_type}: {doc.filename}" for doc in uploaded_docs]
    ) if uploaded_docs else "No profile documents uploaded"

    form_record = ApplicationForm(
        application_id=new_application.id,

        # Part 1
        full_name=request.form.get('full_name', user.full_name),
        date_of_birth=request.form.get('date_of_birth'),
        nationality=request.form.get('nationality'),
        country_of_residence=request.form.get('country_of_residence'),
        email=request.form.get('email', user.email),
        phone_number=request.form.get('phone_number', user.phone_number),
        mailing_address=request.form.get('mailing_address'),
        linkedin_url=request.form.get('linkedin_url'),
        portfolio_url=request.form.get('portfolio_url'),
        is_phd_student=(request.form.get('is_phd_student') == 'yes'),
        orcid_id=request.form.get('orcid_id'),

        # Part 2
        current_highest_degree=request.form.get('current_highest_degree'),
        current_degree_title=request.form.get('current_degree_title'),
        current_institution_name=request.form.get('current_institution_name'),
        current_location=request.form.get('current_location'),
        current_dates_attended=request.form.get('current_dates_attended'),
        current_gpa_grade=request.form.get('current_gpa_grade'),
        thesis_dissertation_title=request.form.get('thesis_dissertation_title'),
        supervisor_name=request.form.get('supervisor_name'),

        previous_degree=request.form.get('previous_degree'),
        previous_degree_title=request.form.get('previous_degree_title'),
        previous_institution_name=request.form.get('previous_institution_name'),
        previous_location=request.form.get('previous_location'),
        previous_dates_attended=request.form.get('previous_dates_attended'),

        # Part 3
        program_applying_for=request.form.get('program_applying_for'),
        proposed_level_of_study=request.form.get('proposed_level_of_study'),
        proposed_program_title=request.form.get('proposed_program_title'),
        proposed_universities=request.form.get('proposed_universities'),
        proposed_start_date=request.form.get('proposed_start_date'),
        anticipated_completion_date=request.form.get('anticipated_completion_date'),
        proposed_thesis_title=request.form.get('proposed_thesis_title'),
        research_question_aim=request.form.get('research_question_aim'),
        proposed_methodology=request.form.get('proposed_methodology'),
        significance_expected_outcomes=request.form.get('significance_expected_outcomes'),
        potential_supervisors=request.form.get('potential_supervisors'),
        motivation=request.form.get('motivation'),
        career_goals=request.form.get('career_goals'),
        why_this_program_university=request.form.get('why_this_program_university'),
        why_you=request.form.get('why_you'),
        relevant_experiences=request.form.get('relevant_experiences'),

        # Part 4
        work_experience=request.form.get('work_experience'),
        research_experience=request.form.get('research_experience'),
        publications_presentations=request.form.get('publications_presentations'),
        volunteering_extracurricular=request.form.get('volunteering_extracurricular'),
        awards_prizes=request.form.get('awards_prizes'),
        skills_languages=request.form.get('skills_languages'),

        # Part 5
        ref1_name_title=request.form.get('ref1_name_title'),
        ref1_institution=request.form.get('ref1_institution'),
        ref1_department=request.form.get('ref1_department'),
        ref1_email=request.form.get('ref1_email'),
        ref1_phone=request.form.get('ref1_phone'),
        ref1_relationship=request.form.get('ref1_relationship'),
        ref1_known_duration=request.form.get('ref1_known_duration'),

        ref2_name_title=request.form.get('ref2_name_title'),
        ref2_institution=request.form.get('ref2_institution'),
        ref2_department=request.form.get('ref2_department'),
        ref2_email=request.form.get('ref2_email'),
        ref2_phone=request.form.get('ref2_phone'),
        ref2_relationship=request.form.get('ref2_relationship'),
        ref2_known_duration=request.form.get('ref2_known_duration'),

        ref3_name_title=request.form.get('ref3_name_title'),
        ref3_institution=request.form.get('ref3_institution'),
        ref3_department=request.form.get('ref3_department'),
        ref3_email=request.form.get('ref3_email'),
        ref3_phone=request.form.get('ref3_phone'),
        ref3_relationship=request.form.get('ref3_relationship'),
        ref3_known_duration=request.form.get('ref3_known_duration'),

        # Part 6
        attachments_summary=attachments_summary
    )

    db.session.add(form_record)
    db.session.commit()

    # Notify admin of new application submission
    try:
        _notify('admin', f"New application submitted by {student.user.full_name} for '{scholarship.title}'")
    except Exception:
        db.session.rollback()

    return redirect(url_for(
        'track_applications',
        message='Application submitted successfully.'
    ))


# -----------------------------
# STUDENT: TRACK APPLICATIONS
# -----------------------------

@app.route('/student/applications')
def track_applications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'student':
        return "Access denied"

    student = Student.query.filter_by(user_id=session['user_id']).first()
    applications = Application.query.filter_by(student_id=student.id).all()

    return render_template(
        'student_track_applications.html',
        applications=applications,
        message=request.args.get('message')
    )


# -----------------------------
# STUDENT: UPLOAD DOCUMENTS
# -----------------------------

def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {
        'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx'
    }


def _password_issues(password):
    issues = []
    if len(password) < 8:
        issues.append("be at least 8 characters")
    if not any(c.isupper() for c in password):
        issues.append("include at least one uppercase letter")
    if not any(c in "!@#$%^&*()-_=+[{]}\\|;:'\",<.>/?`~" for c in password):
        issues.append("include at least one special character")
    return issues


def _random_filename(original_name):
    ext = ''
    if '.' in original_name:
        ext = '.' + original_name.rsplit('.', 1)[1].lower()
    return f"{uuid.uuid4().hex}{ext}"


@app.route('/upload_documents', methods=['GET', 'POST'])
def upload_documents():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'student':
        return "Access denied"

    student = Student.query.filter_by(user_id=session['user_id']).first()
    message = None

    if request.method == 'POST':
        file = request.files.get('document')

        if not file or file.filename == '':
            message = 'Please choose a file to upload.'
        elif not _allowed_file(file.filename):
            message = 'File type not supported. Use PDF, DOC/DOCX or images.'
        else:
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            safe_name = secure_filename(file.filename)
            random_name = _random_filename(safe_name)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], random_name)
            file.save(save_path)

            new_doc = Document(
                student_id=student.id,
                filename=random_name,
                filepath=save_path
            )
            db.session.add(new_doc)
            db.session.commit()

            # Notify admin a student added a document
            try:
                _notify('admin', f"{student.user.full_name} uploaded a document: {safe_name}")
            except Exception:
                db.session.rollback()

            return redirect(url_for(
                'upload_documents',
                message='Document uploaded successfully.'
            ))

    documents = Document.query.filter_by(student_id=student.id).order_by(Document.uploaded_at.desc()).all()

    return render_template(
        'student_upload_documents.html',
        documents=documents,
        message=message or request.args.get('message')
    )


# -----------------------------
# STUDENT PROFILE
# -----------------------------

REQUIRED_DOC_TYPES = {
    'certified_id': 'Certified ID (under 3 months old)',
    'academic_record': 'Recent academic record / matric results',
    'income_proof': 'Proof of income (parents/guardians) or affidavit',
    'motivational_letter': 'Motivational letter'
}


def save_profile_document(student_id, doc_type, file, is_certified=False, certified_date=None):
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    safe_name = secure_filename(file.filename)
    random_name = _random_filename(safe_name)
    filename = f"{student_id}_{doc_type}_{random_name}"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)

    existing_doc = ProfileDocument.query.filter_by(
        student_id=student_id,
        doc_type=doc_type
    ).first()

    if existing_doc:
        existing_doc.filename = filename
        existing_doc.filepath = save_path
        existing_doc.is_certified = is_certified
        existing_doc.certified_date = certified_date
    else:
        new_doc = ProfileDocument(
            student_id=student_id,
            doc_type=doc_type,
            filename=filename,
            filepath=save_path,
            is_certified=is_certified,
            certified_date=certified_date
        )
        db.session.add(new_doc)

    db.session.commit()
    try:
        student = Student.query.get(student_id)
        label = REQUIRED_PROFILE_DOCS.get(doc_type, doc_type)
        _notify('admin', f"{student.user.full_name} uploaded {label}")
    except Exception:
        db.session.rollback()


def check_document_expiry_notifications(student):
    docs = ProfileDocument.query.filter_by(student_id=student.id).all()
    today = datetime.utcnow().date()

    for doc in docs:
        if doc.is_certified and doc.certified_date:
            age_days = (today - doc.certified_date).days
            days_left = 90 - age_days

            if 0 < days_left <= 7:
                message = f"Your {REQUIRED_PROFILE_DOCS.get(doc.doc_type, doc.doc_type)} will need recertification in {days_left} day(s). Please prepare to recertify it."

                existing_notification = Notification.query.filter_by(
                    recipient_role=f"student:{student.id}",
                    message=message
                ).first()

                if not existing_notification:
                    new_notification = Notification(
                        message=message,
                        recipient_role=f"student:{student.id}"
                    )
                    db.session.add(new_notification)

    db.session.commit()


@app.route('/student/profile', methods=['GET', 'POST'])
def student_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'student':
        return "Access denied"

    user = User.query.get(session['user_id'])
    student = Student.query.filter_by(user_id=session['user_id']).first()

    message = None
    error = None

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'doc_upload':
            doc_type = request.form.get('doc_type')
            is_certified = request.form.get('is_certified') == 'yes'
            certified_date_value = request.form.get('certified_date')
            file = request.files.get('document')

            if doc_type not in REQUIRED_PROFILE_DOCS:
                error = "Invalid document type selected."
            elif not file or file.filename == '':
                error = "Please choose a file to upload."
            elif not _allowed_file(file.filename):
                error = "File type not supported. Use PDF, DOC/DOCX, JPG, JPEG, or PNG."
            else:
                certified_date = None

                if is_certified:
                    if not certified_date_value:
                        error = "Please enter the certification date for the certified document."
                    else:
                        try:
                            certified_date = datetime.strptime(certified_date_value, '%Y-%m-%d').date()
                        except ValueError:
                            error = "Invalid certification date."

                if not error:
                    save_profile_document(
                        student_id=student.id,
                        doc_type=doc_type,
                        file=file,
                        is_certified=is_certified,
                        certified_date=certified_date
                    )
                    message = "Document uploaded successfully."

    check_document_expiry_notifications(student)

    docs = {
        d.doc_type: d
        for d in ProfileDocument.query.filter_by(student_id=student.id).all()
    }

    total_required = len(REQUIRED_PROFILE_DOCS)
    have = sum(1 for key in REQUIRED_PROFILE_DOCS if key in docs)
    completeness_percent = int((have / total_required) * 100) if total_required else 100
    missing_list = _missing_profile_docs(student)

    return render_template(
        'student_profile.html',
        user=user,
        student=student,
        docs=docs,
        message=message,
        error=error,
        required_profile_docs=REQUIRED_PROFILE_DOCS,
        department_labels=DEPARTMENT_LABELS,
        completeness_percent=completeness_percent,
        missing_list=missing_list
    )


# -----------------------------
# STUDENT: NOTIFICATIONS
# -----------------------------

@app.route('/student_notifications')
def student_notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    student = Student.query.filter_by(user_id=session['user_id']).first()
    targeted_role = f"student:{student.id}" if student else None

    # 1. Fetch standard notifications
    notifications = Notification.query.filter(
        or_(
            Notification.recipient_role == 'student',
            Notification.recipient_role == targeted_role
        )
    ).order_by(Notification.id.desc()).all()

    # 2. Calculate dynamic scholarship deadlines
    student_dept = DEPARTMENT_LABELS.get(student.department_name, student.department_name)
    scholarships = Scholarship.query.filter_by(
        status='Open',
        department=student_dept
    ).all()

    today = datetime.utcnow().date()
    scholarship_deadlines = []

    for scholarship in scholarships:
        if scholarship.deadline:
            try:
                # Convert string deadline to date object
                deadline_date = datetime.strptime(scholarship.deadline, '%Y-%m-%d').date()
                days_left = (deadline_date - today).days
                
                # Only show if not expired
                if days_left >= 0:
                    scholarship_deadlines.append({
                        'title': scholarship.title,
                        'deadline': scholarship.deadline,
                        'days_left': days_left,
                        'id': scholarship.id
                    })
            except (ValueError, TypeError):
                continue

    return render_template(
        'student_notifications.html',
        notifications=notifications,
        scholarship_deadlines=scholarship_deadlines
    )

#---------------
# notification
#--------------

@app.route('/mark_student_notification_read/<int:notif_id>', methods=['POST'])
def mark_student_notification_read(notif_id):
    # 1. Locate the notification by its ID
    # Use your actual model name (e.g., Notification or StudentNotification)
    notification = Notification.query.get_or_404(notif_id)
    
    try:
        # 2. Remove the record from the database session
        db.session.delete(notification)
        
        # 3. Commit the change to the database
        db.session.commit()
        
        # Optional: Flash a message (now that 'flash' is imported!)
        flash('Notification dismissed.', 'info')
    except Exception as e:
        # If something goes wrong, undo the pending changes
        db.session.rollback()
        flash('Could not remove notification.', 'danger')
        print(f"Error: {e}") # This helps you see the error in your terminal
        
    # 4. Refresh the page
    return redirect(url_for('student_notifications'))



# -----------------------------
# ADMIN DASHBOARD
# -----------------------------

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        return "Access denied"

    admin = Admin.query.filter_by(user_id=session['user_id']).first()

    return render_template(
        'admin_dashboard.html',
        name=session.get('user_name'),
        admin=admin
    )

    ##
    # New function
    # 

def _notify_department(department, message):
    """Notifies all students in a specific department and sends emails."""
    students = Student.query.filter_by(department_name=department).all()
    recipients = []
    for student in students:
        # 1. Create In-App Notification
        note = Notification(
            message=message, 
            recipient_role=f"student:{student.id}"
        )
        db.session.add(note)
        # 2. Collect emails for batch sending
        if student.user and student.user.email:
            recipients.append(student.user.email)
    
    db.session.commit()
    
    # 3. Send bulk email notification
    if recipients:
        _send_email(recipients, message)




# -----------------------------
# CREATE SCHOLARSHIP (ADMIN)
# -----------------------------

@app.route('/create_scholarship', methods=['GET', 'POST'])
def create_scholarship():
    if session.get('role') != 'admin':
        return "Access denied"

    if request.method == 'POST':
        title = request.form['title']
        dept = request.form['department']  # Ensure your form has a department field
        deadline = request.form['deadline']
        level_of_study = request.form['level_of_study']
        
        new_scholarship = Scholarship(
            title=title,
            description=request.form['description'],
            requirements=request.form['requirements'],
            department=dept,
            deadline=deadline,
            status=request.form['status'],
             level_of_study =  level_of_study
        )
        db.session.add(new_scholarship)
        db.session.commit()

        # FEATURE: Announcement Notification
        msg = f"📢 New Scholarship Opportunity: '{title}' is now open for {dept} students! Check it out before {deadline}."
        _notify_department(dept, msg)

        return redirect(url_for('admin_scholarships'))

    return render_template('create_scholarship.html')


# -----------------------------
# VIEW SCHOLARSHIPS
# -----------------------------
# -----------------------------
# EDIT SCHOLARSHIP (ADMIN)
# -----------------------------

@app.route('/edit_scholarship/<int:id>', methods=['GET', 'POST'])
def edit_scholarship(id):
    if session.get('role') != 'admin':
        return "Access denied"

    scholarship = Scholarship.query.get_or_404(id)
    
    if request.method == 'POST':
        old_deadline = scholarship.deadline
        new_deadline = request.form['deadline']
        
        scholarship.title = request.form['title']
        scholarship.deadline = new_deadline
        # ... update other fields ...
        
        # FEATURE: Deadline Extension Notification
        if old_deadline and new_deadline > old_deadline:
            # Notify only the students who have an application for THIS scholarship
            for app_record in scholarship.applications:
                msg = f"⏳ Good news! The deadline for '{scholarship.title}' has been extended to {new_deadline}. You now have more time to update your documents."
                _notify(f"student:{app_record.student_id}", msg)

        db.session.commit()
        return redirect(url_for('admin_scholarships'))

    return render_template('edit_scholarship.html', scholarship=scholarship)


@app.route('/delete_scholarship/<int:id>', methods=['POST'])
def delete_scholarship(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        return "Access denied"

    scholarship = Scholarship.query.get_or_404(id)

    linked_application = Application.query.filter_by(scholarship_id=scholarship.id).first()
    if linked_application:
        return "This scholarship cannot be deleted because students have already applied for it."

    db.session.delete(scholarship)
    db.session.commit()

    return redirect(url_for('admin_scholarships'))


@app.route('/view_scholarships')
def view_scholarships():
    return redirect(url_for('admin_scholarships'))


# -----------------------------
# ADMIN: COMBINED SCHOLARSHIPS PAGE
# -----------------------------

"""
Auto-close deadlines and manage/create scholarships in one page.
"""


def _refresh_scholarship_statuses():
    today = datetime.utcnow().date()
    changed = False
    for s in Scholarship.query.all():
        try:
            deadline_date = datetime.strptime(s.deadline, '%Y-%m-%d').date()
            if deadline_date < today and s.status != 'Closed':
                s.status = 'Closed'
                changed = True
        except ValueError:
            continue
    if changed:
        db.session.commit()


@app.route('/admin/scholarships', methods=['GET', 'POST'])
def admin_scholarships():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return "Access denied"

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        requirements = request.form['requirements']
        deadline = request.form['deadline']
        status = request.form['status']
        dept_code = request.form.get('department')
        level_of_study = request.form.get('level_of_study')

        new_scholarship = Scholarship(
            title=title,
            description=description,
            requirements=requirements,
            deadline=deadline,
            status=status,
            department=dept_code,
            level_of_study = request.form.get('level_of_study')

        )
        db.session.add(new_scholarship)
        db.session.commit()
        return redirect(url_for('admin_scholarships'))

    _refresh_scholarship_statuses()
    scholarships = Scholarship.query.all()
    return render_template('admin_manage_scholarships.html', scholarships=scholarships)


# -----------------------------
# VIEW APPLICATIONS (ADMIN)
# -----------------------------

@app.route('/view_applications')
def view_applications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        return "Access denied"

    applications = Application.query.filter_by(status='Submitted').all()
    return render_template('admin_view_applications.html', applications=applications)


@app.route('/applications/<int:app_id>/under_review', methods=['POST'])
def mark_under_review(app_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        return "Access denied"

    application = Application.query.get_or_404(app_id)
    application.status = 'Under Review'
    db.session.commit()
    return redirect(url_for('view_applications'))


@app.route('/manage_applications')
def manage_applications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        return "Access denied"

    under_review_apps = Application.query.filter_by(status='Under Review').order_by(
        Application.submitted_at.desc()).all()
    shortlisted_apps = Application.query.filter_by(status='Shortlisted').order_by(Application.submitted_at.desc()).all()
    approved_apps = Application.query.filter_by(status='Approved').order_by(Application.submitted_at.desc()).all()
    rejected_apps = Application.query.filter_by(status='Rejected').order_by(Application.submitted_at.desc()).all()
    incomplete_apps = Application.query.filter_by(status='Incomplete').order_by(Application.submitted_at.desc()).all()

    return render_template(
        'admin_manage_applications.html',
        under_review_apps=under_review_apps,
        shortlisted_apps=shortlisted_apps,
        approved_apps=approved_apps,
        rejected_apps=rejected_apps,
        incomplete_apps=incomplete_apps
    )


@app.route('/applications/<int:app_id>/review')
def review_application(app_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        return "Access denied"

    application = Application.query.get_or_404(app_id)
    form = application.form
    scholarship = application.scholarship
    student = application.student
    user = student.user
    documents = Document.query.filter_by(student_id=student.id).order_by(Document.uploaded_at.desc()).all()
    profile_docs = ProfileDocument.query.filter_by(student_id=student.id).order_by(
        ProfileDocument.uploaded_at.desc()).all()

    return render_template(
        'admin_review_application.html',
        application=application,
        form=form,
        scholarship=scholarship,
        student=student,
        user=user,
        documents=documents,
        profile_docs=profile_docs,
        required_profile_docs=REQUIRED_PROFILE_DOCS
    )


@app.route('/applications/<int:app_id>/update_status', methods=['POST'])
def update_application_status(app_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        return "Access denied"

    application = Application.query.get_or_404(app_id)
    new_status = request.form.get('status')
    reason = request.form.get('reason')

    allowed_statuses = ['Under Review', 'Shortlisted', 'Approved', 'Rejected', 'Incomplete']

    if new_status in allowed_statuses:
        application.status = new_status

        # Save reason only if needed
        if new_status in ['Rejected', 'Incomplete']:
            application.reason = reason
        else:
            application.reason = None

        student = application.student
        scholarship = application.scholarship

        # Build notification message
        if reason and new_status in ['Rejected', 'Incomplete']:
            notification_message = (
                f"Your application for '{scholarship.title}' is '{new_status}'. "
                f"Reason: {reason}"
            )
        else:
            notification_message = (
                f"Your application for '{scholarship.title}' has been updated to '{new_status}'."
            )

        targeted_role = f"student:{student.id}"

        new_notification = Notification(
            message=notification_message,
            recipient_role=targeted_role
        )

        db.session.add(new_notification)
        db.session.commit()

    return redirect(url_for('manage_applications'))


# -----------------------------
# ADMIN: REQUEST MISSING DOCUMENTS
# -----------------------------

def _missing_profile_docs(student):
    docs = {d.doc_type: d for d in ProfileDocument.query.filter_by(student_id=student.id).all()}
    missing = []
    for key, label in REQUIRED_DOC_TYPES.items():
        doc = docs.get(key)
        if not doc:
            missing.append(f"Missing: {label}")
        elif key == 'certified_id':
            if doc.certified_date:
                age_days = (datetime.utcnow().date() - doc.certified_date).days
                if age_days > 90:
                    missing.append("Certified ID expired (older than 3 months)")
            else:
                missing.append("Certified ID certification date not provided")
    return missing


@app.route('/admin/missing_documents', methods=['GET', 'POST'])
def admin_missing_documents():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        return "Access denied"

    message = None
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        note = (request.form.get('note') or "").strip()
        student = Student.query.get(student_id)
        if student:
            text = note or "Please upload or update your required documents."
            text = f"{student.user.full_name}: {text}"
            targeted_role = f"student:{student.id}"
            notif = Notification(message=text, recipient_role=targeted_role)
            db.session.add(notif)
            db.session.commit()
            try:
                _notify('admin', f"Requested missing docs from {student.user.full_name}")
            except Exception:
                db.session.rollback()
            message = "Student notified."

    students = Student.query.all()
    flagged = []
    for s in students:
        missing = _missing_profile_docs(s)
        if missing:
            flagged.append({'student': s, 'user': s.user, 'missing': missing})

    return render_template('admin_missing_documents.html', flagged=flagged, message=message)


# -----------------------------
# ADMIN: MANAGE STUDENTS
# -----------------------------

@app.route('/admin/students')
def manage_students():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return "Access denied"

    students = Student.query.all()
    profile_docs = {d.student_id: d for d in ProfileDocument.query.all()}
    return render_template('admin_manage_students.html', students=students, profile_docs=profile_docs)


@app.route('/admin/students/<int:user_id>/unlock', methods=['POST'])
def unlock_student(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return "Access denied"

    user = User.query.get_or_404(user_id)
    if user.role != 'student':
        return "Only student accounts can be unlocked here."

    user.is_locked = False
    user.failed_attempts = 0
    db.session.commit()
    return redirect(url_for('manage_students'))


# -----------------------------
# ADMIN NOTIFICATIONS
# -----------------------------

@app.route('/admin_notifications')
def admin_notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        return "Access denied"

    notifications = Notification.query.filter_by(recipient_role='admin').all()
    return render_template('admin_notifications.html', notifications=notifications)


@app.route('/admin_notifications/<int:notif_id>/read', methods=['POST'])
def mark_admin_notification_read(notif_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return "Access denied"

    notification = Notification.query.get_or_404(notif_id)
    if notification.recipient_role != 'admin':
        return "Access denied"

    db.session.delete(notification)
    db.session.commit()
    return redirect(url_for('admin_notifications'))


# -----------------------------
# LOGOUT
# -----------------------------

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# -----------------------------
# PASSWORD RESET
# -----------------------------

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    _ensure_user_security_columns()
    error = None
    message = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user:
            token = uuid.uuid4().hex
            user.reset_token = token
            user.reset_expires = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            reset_link = url_for('reset_password', token=token, _external=True)
            _send_email(
                [user.email],
                f"Hi {user.full_name},\n\nUse this link to reset your password (valid for 1 hour): {reset_link}\n\nIf you didn't request this, you can ignore it.",
                subject="Reset your password"
            )
        message = "If that email exists, we sent a reset link."
    return render_template('forgot_password.html', error=error, message=message)


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    _ensure_user_security_columns()
    error = None
    message = None
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_expires or user.reset_expires < datetime.utcnow():
        return "Reset link is invalid or expired."

    if request.method == 'POST':
        new_password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        if new_password != confirm:
            error = "Passwords do not match."
        else:
            issues = _password_issues(new_password)
            if issues:
                error = "Password must " + ", ".join(issues[:-1]) + (" and " if len(issues) > 1 else "") + issues[
                    -1] + "."
            else:
                user.password_hash = new_password
                user.reset_token = None
                user.reset_expires = None
                user.failed_attempts = 0
                user.is_locked = False
                db.session.commit()
                message = "Password reset successful. You can now log in."
                return redirect(url_for('login'))

    return render_template('reset_password.html', error=error, message=message, token=token)


# -----------------------------
# RUN APPLICATION
# -----------------------------

if __name__ == '__main__':
    with app.app_context():
        _ensure_user_security_columns()
        db.create_all()

        # Create default admin if not existing
        admin_user = User.query.filter_by(email='admin@example.com').first()
        if not admin_user:
            admin_user = User(
                full_name='Admin User',
                email='admin@example.com',
                phone_number='0000000000',
                password_hash='admin123',
                role='admin'
            )
            db.session.add(admin_user)
            db.session.commit()

            admin_profile = Admin(
                user_id=admin_user.id,
                staff_number='ADM001',
                department='Financial Aid'
            )
            db.session.add(admin_profile)
            db.session.commit()

    app.run(debug=True)