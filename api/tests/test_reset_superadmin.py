"""reset_superadmin.py: the password is never taken from the command line, it is validated, the reset clears the lockout and the sessions,
and the .env file the API reads at start-up is kept in step (otherwise the next restart would undo the reset)."""
import os
import re
import sys

import pytest

_api_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _api_dir not in sys.path:
    sys.path.insert(0, _api_dir)

import reset_superadmin as rs

GOOD = "Fresh-Superadmin#Pass9"
OLD = "TestSuperAdmin@1"          # SUPERADMIN_PASSWORD set by tests/conftest.py


@pytest.fixture(autouse=True)
def restore_superadmin(app):
    """The test database is shared by the whole session: put the superadmin back the way conftest set it."""
    yield
    from extensions import db
    from models.user import User
    from utils.superadmin import SUPERADMIN_EMAIL, ensure_superadmin
    ensure_superadmin()
    sa = User.query.filter_by(email=SUPERADMIN_EMAIL).first()
    sa.set_password(OLD)
    sa.is_locked, sa.locked_until, sa.failed_login_attempts, sa.mfa_enabled = False, None, 0, False
    db.session.commit()


def run(app, argv, *, typed=(GOOD, GOOD), answers="YES", stdin=None):
    it = iter(typed)
    return rs.main(argv, prompt=lambda _q: next(it), confirm=lambda _q: answers, stdin=stdin, app_factory=lambda: app)


def superadmin():
    from extensions import db
    from models.user import User
    db.session.expire_all()      # the script works in its own application context; do not read stale rows
    from utils.superadmin import SUPERADMIN_EMAIL
    return User.query.filter_by(email=SUPERADMIN_EMAIL).first()


class TestPasswordRules:
    @pytest.mark.parametrize("pw,fragment", [
        ("Sh0rt#", "10 characters"), ("alllowercase#1x", "uppercase"), ("NoDigitsHere#xx", "number"), ("NoSpecials123Abc", "special"),
    ])
    def test_weak_passwords_are_listed(self, pw, fragment):
        assert any(fragment in p for p in rs.validate(pw))

    def test_a_good_password_passes(self):
        assert rs.validate(GOOD) == []

    def test_generated_passwords_are_strong_and_safe_to_paste(self):
        seen = set()
        for _ in range(200):
            pw = rs.generate_password()
            assert len(pw) >= 12 and rs.validate(pw) == []
            assert not re.search(r"""['"\\#$\s`]""", pw)
            seen.add(pw)
        assert len(seen) == 200


class TestSecretFile:
    def test_creates_a_new_file_and_never_overwrites(self, tmp_path):
        f = tmp_path / "pw.txt"
        rs.write_secret_file(f, "secret")
        assert f.read_text(encoding="utf-8") == "secret"
        with pytest.raises(FileExistsError):
            rs.write_secret_file(f, "other")
        assert f.read_text(encoding="utf-8") == "secret"


