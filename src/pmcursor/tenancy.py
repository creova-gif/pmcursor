"""Multi-tenant organization registry for the PMCursor team layer.

An :class:`OrgRegistry` persists organizations and their API keys to a JSON
store file. Keys are issued as ``pmk_<key_id>_<secret>`` — the secret is shown
once at issue time and only its SHA-256 hash is stored. Resolution parses the
key id, hashes the presented secret, and compares digests in constant time;
revoked keys never resolve.

The registry is opt-in: :func:`default_org_registry` returns ``None`` unless
``PMCURSOR_ORG_STORE`` points at a store file. When configured, the API server
accepts org keys as bearer credentials in addition to the global
``PMCURSOR_API_TOKEN`` admin token and binds the resolved ``org_id`` to the
request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ORG_KEY_PREFIX = "pmk"
_KEY_ID_ALPHABET = "0123456789abcdef"
_ORG_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
DEFAULT_ORG_ID = "default"
ENV_ORG_STORE = "PMCURSOR_ORG_STORE"
ENV_ORG_BACKEND = "PMCURSOR_ORG_BACKEND"
BACKEND_FILE = "file"
BACKEND_SQLITE = "sqlite"
DEFAULT_STORE_PATH = Path(".pmcursor") / "orgs.json"


logger = logging.getLogger("pmcursor.audit")


class OrgRegistryError(RuntimeError):
    """Raised when an org-registry operation cannot be completed."""


class OrgApiKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    key_id: str
    key_hash: str
    label: str = ""
    created_at: str
    revoked: bool = False
    last_used_at: str | None = None


class Org(BaseModel):
    model_config = ConfigDict(frozen=True)

    org_id: str
    name: str
    created_at: str
    keys: list[OrgApiKey] = Field(default_factory=list)
    # Absolute repo-root paths this org may index/audit. An org key with an
    # empty list can authenticate but cannot reach any repository — roots are
    # a least-privilege grant registered by the deployment admin.
    workspace_roots: list[str] = Field(default_factory=list)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _parse_key(token: str) -> tuple[str, str] | None:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != ORG_KEY_PREFIX or not parts[1] or not parts[2]:
        return None
    key_id, secret = parts[1], parts[2]
    if not all(c in _KEY_ID_ALPHABET for c in key_id):
        return None
    return key_id, secret


def _resolve_org_id(name: str, org_id: str | None) -> str:
    resolved = org_id or re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-_")
    if not _ORG_ID_RE.match(resolved):
        raise OrgRegistryError(
            f"invalid org_id {resolved!r}: must match {_ORG_ID_RE.pattern}"
        )
    if not name.strip():
        raise OrgRegistryError("org name must be non-empty")
    return resolved


def _new_key_record(label: str) -> tuple[OrgApiKey, str]:
    key_id = secrets.token_hex(8)
    secret = secrets.token_hex(24)
    return (
        OrgApiKey(
            key_id=key_id,
            key_hash=_hash_secret(secret),
            label=label,
            created_at=_utcnow(),
        ),
        f"{ORG_KEY_PREFIX}_{key_id}_{secret}",
    )


class OrgStore(Protocol):
    """Common interface for org-registry backends (file JSON or SQLite)."""

    @property
    def store_path(self) -> Path: ...

    def verify(self) -> None: ...

    def list_orgs(self) -> list[Org]: ...

    def get_org(self, org_id: str) -> Org | None: ...

    def create_org(self, name: str, org_id: str | None = None) -> tuple[Org, str]: ...

    def issue_key(self, org_id: str, label: str = "") -> str: ...

    def add_workspace_root(self, org_id: str, root: str) -> Org: ...

    def remove_workspace_root(self, org_id: str, root: str) -> Org: ...

    def revoke_key(self, key_id: str) -> bool: ...

    def resolve_key(self, token: str, *, record_use: bool = True) -> str | None: ...


class OrgRegistry:
    """File-backed registry of organizations and their API keys."""

    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._lock = threading.RLock()
        self._orgs: dict[str, Org] = {}
        self._load()

    @property
    def store_path(self) -> Path:
        return self._store_path

    def _read_orgs(self) -> dict[str, Org]:
        if not self._store_path.exists():
            return {}
        if not self._store_path.is_file():
            raise OrgRegistryError(
                f"org store {self._store_path} is not a regular file"
            )
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OrgRegistryError(
                f"org store {self._store_path} is unreadable: {exc}"
            ) from exc
        orgs_obj = data.get("orgs") if isinstance(data, dict) else None
        orgs: dict[str, Org] = {}
        try:
            for item in orgs_obj or []:
                org = Org.model_validate(item)
                orgs[org.org_id] = org
        except ValidationError as exc:
            raise OrgRegistryError(
                f"org store {self._store_path} is invalid: {exc}"
            ) from exc
        return orgs

    def _load(self) -> None:
        with self._lock:
            self._orgs = self._read_orgs()

    def verify(self) -> None:
        """Probe the store for readability without mutating in-memory state.

        Raises :class:`OrgRegistryError` when the file is missing its parent
        data, unreadable, or schema-invalid. Used by the /readyz probe so a
        node with a broken org store reports not-ready instead of failing
        every org-key request.
        """
        self._read_orgs()

    def _save(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"orgs": [org.model_dump(mode="json") for org in self._orgs.values()]}
        fd, tmp_name = tempfile.mkstemp(
            prefix=".orgs-", dir=self._store_path.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")
            os.replace(tmp_name, self._store_path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def list_orgs(self) -> list[Org]:
        with self._lock:
            return sorted(self._orgs.values(), key=lambda o: o.org_id)

    def get_org(self, org_id: str) -> Org | None:
        with self._lock:
            return self._orgs.get(org_id)

    def create_org(self, name: str, org_id: str | None = None) -> tuple[Org, str]:
        """Create an org and return it with its first plaintext API key."""
        resolved_id = _resolve_org_id(name, org_id)
        with self._lock:
            if resolved_id in self._orgs:
                raise OrgRegistryError(f"org {resolved_id!r} already exists")
            record, plaintext = _new_key_record("initial")
            org = Org(
                org_id=resolved_id,
                name=name.strip(),
                created_at=_utcnow(),
                keys=[record],
            )
            self._orgs[resolved_id] = org
            self._save()
            logger.info(
                "event=org_created org_id=%s key_id=%s", resolved_id, record.key_id
            )
            return org, plaintext

    def issue_key(self, org_id: str, label: str = "") -> str:
        """Issue an additional API key for an org; returns plaintext once."""
        with self._lock:
            org = self._orgs.get(org_id)
            if org is None:
                raise OrgRegistryError(f"org {org_id!r} does not exist")
            record, plaintext = _new_key_record(label)
            self._orgs[org_id] = org.model_copy(update={"keys": [*org.keys, record]})
            self._save()
            logger.info("event=org_key_issued org_id=%s key_id=%s", org_id, record.key_id)
            return plaintext

    def add_workspace_root(self, org_id: str, root: str) -> Org:
        """Grant an org access to a repo root path (stored resolved)."""
        resolved = str(Path(root).expanduser().resolve())
        with self._lock:
            org = self._orgs.get(org_id)
            if org is None:
                raise OrgRegistryError(f"org {org_id!r} does not exist")
            if resolved in org.workspace_roots:
                return org
            updated = org.model_copy(
                update={"workspace_roots": [*org.workspace_roots, resolved]}
            )
            self._orgs[org_id] = updated
            self._save()
            logger.info(
                "event=org_roots_updated org_id=%s action=add root=%s",
                org_id,
                resolved,
            )
            return updated

    def remove_workspace_root(self, org_id: str, root: str) -> Org:
        """Revoke an org's access to a repo root path."""
        resolved = str(Path(root).expanduser().resolve())
        with self._lock:
            org = self._orgs.get(org_id)
            if org is None:
                raise OrgRegistryError(f"org {org_id!r} does not exist")
            remaining = [r for r in org.workspace_roots if r != resolved]
            if remaining == list(org.workspace_roots):
                raise OrgRegistryError(
                    f"org {org_id!r} has no workspace root {resolved!r}"
                )
            updated = org.model_copy(update={"workspace_roots": remaining})
            self._orgs[org_id] = updated
            self._save()
            logger.info(
                "event=org_roots_updated org_id=%s action=remove root=%s",
                org_id,
                resolved,
            )
            return updated

    def revoke_key(self, key_id: str) -> bool:
        """Revoke a key by its key id. Returns True when a key was revoked."""
        with self._lock:
            for org_id, org in self._orgs.items():
                keys = [
                    key.model_copy(update={"revoked": True})
                    if key.key_id == key_id
                    else key
                    for key in org.keys
                ]
                if keys != list(org.keys):
                    self._orgs[org_id] = org.model_copy(update={"keys": keys})
                    self._save()
                    logger.info(
                        "event=org_key_revoked org_id=%s key_id=%s",
                        org_id,
                        key_id,
                    )
                    return True
            return False

    def resolve_key(
        self, token: str, *, record_use: bool = True
    ) -> str | None:
        """Resolve a presented ``pmk_`` key to its org id, or None.

        Revoked keys never resolve. On success the key's ``last_used_at`` is
        stamped — the metering hook the SaaS layer builds on. Pass
        ``record_use=False`` for read-only lookups (e.g. rate-limit bucketing)
        that must not write the store.
        """
        parsed = _parse_key(token.strip())
        if parsed is None:
            return None
        key_id, secret = parsed
        presented_hash = _hash_secret(secret)
        with self._lock:
            for org_id, org in self._orgs.items():
                for key in org.keys:
                    if key.key_id != key_id or key.revoked:
                        continue
                    if hmac.compare_digest(key.key_hash, presented_hash):
                        if record_use:
                            keys = [
                                key.model_copy(update={"last_used_at": _utcnow()})
                                if key.key_id == key_id
                                else key
                                for key in org.keys
                            ]
                            self._orgs[org_id] = org.model_copy(
                                update={"keys": keys}
                            )
                            self._save()
                        return org_id
            return None


