#!/usr/bin/env python3
"""
Restore an encrypted MongoDB backup archive into a target database.

Usage:
  python scripts/restore_encrypted_backup.py /path/to/capstone_db_20260220T010203Z.archive.gz.enc

Required env vars:
  - MONGODB_URI
  - BACKUP_ENCRYPTION_PASSPHRASE

Optional env vars:
  - MONGODB_NAME (source DB name inside archive, default: capstone_db)
  - BACKUP_RESTORE_DB_NAME (target DB, default: capstone_db_restore_test)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parents[1]
if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


def _require_env(name: str) -> str:
    value = (os.getenv(name, "") or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required binary not found in PATH: {name}")


def main(argv: list[str]) -> int:
    try:
        if len(argv) < 2:
            raise RuntimeError(
                "Missing backup file path.\n"
                "Usage: python scripts/restore_encrypted_backup.py /path/to/backup.archive.gz.enc"
            )

        backup_path = Path(argv[1]).expanduser().resolve()
        if not backup_path.exists():
            raise RuntimeError(f"Backup file not found: {backup_path}")

        _require_binary("mongorestore")
        _require_binary("openssl")

        mongo_uri = _require_env("MONGODB_URI")
        _require_env("BACKUP_ENCRYPTION_PASSPHRASE")
        source_db = (os.getenv("MONGODB_NAME", "capstone_db") or "capstone_db").strip()
        target_db = (
            os.getenv("BACKUP_RESTORE_DB_NAME", "capstone_db_restore_test")
            or "capstone_db_restore_test"
        ).strip()

        env = dict(os.environ)
        decrypt_cmd = [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-pass",
            "env:BACKUP_ENCRYPTION_PASSPHRASE",
            "-in",
            str(backup_path),
        ]
        restore_cmd = [
            "mongorestore",
            "--uri",
            mongo_uri,
            "--archive",
            "--gzip",
            "--drop",
            "--nsFrom",
            f"{source_db}.*",
            "--nsTo",
            f"{target_db}.*",
        ]

        print(f"[restore] source backup: {backup_path}")
        print(f"[restore] target DB: {target_db}")
        p1 = subprocess.Popen(decrypt_cmd, stdout=subprocess.PIPE, env=env)
        p2 = subprocess.Popen(restore_cmd, stdin=p1.stdout, env=env)
        if p1.stdout:
            p1.stdout.close()

        p2_rc = p2.wait()
        p1_rc = p1.wait()
        if p1_rc != 0:
            raise RuntimeError(f"openssl decryption failed with exit code {p1_rc}")
        if p2_rc != 0:
            raise RuntimeError(f"mongorestore failed with exit code {p2_rc}")

        print("[restore] restore completed successfully")
        return 0
    except Exception as exc:
        print(f"[restore] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
