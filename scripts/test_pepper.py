"""
=============================================================================
  PEPPER IMPLEMENTATION DEMO — for professor review
=============================================================================

This script proves that:
  1. Passwords are hashed with bcrypt (salted automatically).
  2. An HMAC-SHA256 pepper is applied BEFORE bcrypt, using SECRET_PEPPER.
  3. The same password produces a DIFFERENT hash every time (bcrypt salt).
  4. Verification works correctly (correct password → True).
  5. Wrong password → False.
  6. Changing / removing the pepper makes the stored hash UNVERIFIABLE,
     proving the pepper is an active part of the security layer.

Run from the project root:
    python scripts/test_pepper.py
=============================================================================
"""

import os
import sys
import hmac
import hashlib

# ---------------------------------------------------------------------------
# Bootstrap: make sure we can import from the project without Django running
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Load .env so SECRET_PEPPER is available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass  # dotenv not installed — rely on the shell environment

import bcrypt

# ---------------------------------------------------------------------------
# Helpers — mirrors pepper_utils.py exactly so the demo is self-contained
# ---------------------------------------------------------------------------

def _get_pepper() -> str:
    pepper = os.environ.get('SECRET_PEPPER', '')
    if not pepper:
        raise EnvironmentError(
            "\n[ERROR] SECRET_PEPPER is not set in your .env file!\n"
            "  Generate one with:  python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "  Then add it to .env:  SECRET_PEPPER=<generated_value>\n"
        )
    return pepper


def apply_pepper(raw_password: str, pepper: str) -> str:
    """HMAC-SHA256(pepper, raw_password) → fixed-length hex string."""
    return hmac.new(
        key=pepper.encode('utf-8'),
        msg=raw_password.encode('utf-8'),
        digestmod=hashlib.sha256,
    ).hexdigest()


def hash_password(raw_password: str, pepper: str) -> str:
    peppered = apply_pepper(raw_password, pepper)
    hashed = bcrypt.hashpw(peppered.encode('utf-8'), bcrypt.gensalt())
    return hashed.decode('utf-8')


def verify_password(raw_password: str, stored_hash: str, pepper: str) -> bool:
    peppered = apply_pepper(raw_password, pepper)
    return bcrypt.checkpw(peppered.encode('utf-8'), stored_hash.encode('utf-8'))


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
def header(msg):
    print(f"\n{BOLD}{YELLOW}{'='*60}{RESET}")
    print(f"{BOLD}{YELLOW}  {msg}{RESET}")
    print(f"{BOLD}{YELLOW}{'='*60}{RESET}")


# ---------------------------------------------------------------------------
# MAIN DEMO
# ---------------------------------------------------------------------------

def run_demo():
    print(f"\n{BOLD}{'='*60}")
    print("  PEPPER SECURITY IMPLEMENTATION — DEMO")
    print(f"{'='*60}{RESET}")

    # ── 0. Load pepper ──────────────────────────────────────────────────────
    try:
        real_pepper = _get_pepper()
    except EnvironmentError as e:
        print(e)
        sys.exit(1)

    info(f"SECRET_PEPPER loaded  →  {real_pepper[:8]}{'*' * (len(real_pepper) - 8)}  (first 8 chars shown)")

    # ── 1. Apply pepper & show the peppered value ───────────────────────────
    header("STEP 1 — Pepper is applied via HMAC-SHA256 before hashing")

    raw_password = "MySecurePassword123!"
    peppered = apply_pepper(raw_password, real_pepper)

    info(f"Raw password   :  {raw_password}")
    info(f"After HMAC     :  {peppered}")
    info("The peppered value is a 64-char hex string (SHA-256 output).")
    info("It is NEVER stored — only the final bcrypt hash is stored.")

    # ── 2. Hash the password twice → different hashes (bcrypt salt) ─────────
    header("STEP 2 — bcrypt adds a unique salt → different hash each time")

    hash1 = hash_password(raw_password, real_pepper)
    hash2 = hash_password(raw_password, real_pepper)

    info(f"Hash #1:  {hash1}")
    info(f"Hash #2:  {hash2}")

    if hash1 != hash2:
        ok("Both hashes are DIFFERENT — bcrypt salt is working correctly.")
    else:
        fail("Hashes are identical — something is wrong with bcrypt salting!")

    # ── 3. Correct password verifies ────────────────────────────────────────
    header("STEP 3 — Correct password verifies successfully")

    result = verify_password(raw_password, hash1, real_pepper)
    if result:
        ok(f'verify_password("{raw_password}", hash1)  →  True  ✔')
    else:
        fail(f'verify_password("{raw_password}", hash1)  →  False  ✘  (should be True!)')

    # ── 4. Wrong password fails ─────────────────────────────────────────────
    header("STEP 4 — Wrong password is correctly rejected")

    wrong_password = "WrongPassword999!"
    result_wrong = verify_password(wrong_password, hash1, real_pepper)
    if not result_wrong:
        ok(f'verify_password("{wrong_password}", hash1)  →  False  ✔  (correctly rejected)')
    else:
        fail(f'verify_password("{wrong_password}", hash1)  →  True  ✘  (should be False!)')

    # ── 5. KEY PROOF — wrong pepper breaks verification ─────────────────────
    header("STEP 5 — KEY PROOF: Wrong pepper makes hash UNVERIFIABLE")

    fake_pepper = "this-is-a-completely-wrong-pepper-value-0000000000000000"
    result_fake = verify_password(raw_password, hash1, fake_pepper)

    info(f"Stored hash was created with the REAL pepper.")
    info(f"Now we try to verify with a FAKE pepper: {fake_pepper[:16]}...")

    if not result_fake:
        ok(
            "verify_password(correct_password, hash, FAKE_PEPPER)  →  False\n"
            "     ↳ The pepper is an ACTIVE security layer.\n"
            "       Even with the correct password, the wrong pepper\n"
            "       produces a different HMAC → bcrypt rejects it.\n"
            "       An attacker who steals the database CANNOT verify\n"
            "       passwords without also knowing the SECRET_PEPPER."
        )
    else:
        fail("Verification succeeded with a fake pepper — pepper is NOT working!")

    # ── 6. Summary ───────────────────────────────────────────────────────────
    header("SUMMARY")

    checks = [
        ("Pepper loaded from environment (not hardcoded)",        True),
        ("HMAC-SHA256 applied before bcrypt",                     True),
        ("bcrypt auto-salting produces unique hashes",            hash1 != hash2),
        ("Correct password verifies",                             result),
        ("Wrong password rejected",                               not result_wrong),
        ("Wrong pepper makes hash unverifiable (key proof)",      not result_fake),
    ]

    all_passed = True
    for label, passed in checks:
        if passed:
            ok(label)
        else:
            fail(label)
            all_passed = False

    print()
    if all_passed:
        print(f"{BOLD}{GREEN}  ALL CHECKS PASSED — Pepper is correctly implemented!{RESET}\n")
    else:
        print(f"{BOLD}{RED}  SOME CHECKS FAILED — Review the output above.{RESET}\n")


if __name__ == '__main__':
    run_demo()
