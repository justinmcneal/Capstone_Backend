#!/usr/bin/env python3
"""
Interactive security demo harness for Capstone backend.

This script uses real backend endpoints and real user inputs to exercise:
- Customer signup
- Customer login
- PII document upload (encrypted at rest in backend)
- Authorized/unauthorized document access
- Input sanitization defenses (XSS + NoSQL payload tests)
- JSON evidence export from backend security logs
"""
from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_BASE_URL = os.getenv("CAPSTONE_API_BASE_URL", "http://localhost:8000")
DEFAULT_SECURITY_LOG = os.getenv("CAPSTONE_SECURITY_LOG_PATH", "logs/security_events.jsonl")
DEFAULT_DOC_TYPE = "valid_id"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    cleaned = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


@dataclass
class SessionState:
    started_at: datetime = field(default_factory=utc_now)
    auth_tokens: dict[str, dict[str, str]] = field(default_factory=dict)
    uploaded_docs: list[dict[str, str]] = field(default_factory=list)


class SecurityDemoCLI:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.state = SessionState()
        self.http = requests.Session()
        self.http.headers.update({"Accept": "application/json"})

    def run(self) -> None:
        while True:
            print("\n" + "=" * 68)
            print("CAPSTONE SECURITY DEMO HARNESS")
            print("=" * 68)
            print("[1] Customer Signup")
            print("[2] Verify Signup OTP (optional)")
            print("[3] Customer Login")
            print("[4] Upload Document (valid_id)")
            print("[5] View/Preview Document")
            print("[6] Run Input Sanitization Test (XSS + NoSQL)")
            print("[7] Run Unauthorized Access Test")
            print("[8] Export Security Logs to JSON")
            print("[9] Show Session State")
            print("[0] Exit")
            print("=" * 68)

            choice = input("Choice: ").strip()

            if choice == "1":
                self.customer_signup()
            elif choice == "2":
                self.verify_signup_otp()
            elif choice == "3":
                self.customer_login()
            elif choice == "4":
                self.upload_document()
            elif choice == "5":
                self.preview_document()
            elif choice == "6":
                self.run_sanitization_test()
            elif choice == "7":
                self.run_unauthorized_access_test()
            elif choice == "8":
                self.export_security_logs()
            elif choice == "9":
                self.show_state()
            elif choice == "0":
                print("Exiting.")
                return
            else:
                print("Invalid choice.")

    def api_call(
        self,
        method: str,
        path: str,
        token: str | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.http.request(method=method, url=url, headers=headers, timeout=30, **kwargs)

    @staticmethod
    def print_response(resp: requests.Response) -> None:
        print(f"HTTP {resp.status_code}")
        try:
            payload = resp.json()
            print(json.dumps(payload, indent=2))
        except ValueError:
            print(resp.text[:1000])

    def customer_signup(self) -> None:
        print("\nCustomer Signup")
        first_name = input("First name: ").strip()
        last_name = input("Last name: ").strip()
        email = input("Email: ").strip().lower()
        phone = input("Phone (optional): ").strip()
        password = input("Password: ").strip()

        payload = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "password": password,
            "password_confirm": password,
            "phone": phone,
            "language": "en",
        }
        resp = self.api_call("POST", "/api/auth/signup/", json=payload)
        self.print_response(resp)

    def customer_login(self) -> None:
        print("\nCustomer Login")
        email = input("Email: ").strip().lower()
        password = input("Password: ").strip()
        remember_me = input("Remember me? (yes/no): ").strip().lower() == "yes"

        payload = {
            "email": email,
            "password": password,
            "remember_me": remember_me,
        }
        resp = self.api_call("POST", "/api/auth/login/", json=payload)
        self.print_response(resp)

        if resp.status_code != 200:
            return

        try:
            data = resp.json().get("data", {})
        except ValueError:
            return

        if data.get("requires_2fa"):
            print("2FA is enabled for this account. Complete 2FA with frontend or API first.")
            return

        access = data.get("access")
        refresh = data.get("refresh")
        if access and refresh:
            self.state.auth_tokens[email] = {"access": access, "refresh": refresh}
            print(f"Stored auth tokens for {email}.")

    def verify_signup_otp(self) -> None:
        print("\nVerify Signup OTP")
        email = input("Email: ").strip().lower()
        otp = input("OTP code: ").strip()
        payload = {"email": email, "otp": otp}
        resp = self.api_call("POST", "/api/auth/verify-email/", json=payload)
        self.print_response(resp)

        if resp.status_code != 200:
            return

        try:
            data = resp.json().get("data", {})
        except ValueError:
            return

        access = data.get("access")
        refresh = data.get("refresh")
        if access and refresh:
            self.state.auth_tokens[email] = {"access": access, "refresh": refresh}
            print(f"Stored auth tokens for {email}.")

    def choose_authenticated_user(self) -> tuple[str, str] | None:
        if not self.state.auth_tokens:
            print("No logged-in users in this session. Run login first.")
            return None

        users = list(self.state.auth_tokens.keys())
        print("Available authenticated users:")
        for idx, email in enumerate(users, start=1):
            print(f"  [{idx}] {email}")
        choice = input("Select user number: ").strip()
        try:
            selected = users[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return None
        return selected, self.state.auth_tokens[selected]["access"]

    def upload_document(self) -> None:
        print("\nUpload Document (valid_id only)")
        selected = self.choose_authenticated_user()
        if not selected:
            return
        owner_email, access_token = selected

        file_path = input("File path to upload: ").strip()
        description = input("Description (optional): ").strip()
        if not os.path.exists(file_path):
            print("File does not exist.")
            return

        with open(file_path, "rb") as source:
            guessed_mime, _ = mimetypes.guess_type(file_path)
            part_mime = guessed_mime or "application/octet-stream"
            files = {"file": (os.path.basename(file_path), source, part_mime)}
            data = {"document_type": DEFAULT_DOC_TYPE, "description": description}
            resp = self.api_call(
                "POST",
                "/api/documents/upload/",
                token=access_token,
                files=files,
                data=data,
            )
        print(f"Detected MIME: {part_mime}")
        self.print_response(resp)

        if resp.status_code == 201:
            try:
                payload = resp.json().get("data", {})
                document_id = payload.get("id")
                if document_id:
                    self.state.uploaded_docs.append(
                        {
                            "document_id": document_id,
                            "owner_email": owner_email,
                            "document_type": DEFAULT_DOC_TYPE,
                        }
                    )
                    print(f"Saved uploaded document id: {document_id}")
            except ValueError:
                pass

    def choose_document(self) -> dict[str, str] | None:
        if not self.state.uploaded_docs:
            manual_id = input("No tracked docs. Enter document_id manually (or blank): ").strip()
            if not manual_id:
                return None
            return {"document_id": manual_id, "owner_email": "unknown", "document_type": DEFAULT_DOC_TYPE}

        print("Tracked documents:")
        for idx, doc in enumerate(self.state.uploaded_docs, start=1):
            print(f"  [{idx}] {doc['document_id']} owner={doc['owner_email']} type={doc['document_type']}")
        print("  [M] Manual document_id")
        choice = input("Select document: ").strip().lower()
        if choice == "m":
            manual_id = input("Enter document_id: ").strip()
            if not manual_id:
                return None
            return {"document_id": manual_id, "owner_email": "unknown", "document_type": DEFAULT_DOC_TYPE}

        try:
            return self.state.uploaded_docs[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return None

    def preview_document(self) -> None:
        print("\nView/Preview Document")
        selected = self.choose_authenticated_user()
        if not selected:
            return
        requester_email, access_token = selected

        doc = self.choose_document()
        if not doc:
            return
        document_id = doc["document_id"]

        resp = self.api_call(
            "GET",
            f"/api/documents/{document_id}/preview/",
            token=access_token,
        )
        print(f"HTTP {resp.status_code}")
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            print(f"Preview stream received: {len(resp.content)} bytes ({content_type})")
            save_copy = input("Save local copy for manual inspection? (yes/no): ").strip().lower() == "yes"
            if save_copy:
                previews_dir = Path("logs/demo_previews")
                previews_dir.mkdir(parents=True, exist_ok=True)
                output_path = previews_dir / f"{document_id}_{requester_email.replace('@', '_at_')}"
                output_path.write_bytes(resp.content)
                print(f"Preview content saved to: {output_path}")
        else:
            self.print_response(resp)

    def run_sanitization_test(self) -> None:
        print("\nRunning input sanitization test with live API calls...")
        unique_suffix = datetime.now().strftime("%Y%m%d%H%M%S")

        xss_payload = {
            "first_name": "<script>alert('xss')</script>",
            "last_name": "Tester",
            "email": f"xss-test-{unique_suffix}@example.com",
            "password": "SecurePass123!",
            "password_confirm": "SecurePass123!",
            "phone": "09171234567",
            "language": "en",
        }
        resp_xss = self.api_call("POST", "/api/auth/signup/", json=xss_payload)
        print("\nXSS payload signup attempt:")
        self.print_response(resp_xss)

        nosql_payload = {
            "first_name": "NoSql",
            "last_name": "{\"$ne\":\"\"}",
            "email": f"nosql-test-{unique_suffix}@example.com",
            "password": "SecurePass123!",
            "password_confirm": "SecurePass123!",
            "phone": "09171234567",
            "language": "en",
        }
        resp_nosql = self.api_call("POST", "/api/auth/signup/", json=nosql_payload)
        print("\nNoSQL payload signup attempt:")
        self.print_response(resp_nosql)

        xss_blocked = resp_xss.status_code in {400, 422}
        nosql_blocked = resp_nosql.status_code in {400, 422}
        print("\nSanitization summary:")
        print(f"  XSS payload blocked: {'YES' if xss_blocked else 'NO'}")
        print(f"  NoSQL payload blocked: {'YES' if nosql_blocked else 'NO'}")

    def run_unauthorized_access_test(self) -> None:
        print("\nUnauthorized access test")
        if len(self.state.auth_tokens) < 2:
            print("At least 2 logged-in users are required (owner and attacker).")
            return

        doc = self.choose_document()
        if not doc:
            return
        target_doc_id = doc["document_id"]
        owner_email = doc.get("owner_email", "")

        attacker_candidates = [email for email in self.state.auth_tokens.keys() if email != owner_email]
        if not attacker_candidates:
            print("No non-owner authenticated user available.")
            return

        print("Attacker candidates:")
        for idx, email in enumerate(attacker_candidates, start=1):
            print(f"  [{idx}] {email}")
        choice = input("Select attacker user number: ").strip()
        try:
            attacker_email = attacker_candidates[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return

        attacker_token = self.state.auth_tokens[attacker_email]["access"]
        resp = self.api_call(
            "GET",
            f"/api/documents/{target_doc_id}/preview/",
            token=attacker_token,
        )
        print("Unauthorized request result:")
        self.print_response(resp)
        print(f"Blocked as expected: {'YES' if resp.status_code in {403, 404} else 'NO'}")

    def export_security_logs(self) -> None:
        source_path = Path(DEFAULT_SECURITY_LOG)
        if not source_path.exists():
            print(f"Security log file not found: {source_path}")
            return

        started_at = self.state.started_at
        exported_events: list[dict[str, Any]] = []
        with source_path.open("r", encoding="utf-8") as source:
            for line in source:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = parse_iso_datetime(event.get("timestamp", ""))
                if timestamp and timestamp >= started_at:
                    exported_events.append(event)

        output_dir = Path("logs")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"security_demo_evidence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path.write_text(json.dumps(exported_events, indent=2), encoding="utf-8")

        print(f"Exported {len(exported_events)} security events to: {output_path}")
        events_by_type: dict[str, int] = {}
        for event in exported_events:
            event_name = event.get("event", "unknown")
            events_by_type[event_name] = events_by_type.get(event_name, 0) + 1
        if events_by_type:
            print("Event summary:")
            for event_name in sorted(events_by_type.keys()):
                print(f"  {event_name}: {events_by_type[event_name]}")

    def show_state(self) -> None:
        print("\nSession state")
        print(f"  Started at: {self.state.started_at.isoformat()}")
        print(f"  Authenticated users: {len(self.state.auth_tokens)}")
        for email in self.state.auth_tokens.keys():
            print(f"    - {email}")
        print(f"  Tracked uploaded documents: {len(self.state.uploaded_docs)}")
        for doc in self.state.uploaded_docs:
            print(f"    - {doc['document_id']} owner={doc['owner_email']}")


def main() -> int:
    base_url = input(f"Backend base URL [{DEFAULT_BASE_URL}]: ").strip() or DEFAULT_BASE_URL
    cli = SecurityDemoCLI(base_url=base_url)
    cli.run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)
