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
import os
import re
import secrets
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ORG_KEY_PREFIX = "pmk"
_KEY_ID_ALPHABET = "0123456789abcdef"
_ORG_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
DEFAULT_ORG_ID = "default"
ENV_ORG_STORE = "PMCURSOR_ORG_STORE"
DEFAULT_STORE_PATH = Path(".pmcursor") / "orgs.json"


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

    def _load(self) -> None:
        with self._lock:
            if not self._store_path.is_file():
                self._orgs = {}
                return
            try:
                data = json.loads(self._store_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OrgRegistryError(
                    f"org store {self._store_path} is unreadable: {exc}"
                ) from exc
            orgs_obj = data.get("orgs") if isinstance(data, dict) else None
            self._orgs = {}
            for item in orgs_obj or []:
                org = Org.model_validate(item)
                self._orgs[org.org_id] = org

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

    @staticmethod
    def _validate_org_id(org_id: str) -> None:
        if not _ORG_ID_RE.match(org_id):
            raise OrgRegistryError(
                f"invalid org_id {org_id!r}: must match {_ORG_ID_RE.pattern}"
            )

    def list_orgs(self) -> list[Org]:
        with self._lock:
            return sorted(self._orgs.values(), key=lambda o: o.org_id)

    def get_org(self, org_id: str) -> Org | None:
        with self._lock:
            return self._orgs.get(org_id)

    def create_org(self, name: str, org_id: str | None = None) -> tuple[Org, str]:
        """Create an org and return it with its first plaintext API key."""
        resolved_id = org_id or re.sub(
            r"[^a-z0-9_-]+", "-", name.strip().lower()
        ).strip("-_")
        self._validate_org_id(resolved_id)
        if not name.strip():
            raise OrgRegistryError("org name must be non-empty")
        with self._lock:
            if resolved_id in self._orgs:
                raise OrgRegistryError(f"org {resolved_id!r} already exists")
            key_id = secrets.token_hex(8)
            secret = secrets.token_hex(24)
            record = OrgApiKey(
                key_id=key_id,
                key_hash=_hash_secret(secret),
                label="initial",
                created_at=_utcnow(),
            )
            org = Org(
                org_id=resolved_id,
                name=name.strip(),
                created_at=_utcnow(),
                keys=[record],
            )
            self._orgs[resolved_id] = org
            self._save()
            return org, f"{ORG_KEY_PREFIX}_{key_id}_{secret}"

    def issue_key(self, org_id: str, label: str = "") -> str:
        """Issue an additional API key for an org; returns plaintext once."""
        with self._lock:
            org = self._orgs.get(org_id)
            if org is None:
                raise OrgRegistryError(f"org {org_id!r} does not exist")
            key_id = secrets.token_hex(8)
            secret = secrets.token_hex(24)
            record = OrgApiKey(
                key_id=key_id,
                key_hash=_hash_secret(secret),
                label=label,
                created_at=_utcnow(),
            )
            self._orgs[org_id] = org.model_copy(update={"keys": [*org.keys, record]})
            self._save()
            return f"{ORG_KEY_PREFIX}_{key_id}_{secret}"

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


def default_org_registry(env: dict[str, str] | None = None) -> OrgRegistry | None:
    """Build a registry when ``PMCURSOR_ORG_STORE`` is set, else None."""
    environ = env if env is not None else os.environ
    raw = environ.get(ENV_ORG_STORE, "").strip()
    if not raw:
        return None
    return OrgRegistry(Path(raw))
