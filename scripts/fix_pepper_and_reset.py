r"""
=============================================================================
  FIX PEPPER & RESET ADMIN PASSWORD
=============================================================================
This script will:
1. Generate a proper 64-character SECRET_PEPPER.
2. Update your .env file with the new pepper.
3. Re-hash the password for testadmin@gmail.com so it works perfectly.
=============================================================================
"""
import os
import secrets
import sys
import django

# Bootstrap
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from dotenv import load_dotenv, set_key
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(env_path)

def run():
    print("--- PEPPER FIX & PASSWORD RESET ---")
    
    # 1. Generate new 64-char pepper
    new_pepper = secrets.token_hex(32)
    print(f"Generated new 64-char pepper: {new_pepper[:10]}...")
    
    # 2. Update .env
    set_key(env_path, "SECRET_PEPPER", new_pepper)
    print("Updated .env with the new SECRET_PEPPER.")
    
    # Refresh environment
    os.environ["SECRET_PEPPER"] = new_pepper
    django.setup()
    
    from accounts.models.admin import Admin
    
    # 3. Reset the admin password
    admin_email = "testadmin@gmail.com"
    admin = Admin.find_one({"email": admin_email})
    
    if admin:
        # Use the password from your notes
        new_password = "AdminPass123!"
        admin.set_password(new_password)
        admin.save()
        print(f"Successfully reset password for {admin_email} using the NEW pepper.")
        print(f"You can now login with: {new_password}")
    else:
        print(f"Admin {admin_email} not found. Please check the email address.")

if __name__ == "__main__":
    run()
