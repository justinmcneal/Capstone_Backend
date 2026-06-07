import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounts.models import LoanOfficer
from loans.models import LoanApplication
from bson import ObjectId

officer = LoanOfficer.find_one({"email": "sorianoeligabriel16@gmail.com"})
if officer:
    print(f"Officer found: ID={officer.id}, Role={officer.role}")
    apps = list(LoanApplication.find({"assigned_officer": str(officer.id)}))
    print(f"Assigned applications: {len(apps)}")
    for a in apps:
        print(f" - {a.id}: status={a.status}")
    
    all_apps = list(LoanApplication.find({}))
    print(f"Total applications in DB: {len(all_apps)}")
else:
    print("Officer not found")
