import sqlite3, pprint
con=sqlite3.connect('scholarship_tracker.db')
cur=con.cursor()
pprint.pp(cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
pprint.pp(cur.execute("SELECT id, full_name, email, phone_number, password_hash, role FROM Users").fetchall())
pprint.pp(cur.execute("SELECT id, student_number, user_id, faculty_name, department_name, level_of_study FROM Students").fetchall())
con.close()