class SQLiteOrgRegistry:
    """SQLite-backed registry of organizations and their API keys.

    Safe for multi-writer deployments: WAL journal mode plus
    ``PRAGMA busy_timeout`` lets several uvicorn workers (and concurrent CLI
    invocations) share one store file, and every mutation runs in a single
    ``BEGIN IMMEDIATE`` transaction. Unlike :class:`OrgRegistry`, key
    resolution is an indexed lookup rather than a scan.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS orgs(
        org_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS org_keys(
        key_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL REFERENCES orgs(org_id),
        key_hash TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS org_roots(
        org_id TEXT NOT NULL REFERENCES orgs(org_id),
        root TEXT NOT NULL,
        PRIMARY KEY (org_id, root)
    );
    """

    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._lock = threading.RLock()
        if self._store_path.exists() and not self._store_path.is_file():
            raise OrgRegistryError(
                f"org store {self._store_path} is not a regular file"
            )
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OrgRegistryError(
                f"org store {self._store_path} parent cannot be created: {exc}"
            ) from exc
        self._conn = sqlite3.connect(
            str(self._store_path), check_same_thread=False, isolation_level=None
        )
        try:
            # busy_timeout first: it must apply to journal-mode negotiation too.
            # WAL transition can still race a concurrent fresh-store opener, so
            # retry the short init sequence on transient lock contention.
            for attempt in range(3):
                try:
                    self._conn.execute("PRAGMA busy_timeout=5000")
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    self._conn.execute("PRAGMA foreign_keys=ON")
                    self._conn.executescript(self._SCHEMA)
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc) or attempt == 2:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except sqlite3.Error as exc:
            raise OrgRegistryError(
                f"org store {self._store_path} cannot be opened: {exc}"
            ) from exc

    @property
    def store_path(self) -> Path:
        return self._store_path

    def _fetchone(self, sql: str, params: tuple[str, ...] = ()) -> Any:
        try:
            return self._conn.execute(sql, params).fetchone()
        except sqlite3.Error as exc:
            raise OrgRegistryError(
                f"org store {self._store_path} read failed: {exc}"
            ) from exc

    def _fetchall(self, sql: str, params: tuple[str, ...] = ()) -> list[Any]:
        try:
            return list(self._conn.execute(sql, params).fetchall())
        except sqlite3.Error as exc:
            raise OrgRegistryError(
                f"org store {self._store_path} read failed: {exc}"
            ) from exc

    def _rollback(self) -> None:
        if self._conn.in_transaction:
            self._conn.rollback()

    def verify(self) -> None:
        """Probe store integrity (``PRAGMA quick_check``) without mutating."""
        row = self._fetchone("PRAGMA quick_check")
        if row is None or row[0] != "ok":
            raise OrgRegistryError(f"org store {self._store_path} failed integrity check")

    def _org_from_rows(self, org_row: tuple[str, str, str]) -> Org:
        org_id, name, created_at = org_row
        keys = [
            OrgApiKey(
                key_id=key_id,
                key_hash=key_hash,
                label=label,
                created_at=k_created,
                last_used_at=last_used,
                revoked=bool(revoked),
            )
            for key_id, key_hash, label, k_created, last_used, revoked in self._fetchall(
                "SELECT key_id, key_hash, label, created_at, last_used_at, revoked"
                " FROM org_keys WHERE org_id = ? ORDER BY rowid",
                (org_id,),
            )
        ]
        roots = [
            row[0]
            for row in self._fetchall(
                "SELECT root FROM org_roots WHERE org_id = ? ORDER BY rowid", (org_id,)
            )
        ]
        return Org(
            org_id=org_id,
            name=name,
            created_at=created_at,
            keys=keys,
            workspace_roots=roots,
        )

    def _require_org(self, org_id: str) -> tuple[str, str, str]:
        row = self._fetchone(
            "SELECT org_id, name, created_at FROM orgs WHERE org_id = ?", (org_id,)
        )
        if row is None:
            raise OrgRegistryError(f"org {org_id!r} does not exist")
        return row[0], row[1], row[2]

    def list_orgs(self) -> list[Org]:
        with self._lock:
            return [
                self._org_from_rows(row)
                for row in self._fetchall(
                    "SELECT org_id, name, created_at FROM orgs ORDER BY org_id"
                )
            ]

    def get_org(self, org_id: str) -> Org | None:
        with self._lock:
            row = self._fetchone(
                "SELECT org_id, name, created_at FROM orgs WHERE org_id = ?", (org_id,)
            )
            return None if row is None else self._org_from_rows(row)

    def create_org(self, name: str, org_id: str | None = None) -> tuple[Org, str]:
        """Create an org and return it with its first plaintext API key."""
        resolved_id = _resolve_org_id(name, org_id)
        record, plaintext = _new_key_record("initial")
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT INTO orgs(org_id, name, created_at) VALUES (?, ?, ?)",
                    (resolved_id, name.strip(), _utcnow()),
                )
                self._conn.execute(
                    "INSERT INTO org_keys"
                    "(key_id, org_id, key_hash, label, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (record.key_id, resolved_id, record.key_hash, record.label, record.created_at),
                )
                self._conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._rollback()
                raise OrgRegistryError(f"org {resolved_id!r} already exists") from exc
            except sqlite3.Error as exc:
                self._rollback()
                raise OrgRegistryError(f"create_org failed: {exc}") from exc
        logger.info(
            "event=org_created org_id=%s key_id=%s", resolved_id, record.key_id
        )
        org = self.get_org(resolved_id)
        if org is None:
            raise OrgRegistryError(f"org {resolved_id!r} missing after insert")
        return org, plaintext

    def issue_key(self, org_id: str, label: str = "") -> str:
        """Issue an additional API key for an org; returns plaintext once."""
        record, plaintext = _new_key_record(label)
        with self._lock:
            self._require_org(org_id)
            try:
                self._conn.execute(
                    "INSERT INTO org_keys"
                    "(key_id, org_id, key_hash, label, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (record.key_id, org_id, record.key_hash, record.label, record.created_at),
                )
            except sqlite3.Error as exc:
                raise OrgRegistryError(f"issue_key failed: {exc}") from exc
        logger.info("event=org_key_issued org_id=%s key_id=%s", org_id, record.key_id)
        return plaintext

    def add_workspace_root(self, org_id: str, root: str) -> Org:
        """Grant an org access to a repo root path (stored resolved)."""
        resolved = str(Path(root).expanduser().resolve())
        with self._lock:
            self._require_org(org_id)
            try:
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO org_roots(org_id, root) VALUES (?, ?)",
                    (org_id, resolved),
                )
            except sqlite3.Error as exc:
                raise OrgRegistryError(f"add_workspace_root failed: {exc}") from exc
            if cursor.rowcount == 0:
                org = self.get_org(org_id)
                if org is None:
                    raise OrgRegistryError(f"org {org_id!r} does not exist")
                return org
        logger.info(
            "event=org_roots_updated org_id=%s action=add root=%s", org_id, resolved
        )
        org = self.get_org(org_id)
        if org is None:
            raise OrgRegistryError(f"org {org_id!r} does not exist")
        return org

    def remove_workspace_root(self, org_id: str, root: str) -> Org:
        """Revoke an org's access to a repo root path."""
        resolved = str(Path(root).expanduser().resolve())
        with self._lock:
            self._require_org(org_id)
            try:
                cursor = self._conn.execute(
                    "DELETE FROM org_roots WHERE org_id = ? AND root = ?",
                    (org_id, resolved),
                )
            except sqlite3.Error as exc:
                raise OrgRegistryError(f"remove_workspace_root failed: {exc}") from exc
            if cursor.rowcount == 0:
                raise OrgRegistryError(
                    f"org {org_id!r} has no workspace root {resolved!r}"
                )
        logger.info(
            "event=org_roots_updated org_id=%s action=remove root=%s", org_id, resolved
        )
        org = self.get_org(org_id)
        if org is None:
            raise OrgRegistryError(f"org {org_id!r} does not exist")
        return org

    def revoke_key(self, key_id: str) -> bool:
        """Revoke a key by its key id. Returns True when a key was revoked."""
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "UPDATE org_keys SET revoked = 1 WHERE key_id = ? AND revoked = 0",
                    (key_id,),
                )
                if cursor.rowcount == 0:
                    return False
                row = self._fetchone(
                    "SELECT org_id FROM org_keys WHERE key_id = ?", (key_id,)
                )
            except sqlite3.Error as exc:
                raise OrgRegistryError(f"revoke_key failed: {exc}") from exc
        org_id = row[0] if row else ""
        logger.info("event=org_key_revoked org_id=%s key_id=%s", org_id, key_id)
        return True

    def resolve_key(
        self, token: str, *, record_use: bool = True
    ) -> str | None:
        """Resolve a presented ``pmk_`` key to its org id, or None.

        Revoked keys never resolve. On success the key's ``last_used_at`` is
        stamped — the metering hook the SaaS layer builds on. Pass
        ``record_use=False`` for read-only lookups (e.g. rate-limit bucketing)
        that must not write the store.
        """
        parsed = _parse_key(token.strip())
        if parsed is None:
            return None
        key_id, secret = parsed
        presented_hash = _hash_secret(secret)
        with self._lock:
            row = self._fetchone(
                "SELECT org_id, key_hash, revoked FROM org_keys WHERE key_id = ?",
                (key_id,),
            )
            if row is None or row[2] or not hmac.compare_digest(row[1], presented_hash):
                return None
            if record_use:
                try:
                    self._conn.execute(
                        "UPDATE org_keys SET last_used_at = ? WHERE key_id = ?",
                        (_utcnow(), key_id),
                    )
                except sqlite3.Error as exc:
                    raise OrgRegistryError(f"resolve_key failed: {exc}") from exc
            return str(row[0])


