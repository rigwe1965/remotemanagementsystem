"""
Emergency CLI: reset the built-in superadmin's password and unlock the account.

Run from the api/ directory:

    python reset_superadmin.py                       asks for the new password twice (nothing is shown as you type)
    python reset_superadmin.py --generate            makes a strong random password and shows it once
    python reset_superadmin.py --generate --out F    writes the generated password to the new file F instead of the screen
    some-command | python reset_superadmin.py --stdin    reads the password from standard input (automation)

Options:
    --env-file PATH   also set SUPERADMIN_PASSWORD in this .env file (default: the .env the API reads, when there is one)
    --no-env          do not touch any .env file
    --reset-mfa       also switch off the superadmin's two-step verification (lost phone)
    --yes             do not ask for confirmation

The password is NOT accepted on the command line: it would stay in your shell history and be visible to other programs in the
process list.

Why the .env file matters: the API sets the superadmin's password back to SUPERADMIN_PASSWORD (from the environment) every time it
starts. If that setting is not updated too, the next restart undoes this reset. When the API runs from a .env file this script
updates it for you; when the setting lives elsewhere (Docker, a service manager) it tells you to change it there.

What it does: sets the password (at least 10 characters with an uppercase letter, a number and a special character), clears the
lockout and every address's failed-sign-in count, ends the superadmin's existing sessions, leaves "must change password" off (the
account is managed through SUPERADMIN_PASSWORD), and records "superadmin_password_reset" in the audit log (never the password).
"""
import argparse
import getpass
import os
import re
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_LENGTH = 10
_SPECIALS_FOR_GENERATED = "!@%^*-_+=.,?"   # no quotes, backslash, #, $ or spaces: safe to paste anywhere and into a .env file


def validate(password: str) -> list:
    """Reasons the password is not acceptable (empty list = fine). Same rules as the app, plus the 10-character minimum."""
    from utils.password import validate_password
    problems = []
    if len(password) < MIN_LENGTH:
        problems.append(f"at least {MIN_LENGTH} characters")
    problems += [p for p in validate_password(password) if not p.startswith("at least 8 characters")]
    return problems


