#!/usr/bin/env python3
"""Apply the generated PostgreSQL import using psql and DATABASE_URL."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from pg_connection import libpq_environment

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true", help="replace northwind schema only when its source-hash provenance matches")
    parser.add_argument("--sql", type=Path, default=ROOT / "artifacts/hosting-imports/postgres.sql")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL must be set")
    if not args.sql.is_file():
        parser.error(f"SQL file not found: {args.sql}")

    try:
        env = libpq_environment(database_url)
    except ValueError as error:
        parser.error(str(error))
    if args.replace:
        env["PGOPTIONS"] = (env.get("PGOPTIONS", "") + " -c northwind.allow_replace=on").strip()
    result = subprocess.run(
        ["psql", "--no-psqlrc", "--set", "ON_ERROR_STOP=1", "--file", str(args.sql)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        print(f"PostgreSQL import failed (psql exit {result.returncode}); connection details were suppressed.", file=sys.stderr)
        return result.returncode
    print("Northwind PostgreSQL import completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
