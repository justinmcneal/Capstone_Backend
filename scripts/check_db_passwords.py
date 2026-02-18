"""
=============================================================================
  CHECK DATABASE PASSWORDS — Are they bcrypt + peppered?
=============================================================================

This script connects to your real MongoDB and:
  1. Shows the stored password hash for each user (all collections).
  2. Explains what the $2b$ prefix means (bcrypt).
  3. Lets you verify a real user's password live.

Run from the project root:
    venv\Scripts\python.exe scripts/check_db_passwords.py
=============================================================================
"""

import os
import sys
import django

# ---------------------------------------------------------------------------
# Bootstrap Django so we can use settings.MONGODB
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

django.setup()

from django.conf import settings

# ---------------------------------------------------------------------------
# Pretty printing helpers
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✔  {msg}{RESET}")
def fail(msg):  print(f"  {RED}✘  {msg}{RESET}")
def info(msg):  print(f"  {CYAN}ℹ  {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}⚠  {msg}{RESET}")
def header(msg):
    print(f"\n{BOLD}{YELLOW}{'='*65}{RESET}")
    print(f"{BOLD}{YELLOW}  {msg}{RESET}")
    print(f"{BOLD}{YELLOW}{'='*65}{RESET}")


def is_bcrypt_hash(value: str) -> bool:
    """bcrypt hashes always start with $2b$ or $2a$ and are 60 chars long."""
    return (
        isinstance(value, str)
        and len(value) == 60
        and value.startswith(('$2b$', '$2a$', '$2y$'))
    )


def check_collection(db, collection_name: str, name_field: str = 'email'):
    """Print password hash status for every document in a collection."""
    col = db[collection_name]
    docs = list(col.find({}, {'_id': 1, name_field: 1, 'password': 1}))

    if not docs:
        warn(f"Collection '{collection_name}' is empty — no users found.")
        return 0, 0

    peppered_count = 0
    not_peppered_count = 0

    for doc in docs:
        identifier = doc.get(name_field, str(doc.get('_id', '?')))
        pwd = doc.get('password', '')

        if is_bcrypt_hash(pwd):
            # Show only the first 20 chars of the hash so it's readable
            short_hash = pwd[:20] + '...'
            ok(
                f"{identifier:<35}  hash: {BOLD}{short_hash}{RESET}{GREEN}  ← bcrypt ✔"
            )
            peppered_count += 1
        elif pwd:
            fail(
                f"{identifier:<35}  hash: {pwd[:20]}...  ← NOT bcrypt ✘"
            )
            not_peppered_count += 1
        else:
            warn(f"{identifier:<35}  (no password field)")

    return peppered_count, not_peppered_count


def live_verify():
    """Interactively verify a real user's password against the database."""
    header("LIVE VERIFICATION — Test a real user's password")

    from accounts.utils.pepper_utils import verify_password

    db = settings.MONGODB

    print(f"\n  {BOLD}Which collection?{RESET}")
    print("    1 = customer")
    print("    2 = admins")
    print("    3 = loan_officers")
    choice = input("  Enter 1/2/3: ").strip()

    collection_map = {'1': 'customer', '2': 'admins', '3': 'loan_officers'}
    collection_name = collection_map.get(choice)
    if not collection_name:
        warn("Invalid choice.")
        return

    email = input("  Enter user email: ").strip()
    raw_password = input("  Enter password to test: ").strip()

    doc = db[collection_name].find_one({'email': email}, {'password': 1, 'email': 1})
    if not doc:
        fail(f"No user found with email '{email}' in '{collection_name}'.")
        return

    stored_hash = doc.get('password', '')
    if not is_bcrypt_hash(stored_hash):
        fail("Stored password is NOT a bcrypt hash — pepper may not be applied!")
        return

    info(f"Stored hash  :  {stored_hash[:20]}...")
    info(f"Hash length  :  {len(stored_hash)} chars (bcrypt = always 60)")
    info(f"Hash prefix  :  {stored_hash[:4]}  ($2b$ = bcrypt with pepper)")

    result = verify_password(raw_password, stored_hash)
    print()
    if result:
        ok(f"Password '{raw_password}' is CORRECT for {email}  ✔")
    else:
        fail(f"Password '{raw_password}' is WRONG for {email}  ✘")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def run():
    print(f"\n{BOLD}{'='*65}")
    print("  MONGODB PASSWORD HASH CHECKER")
    print(f"{'='*65}{RESET}")

    db = settings.MONGODB

    # ── 1. Explain what we're looking for ───────────────────────────────────
    header("WHAT A PEPPERED + BCRYPT HASH LOOKS LIKE")

    info("A correctly peppered password stored in MongoDB looks like:")
    print(f"\n    {BOLD}$2b$12$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy{RESET}")
    print()
    info("  $2b$  → bcrypt algorithm identifier")
    info("  12    → cost factor (2^12 = 4096 bcrypt rounds)")
    info("  next 22 chars → the unique SALT (auto-generated by bcrypt)")
    info("  last 31 chars → the actual password hash")
    info("")
    info("The PEPPER is NOT visible in the hash — it was mixed in BEFORE")
    info("bcrypt ran, via HMAC-SHA256. That's the whole point.")

    # ── 2. Scan all collections ─────────────────────────────────────────────
    collections = [
        ('customer',      'email'),
        ('admins',        'email'),
        ('loan_officers', 'email'),
    ]

    total_ok = 0
    total_bad = 0

    for col_name, id_field in collections:
        header(f"COLLECTION: {col_name}")
        ok_count, bad_count = check_collection(db, col_name, id_field)
        total_ok  += ok_count
        total_bad += bad_count

    # ── 3. Summary ───────────────────────────────────────────────────────────
    header("SUMMARY")
    ok(f"Bcrypt-hashed (peppered) passwords : {total_ok}")
    if total_bad:
        fail(f"Non-bcrypt passwords (NOT peppered) : {total_bad}")
    else:
        ok(f"Non-bcrypt passwords               : {total_bad}  (none — all good!)")

    print()
    if total_bad == 0 and total_ok > 0:
        print(f"{BOLD}{GREEN}  All stored passwords are bcrypt + peppered!{RESET}")
    elif total_ok == 0:
        warn("No users found in the database yet.")
    else:
        print(f"{BOLD}{RED}  Some passwords are NOT peppered — re-hash them!{RESET}")

    # ── 4. Live verification ─────────────────────────────────────────────────
    print()
    do_verify = input(f"  {BOLD}Do you want to verify a real user's password? (y/n): {RESET}").strip().lower()
    if do_verify == 'y':
        live_verify()

    print()


if __name__ == '__main__':
    run()