def org_registry_for_path(
    store_path: Path, backend: str | None = None
) -> OrgStore:
    """Build the registry backend for a store path.

    ``backend`` is ``file`` (default) or ``sqlite``; when unset it reads
    ``PMCURSOR_ORG_BACKEND``. Unknown values raise ``OrgRegistryError``.
    """
    selected = (
        backend
        if backend is not None
        else os.environ.get(ENV_ORG_BACKEND, BACKEND_FILE)
    ).strip().lower()
    if selected == BACKEND_SQLITE:
        return SQLiteOrgRegistry(store_path)
    if selected in {"", BACKEND_FILE}:
        return OrgRegistry(store_path)
    raise OrgRegistryError(
        f"unknown {ENV_ORG_BACKEND} value {selected!r}: "
        f"expected '{BACKEND_FILE}' or '{BACKEND_SQLITE}'"
    )


def default_org_registry(env: dict[str, str] | None = None) -> OrgStore | None:
    """Build a registry when ``PMCURSOR_ORG_STORE`` is set, else None.

    Backend is selected by ``PMCURSOR_ORG_BACKEND`` (``file`` default,
    ``sqlite`` for multi-writer deployments).
    """
    environ = env if env is not None else os.environ
    raw = environ.get(ENV_ORG_STORE, "").strip()
    if not raw:
        return None
    return org_registry_for_path(Path(raw), environ.get(ENV_ORG_BACKEND, "").strip())
