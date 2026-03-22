from app import app, db
from models import Scholarship

with app.app_context():
    # This creates the .db file again with the NEW department column
    db.create_all() 

    s1 = Scholarship(
        title = "Woman in STEM Excellence Award",
        description = "Supporting women in tech fields.",
        requirements = "Must be a 2nd year ICT student.",
        deadline = "2026-04-08",
        status = "Open",
        department = "Information Technology" 
    )

    s2 = Scholarship(
        title = "Ubuntu Scholarship",
        description = "Community-focused funding.",
        requirements = "Proof of community service.",
        deadline = "2026-08-16",
        status = "Open",
        department = "Humanities"
    )

    db.session.add(s1)
    db.session.add(s2)
    db.session.commit()
    print("Database recreated and seeded successfully!")















