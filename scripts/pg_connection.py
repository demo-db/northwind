"""Convert a PostgreSQL URL from DATABASE_URL to libpq environment settings."""
from __future__ import annotations

import os
from urllib.parse import parse_qsl, unquote, urlsplit


_QUERY_ENV = {
    "application_name": "PGAPPNAME",
    "channel_binding": "PGCHANNELBINDING",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "gssencmode": "PGGSSENCMODE",
    "options": "PGOPTIONS",
    "replication": "PGREPLICATION",
    "sslcert": "PGSSLCERT",
    "sslcompression": "PGSSLCOMPRESSION",
    "sslcrl": "PGSSLCRL",
    "sslkey": "PGSSLKEY",
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
}


def libpq_environment(database_url: str) -> dict[str, str]:
    parsed = urlsplit(database_url)
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("DATABASE_URL must be a postgresql:// or postgres:// URL with host and database")
    env = os.environ.copy()
    env["PGHOST"] = parsed.hostname
    if parsed.port is not None:
        env["PGPORT"] = str(parsed.port)
    if parsed.username is not None:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    env["PGDATABASE"] = unquote(parsed.path.lstrip("/"))
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in _QUERY_ENV:
            env[_QUERY_ENV[key]] = value
    return env
