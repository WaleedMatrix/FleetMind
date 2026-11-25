"""Create the initial administrator and provision local prediction credentials."""

import argparse
import os
import warnings
from getpass import GetPassWarning, getpass
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from fleetmind.security.contracts import AccountCreate, ServiceCreate
from fleetmind.security.models import UserAccount
from fleetmind.security.store import SecurityError, SecurityStore


def read_password(prompt):
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        return getpass(prompt)


def bootstrap(store, username):
    password = read_password("Administrator password: ")
    if password != read_password("Confirm password: "):
        raise SecurityError(400, "Passwords do not match.")
    account = AccountCreate(
        username=username.strip().lower(), password=password, role="administrator"
    )
    store.create_user(
        account.username, account.password.get_secret_value(), account.role
    )
    print("Initial administrator created.")


def create_service(store, args):
    payload = ServiceCreate(name=args.name, expires_in_days=args.days)
    with store.factory() as db:
        creator = db.scalar(
            select(UserAccount.id).where(
                UserAccount.username == args.administrator.strip().lower(),
            )
        )
    if creator is None:
        raise SecurityError(403, "Choose an active administrator.")
    handle = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(handle, "w", encoding="ascii") as stream:
            token, identifier = store.new_service(
                payload.name, payload.expires_in_days, creator
            )
            try:
                stream.write(token + "\n")
                stream.flush()
            except OSError:
                store.revoke_service(identifier, creator)
                raise
    except Exception:
        args.output.unlink(missing_ok=True)
        raise
    print(
        f"Created prediction credential {identifier}. "
        "Secure the output file with OS permissions."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("bootstrap")
    first.add_argument("--username", required=True)
    service = commands.add_parser("create-service")
    service.add_argument("--name", required=True)
    service.add_argument("--administrator", required=True)
    service.add_argument("--days", type=int, default=30)
    service.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = SecurityStore()
    try:
        if args.command == "bootstrap":
            bootstrap(store, args.username)
        else:
            create_service(store, args)
    except SecurityError as exc:
        parser.exit(1, f"{exc}\n")
    except ValidationError:
        parser.exit(
            1, "Invalid account or credential input. Use a 12–128 character password.\n"
        )
    except (SQLAlchemyError, GetPassWarning, OSError, EOFError):
        parser.exit(
            1, "Operation failed. Check migration, terminal, and file permissions.\n"
        )


if __name__ == "__main__":
    main()
