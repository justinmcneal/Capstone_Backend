"""Safety regressions for the encrypted MongoDB restore workflow."""

from scripts import restore_encrypted_backup


def _restore_environment(monkeypatch, *, source="capstone", target="capstone_restore_test"):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example.test")
    monkeypatch.setenv("BACKUP_ENCRYPTION_PASSPHRASE", "test-passphrase")
    monkeypatch.setenv("MONGODB_NAME", source)
    monkeypatch.setenv("BACKUP_RESTORE_DB_NAME", target)
    monkeypatch.setattr(restore_encrypted_backup, "_require_binary", lambda _name: None)


def test_restore_refuses_to_overwrite_source_database(tmp_path, monkeypatch):
    archive = tmp_path / "backup.archive.gz.enc"
    archive.write_bytes(b"encrypted-test-placeholder")
    _restore_environment(monkeypatch, source="capstone", target="capstone")

    assert restore_encrypted_backup.main(["restore", str(archive)]) == 1


def test_restore_is_fail_fast_and_bypasses_validator_for_legacy_evidence(
    tmp_path, monkeypatch
):
    archive = tmp_path / "backup.archive.gz.enc"
    archive.write_bytes(b"encrypted-test-placeholder")
    _restore_environment(monkeypatch)
    calls = []

    class FakeStream:
        def close(self):
            return None

    class FakeProcess:
        def __init__(self, has_stdout=False):
            self.stdout = FakeStream() if has_stdout else None

        def wait(self):
            return 0

    def fake_popen(command, **_kwargs):
        calls.append(command)
        return FakeProcess(has_stdout=len(calls) == 1)

    monkeypatch.setattr(restore_encrypted_backup.subprocess, "Popen", fake_popen)

    assert restore_encrypted_backup.main(["restore", str(archive)]) == 0
    restore_command = calls[1]
    assert "--drop" in restore_command
    assert "--stopOnError" in restore_command
    assert "--bypassDocumentValidation" in restore_command
    assert "capstone_restore_test.*" in restore_command