class TestEnvFile:
    def test_replaces_the_line_and_keeps_the_rest(self, tmp_path):
        f = tmp_path / ".env"
        f.write_bytes(b"A=1\r\nSUPERADMIN_PASSWORD=old\r\n# note\r\nB=2\r\n")
        assert rs.update_env_file(f, "SUPERADMIN_PASSWORD", "New#Pass1") is True
        raw = f.read_bytes().decode()
        assert raw == "A=1\r\nSUPERADMIN_PASSWORD='New#Pass1'\r\n# note\r\nB=2\r\n"
        assert [p.name for p in tmp_path.iterdir()] == [".env"]                      # no temp file left behind

    def test_adds_the_line_when_missing(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("A=1\n", encoding="utf-8")
        rs.update_env_file(f, "SUPERADMIN_PASSWORD", "x")
        assert f.read_text(encoding="utf-8").splitlines() == ["A=1", "SUPERADMIN_PASSWORD='x'"]

    def test_removes_a_duplicate_definition(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("SUPERADMIN_PASSWORD=a\nX=1\nSUPERADMIN_PASSWORD=b\n", encoding="utf-8")
        rs.update_env_file(f, "SUPERADMIN_PASSWORD", "c")
        assert f.read_text(encoding="utf-8").count("SUPERADMIN_PASSWORD") == 1

    def test_missing_file_is_reported_not_created(self, tmp_path):
        assert rs.update_env_file(tmp_path / "nope.env", "K", "v") is False
        assert not (tmp_path / "nope.env").exists()

    @pytest.mark.parametrize("pw", ["Plain#Pass1", "has 'quote' and \\ back#slash1A", "dollar$sign#Abc1 and spaces", "a=b#c1A"])
    def test_every_password_reads_back_exactly(self, tmp_path, pw):
        from dotenv import dotenv_values
        f = tmp_path / ".env"
        f.write_text("A=1\n", encoding="utf-8")
        rs.update_env_file(f, "SUPERADMIN_PASSWORD", pw)
        assert dotenv_values(f)["SUPERADMIN_PASSWORD"] == pw


class TestMain:
    def test_a_password_on_the_command_line_is_refused(self, app, capsys):
        assert run(app, ["Secret#Pass12345"]) == 2
        out = capsys.readouterr()
        assert "no longer accepted" in out.err and "Secret#Pass12345" not in out.out + out.err
        assert not superadmin().check_password("Secret#Pass12345")

    def test_typed_password_is_set(self, app, capsys):
        assert run(app, ["--no-env", "--yes"]) == 0
        assert superadmin().check_password(GOOD) and not superadmin().check_password(OLD)
        out = capsys.readouterr().out
        assert GOOD not in out and "WARNING" in out and "NOT changed anywhere" in out

    def test_two_entries_that_differ_change_nothing(self, app):
        assert run(app, ["--no-env", "--yes"], typed=(GOOD, GOOD + "x")) == 1
        assert superadmin().check_password(OLD)

    def test_weak_password_changes_nothing(self, app, capsys):
        assert run(app, ["--no-env", "--yes"], typed=("weak", "weak")) == 1
        assert superadmin().check_password(OLD) and "not acceptable" in capsys.readouterr().err

    def test_not_confirming_changes_nothing(self, app):
        assert run(app, ["--no-env"], answers="no") == 1
        assert superadmin().check_password(OLD)

    def test_reset_unlocks_ends_sessions_and_records_it_without_the_password(self, app):
        from datetime import datetime, timedelta, timezone
        from extensions import db
        from models.audit import AuditLog
        from models.user_session import UserSession
        from utils.superadmin import ensure_superadmin
        ensure_superadmin()
        sa = superadmin()
        sa.is_locked, sa.locked_until, sa.failed_login_attempts = True, datetime.now(timezone.utc) + timedelta(minutes=5), 3
        db.session.add(UserSession(user_id=sa.id, device_fp="f" * 32, refresh_jti="j" * 36))
        db.session.commit()
        before = AuditLog.query.filter_by(user_id=sa.id, action="superadmin_password_reset").count()
        assert run(app, ["--no-env", "--yes"]) == 0
        sa = superadmin()
        assert (sa.is_locked, sa.locked_until, sa.failed_login_attempts, sa.must_change_password) == (False, None, 0, False)
        assert UserSession.query.filter_by(user_id=sa.id).count() == 0
        rows = AuditLog.query.filter_by(user_id=sa.id, action="superadmin_password_reset").all()
        assert len(rows) == before + 1 and GOOD not in str(rows[-1].payload)
        assert AuditLog.query.filter_by(user_id=sa.id, action="login_unlocked").count() >= 1

    def test_generate_shows_a_working_password_once(self, app, capsys):
        assert run(app, ["--generate", "--no-env", "--yes"]) == 0
        out = capsys.readouterr().out
        shown = re.search(r"New password \(shown once\): (\S+)", out).group(1)
        assert superadmin().check_password(shown)

    def test_generate_to_a_file_keeps_it_off_the_screen(self, app, tmp_path, capsys):
        f = tmp_path / "new-pw.txt"
        assert run(app, ["--generate", "--out", str(f), "--no-env", "--yes"]) == 0
        pw = re.search(r"Password: (\S+)", f.read_text(encoding="utf-8")).group(1)
        assert superadmin().check_password(pw) and pw not in capsys.readouterr().out

    def test_an_existing_output_file_stops_everything_before_any_change(self, app, tmp_path, capsys):
        f = tmp_path / "taken.txt"
        f.write_text("keep me", encoding="utf-8")
        assert run(app, ["--generate", "--out", str(f), "--no-env", "--yes"]) == 1
        assert f.read_text(encoding="utf-8") == "keep me" and superadmin().check_password(OLD)

    def test_out_needs_generate(self, app, tmp_path):
        assert run(app, ["--out", str(tmp_path / "x.txt")]) == 2

    def test_the_env_file_is_updated_so_a_restart_keeps_the_reset(self, app, tmp_path, capsys):
        from dotenv import dotenv_values
        f = tmp_path / ".env"
        f.write_text("SUPERADMIN_PASSWORD=old-value\nOTHER=1\n", encoding="utf-8")
        assert run(app, ["--env-file", str(f), "--yes"]) == 0
        assert dotenv_values(f)["SUPERADMIN_PASSWORD"] == GOOD and dotenv_values(f)["OTHER"] == "1"
        assert "so a restart keeps it" in capsys.readouterr().out

    def test_password_can_come_from_standard_input(self, app):
        import io
        assert run(app, ["--stdin", "--no-env", "--yes"], stdin=io.StringIO(GOOD + "\n")) == 0
        assert superadmin().check_password(GOOD)

    def test_reset_mfa(self, app):
        from extensions import db
        sa = superadmin()
        sa.mfa_enabled = True
        sa.set_mfa_secret("JBSWY3DPEHPK3PXP")
        db.session.commit()
        assert run(app, ["--no-env", "--yes", "--reset-mfa"]) == 0
        sa = superadmin()
        assert sa.mfa_enabled is False and sa.mfa_secret is None
