#!/usr/bin/env python3
"""
Create an encrypted MongoDB backup archive and optionally copy it offsite.

Required env vars:
  - MONGODB_URI
  - BACKUP_ENCRYPTION_PASSPHRASE

Optional env vars:
  - MONGODB_NAME (default: capstone_db)
  - BACKUP_OUTPUT_DIR (default: ./backups)
  - BACKUP_RETENTION_DAYS (default: 14)
  - BACKUP_OFFSITE_RCLONE_REMOTE (example: gdrive:msme-pathways-backups)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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


def _cleanup_old_backups(directory: Path, retention_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for item in directory.glob("*.archive.gz.enc"):
        modified = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
        if modified < cutoff:
            item.unlink(missing_ok=True)
            removed += 1
    return removed


def main() -> int:
    try:
        _require_binary("mongodump")
        _require_binary("openssl")

        mongo_uri = _require_env("MONGODB_URI")
        _require_env("BACKUP_ENCRYPTION_PASSPHRASE")
        mongo_db = (os.getenv("MONGODB_NAME", "capstone_db") or "capstone_db").strip()
        output_dir = Path(os.getenv("BACKUP_OUTPUT_DIR", "backups")).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "14"))
        offsite_remote = (os.getenv("BACKUP_OFFSITE_RCLONE_REMOTE", "") or "").strip()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_name = f"{mongo_db}_{timestamp}.archive.gz.enc"
        backup_path = output_dir / backup_name

        env = dict(os.environ)
        dump_cmd = [
            "mongodump",
            "--uri",
            mongo_uri,
            "--db",
            mongo_db,
            "--archive",
            "--gzip",
            "--readPreference",
            "secondaryPreferred",
        ]
        encrypt_cmd = [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-pass",
            "env:BACKUP_ENCRYPTION_PASSPHRASE",
            "-out",
            str(backup_path),
        ]

        print(f"[backup] creating encrypted archive: {backup_path}")
        p1 = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, env=env)
        p2 = subprocess.Popen(encrypt_cmd, stdin=p1.stdout, env=env)
        if p1.stdout:
            p1.stdout.close()

        p2_rc = p2.wait()
        p1_rc = p1.wait()
        if p1_rc != 0:
            raise RuntimeError(f"mongodump failed with exit code {p1_rc}")
        if p2_rc != 0:
            raise RuntimeError(f"openssl encryption failed with exit code {p2_rc}")

        size_mb = backup_path.stat().st_size / (1024 * 1024)
        print(f"[backup] done: {backup_path.name} ({size_mb:.2f} MB)")

        if offsite_remote:
            _require_binary("rclone")
            remote_target = f"{offsite_remote.rstrip('/')}/{backup_name}"
            print(f"[backup] copying offsite via rclone -> {remote_target}")
            subprocess.run(["rclone", "copyto", str(backup_path), remote_target], check=True, env=env)
            print("[backup] offsite copy complete")
        else:
            print("[backup] offsite copy skipped (BACKUP_OFFSITE_RCLONE_REMOTE not set)")

        removed = _cleanup_old_backups(output_dir, retention_days)
        print(f"[backup] retention cleanup removed {removed} old backup(s)")
        return 0
    except Exception as exc:
        print(f"[backup] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