def generate_password(length: int = 20) -> str:
    """A random password with at least one lowercase, uppercase, digit and special character."""
    pools = ["abcdefghijkmnopqrstuvwxyz", "ABCDEFGHJKLMNPQRSTUVWXYZ", "23456789", _SPECIALS_FOR_GENERATED]
    chars = [secrets.choice(p) for p in pools]
    allchars = "".join(pools)
    chars += [secrets.choice(allchars) for _ in range(max(length, 12) - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def write_secret_file(path, text: str) -> None:
    """Create a NEW file that only the current user can read. Never overwrites."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def _env_quote(value: str) -> str:
    """A .env value python-dotenv reads back exactly: single quotes, with backslash and quote escaped."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def update_env_file(path, key: str, value: str) -> bool:
    """Set KEY in a .env file (replace the line, or add it), keeping every other line and the line endings. Atomic."""
    path = Path(path)
    if not path.exists():
        return False
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(key)}\s*=")
    new_line = f"{key}={_env_quote(value)}"
    replaced = False
    out = []
    for line in lines:
        if pattern.match(line):
            if not replaced:
                out.append(new_line)
                replaced = True
            continue                      # drop a duplicate definition of the same key
        out.append(line)
    if not replaced:
        out.append(new_line)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".env.tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write((newline.join(out) + newline).encode("utf-8"))
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return True


def reset(password: str, *, reset_mfa: bool = False, generated: bool = False, env_updated: bool = False):
    """Do the reset. Must run inside an application context. Returns the superadmin User."""
    from extensions import db
    from models.audit import AuditLog
    from models.user import User
    from models.user_session import UserSession
    from utils.superadmin import SUPERADMIN_EMAIL, ensure_superadmin

    ensure_superadmin()
    sa = User.query.filter_by(email=SUPERADMIN_EMAIL).first()
    now = datetime.now(timezone.utc)
    sa.set_password(password)
    sa.password_changed_at = now
    sa.is_active = True
    sa.must_change_password = False
    sa.is_locked = False
    sa.locked_until = None
    sa.failed_login_attempts = 0
    if reset_mfa:
        sa.mfa_enabled = False
        sa.set_mfa_secret(None)
    UserSession.query.filter_by(user_id=sa.id).delete()          # end every existing session
    db.session.add(AuditLog(user_id=sa.id, action="login_unlocked", resource_type="user"))   # clears every address's count
    db.session.add(AuditLog(user_id=sa.id, action="superadmin_password_reset", resource_type="user",
                            payload={"via": "reset_superadmin.py", "generated": generated, "env_file_updated": env_updated,
                                     "mfa_reset": reset_mfa}))
    db.session.commit()
    return sa


def _read_password(args, prompt, stdin) -> str:
    if args.generate:
        return generate_password()
    if args.stdin:
        return (stdin or sys.stdin).readline().rstrip("\r\n")
    first = prompt("New superadmin password: ")
    if first != prompt("Type it again: "):
        raise SystemExit("The two entries do not match. Nothing was changed.")
    return first


def build_parser():
    p = argparse.ArgumentParser(prog="reset_superadmin.py", description="Reset the built-in superadmin's password.")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--generate", action="store_true", help="make a strong random password")
    src.add_argument("--stdin", action="store_true", help="read the password from standard input")
    p.add_argument("--out", metavar="FILE", help="with --generate: write the password to this NEW file instead of the screen")
    env = p.add_mutually_exclusive_group()
    env.add_argument("--env-file", metavar="PATH", help="also set SUPERADMIN_PASSWORD in this .env file")
    env.add_argument("--no-env", action="store_true", help="do not touch any .env file")
    p.add_argument("--reset-mfa", action="store_true", help="also switch off two-step verification")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    return p


def main(argv=None, *, prompt=getpass.getpass, stdin=None, app_factory=None, confirm=input) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # The old form took the password as an argument. A stray argument is refused (never echoed): it may be a password.
    args, stray = build_parser().parse_known_args(argv)
    if stray:
        print("The password is no longer accepted on the command line (it would stay in your shell history).\n"
              "Run:  python reset_superadmin.py            to type it (hidden)\n"
              "  or  python reset_superadmin.py --generate  to get a random one", file=sys.stderr)
        return 2
    if args.out and not args.generate:
        print("--out only works together with --generate.", file=sys.stderr)
        return 2

    try:
        from dotenv import find_dotenv, load_dotenv
        env_path = find_dotenv(usecwd=True)
        load_dotenv(env_path or None)
    except Exception:
        env_path = ""
    try:
        password = _read_password(args, prompt, stdin)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1
    problems = validate(password)
    if problems:
        print("That password is not acceptable. It needs: " + ", ".join(problems) + ". Nothing was changed.", file=sys.stderr)
        return 1

    if app_factory is None:
        def app_factory():
            from app import create_app
            return create_app()
    try:
        app = app_factory()
    except RuntimeError as e:      # utils/superadmin.py refuses to load without SUPERADMIN_PASSWORD in the environment
        print(f"Cannot start: {e}", file=sys.stderr)
        return 1

    if not args.yes:
        try:
            answer = str(confirm("This changes the superadmin's password and ends its sessions. Type YES to continue: ")).strip()
        except EOFError:
            answer = ""
            print("(No answer could be read. When the password comes from --stdin, add --yes.)", file=sys.stderr)
        if answer != "YES":
            print("Cancelled. Nothing was changed.")
            return 1

    from utils.superadmin import SUPERADMIN_EMAIL
    # Everything that can fail without side effects happens BEFORE the database changes: a password nobody saw must never be set.
    if args.generate and args.out:
        try:
            write_secret_file(args.out, f"Superadmin: {SUPERADMIN_EMAIL}\nPassword: {password}\n")
        except FileExistsError:
            print(f"{args.out} already exists; it is never overwritten. Nothing was changed.", file=sys.stderr)
            return 1
        except OSError as e:
            print(f"Cannot write {args.out}: {e}. Nothing was changed.", file=sys.stderr)
            return 1

    target_env = None if args.no_env else (args.env_file or env_path or None)
    with app.app_context():
        sa = reset(password, reset_mfa=args.reset_mfa, generated=args.generate,
                   env_updated=bool(target_env and Path(target_env).exists()))
        email = sa.email

    env_updated = False
    if target_env:
        try:
            env_updated = update_env_file(target_env, "SUPERADMIN_PASSWORD", password)
        except OSError as e:
            print(f"  (Could not update {target_env}: {e})", file=sys.stderr)

    print("Superadmin password reset.")
    print(f"  Email:  {email}")
    print("  Existing sessions were ended, and the account is unlocked.")
    if args.generate:
        if args.out:
            print(f"  The new password was written to {args.out} (only you can read it). Delete the file after you saved it.")
        else:
            print(f"  New password (shown once): {password}")
    if env_updated:
        print(f"  SUPERADMIN_PASSWORD was updated in {target_env}, so a restart keeps it.")
    else:
        print("  WARNING: SUPERADMIN_PASSWORD was NOT changed anywhere. The API sets the superadmin's password back to that\n"
              "  setting every time it starts: change it too (in .env, Docker or your service settings), or this reset is undone\n"
              "  at the next restart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
