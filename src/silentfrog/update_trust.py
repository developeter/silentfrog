"""Signed-release trust for the Silentfrog updater (v2.0 H7 / PR-18).

The updater no longer trusts "whatever is on the ``dev`` branch". Instead a
GitHub Release (derived from a ``v*`` tag) carries a minisign-signed manifest
listing the SHA-256 of the source archive and the pinned Python installer.
This module verifies that manifest against a public key **pinned in-repo**
using the vendored pure-Python Ed25519 verifier (no dependency, no external
binary), then checks the downloaded archive's hash against the manifest.

Everything here fails closed: a missing pinned key, a bad signature, a wrong
key id, a tampered manifest, or a hash mismatch all raise :class:`TrustError`
(or return False), so the updater refuses the swap rather than installing
unverified code. A same-channel checksum alone is never trusted — only a
signature made by the pinned key.

The pinned key is empty in the repository until the maintainer pastes their
minisign public key into ``PINNED_PUBLIC_KEY`` (see ``docs/`` / the release
procedure). While it is empty the updater verifies nothing and therefore
refuses every update — the safe default.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ._vendor.ed25519 import verify as _ed25519_verify

# The maintainer's minisign public key, pinned in-repo. Empty = no key pinned =
# every update refused (fail closed). Unpinned as of 2.0.0: the key formerly
# here (id f09a0bdc8bf93fb3) had no known private counterpart, so no release
# could ever be signed against it — see docs/RELEASING.md to generate a real
# keypair and pin its public half here.
PINNED_PUBLIC_KEY = ""

_MINISIGN_LEGACY = b"Ed"  # signs the raw file
_MINISIGN_PREHASHED = b"ED"  # signs BLAKE2b-512 of the file (minisign default)
_MANIFEST_FORMAT = 1


class TrustError(Exception):
    """Raised when release material cannot be authenticated. Fail closed."""


@dataclass(frozen=True)
class PublicKey:
    key_id: bytes  # 8 bytes; ties a signature to this exact key
    key: bytes  # 32-byte Ed25519 public key


@dataclass(frozen=True)
class Manifest:
    tag: str
    archive_name: str
    archive_sha256: str
    installer_url: str
    installer_sha256: str


def _b64decode(blob: str) -> bytes:
    try:
        return base64.b64decode(blob.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TrustError("invalid base64 in signing material") from exc


def parse_public_key(text: str) -> PublicKey:
    """Parse a minisign public key (the comment line is optional)."""
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("untrusted comment:")]
    if not lines:
        raise TrustError("empty public key")
    raw = _b64decode(lines[-1])
    if len(raw) != 42:
        raise TrustError("public key has wrong length")
    return PublicKey(key_id=raw[2:10], key=raw[10:42])


def pinned_public_key() -> PublicKey | None:
    """The in-repo pinned key, or None when none is pinned (fail closed)."""
    if not PINNED_PUBLIC_KEY.strip():
        return None
    return parse_public_key(PINNED_PUBLIC_KEY)


@dataclass(frozen=True)
class _Signature:
    algorithm: bytes
    key_id: bytes
    signature: bytes
    trusted_comment: str
    global_signature: bytes


def _parse_signature(text: str) -> _Signature:
    lines = [line for line in text.splitlines() if line.strip() != ""]
    if len(lines) < 4:
        raise TrustError("minisign signature must have 4 lines")
    # lines[0] untrusted comment; lines[1] signature; lines[2] trusted comment;
    # lines[3] global signature over (signature || trusted comment).
    sig_blob = _b64decode(lines[1])
    if len(sig_blob) != 74:
        raise TrustError("signature blob has wrong length")
    prefix = "trusted comment: "
    if not lines[2].startswith(prefix):
        raise TrustError("missing trusted comment")
    global_blob = _b64decode(lines[3])
    if len(global_blob) != 64:
        raise TrustError("global signature has wrong length")
    return _Signature(
        algorithm=sig_blob[0:2],
        key_id=sig_blob[2:10],
        signature=sig_blob[10:74],
        trusted_comment=lines[2][len(prefix) :],
        global_signature=global_blob,
    )


def _signed_payload(message: bytes, algorithm: bytes) -> bytes:
    if algorithm == _MINISIGN_PREHASHED:
        return hashlib.blake2b(message, digest_size=64).digest()
    if algorithm == _MINISIGN_LEGACY:
        return message
    raise TrustError("unsupported minisign algorithm")


def verify_detached(message: bytes, signature_text: str, public_key: PublicKey) -> bool:
    """True iff ``signature_text`` is a minisign signature of ``message`` made
    by ``public_key``. Verifies the trusted-comment global signature too, and
    rejects a signature whose key id is not the pinned key's. Never raises on a
    verification failure — returns False so callers fail closed."""
    try:
        sig = _parse_signature(signature_text)
    except TrustError:
        return False
    if sig.key_id != public_key.key_id:
        return False
    try:
        payload = _signed_payload(message, sig.algorithm)
    except TrustError:
        return False
    if not _ed25519_verify(sig.signature, payload, public_key.key):
        return False
    # The global signature binds the trusted comment to the file signature.
    bound = sig.signature + sig.trusted_comment.encode("utf-8")
    return _ed25519_verify(sig.global_signature, bound, public_key.key)


def parse_manifest(data: bytes) -> Manifest:
    """Parse manifest JSON into a typed record (no authentication here)."""
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise TrustError("manifest is not valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("format") != _MANIFEST_FORMAT:
        raise TrustError("unsupported manifest format")
    source = payload.get("source") or {}
    installer = payload.get("python_installer") or {}
    try:
        return Manifest(
            tag=str(payload["tag"]),
            archive_name=str(source["name"]),
            archive_sha256=str(source["sha256"]).lower(),
            installer_url=str(installer["url"]),
            installer_sha256=str(installer["sha256"]).lower(),
        )
    except (KeyError, TypeError) as exc:
        raise TrustError("manifest is missing required fields") from exc


def verify_manifest(manifest_bytes: bytes, signature_text: str, public_key: PublicKey) -> Manifest:
    """Authenticate ``manifest_bytes`` against ``public_key`` then parse it.

    Raises :class:`TrustError` (fail closed) when the signature does not
    verify or the manifest is malformed."""
    if not verify_detached(manifest_bytes, signature_text, public_key):
        raise TrustError("manifest signature did not verify against the pinned key")
    return parse_manifest(manifest_bytes)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def ensure_archive_matches(manifest: Manifest, archive_path: Path) -> None:
    """Raise :class:`TrustError` unless the archive's SHA-256 is the one the
    signed manifest commits to."""
    actual = sha256_file(archive_path)
    if actual != manifest.archive_sha256:
        raise TrustError(f"archive SHA-256 mismatch: manifest {manifest.archive_sha256}, got {actual}")


__all__ = [
    "Manifest",
    "PublicKey",
    "PINNED_PUBLIC_KEY",
    "TrustError",
    "ensure_archive_matches",
    "parse_manifest",
    "parse_public_key",
    "pinned_public_key",
    "sha256_file",
    "verify_detached",
    "verify_manifest",
]
