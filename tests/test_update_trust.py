"""Trust tests for the signed-release updater (v2.0 H7 / PR-18).

minisign tooling is not available in CI, so the fixtures here generate
genuine minisign-format material with a self-contained signer
(minisign_fixture) that does NOT share code with the production verifier —
it has its own Ed25519 implementation, so these are two independent
implementations of the documented minisign layout that cross-check each
other. The production verify path is additionally pinned to RFC 8032 in
test_vendor_ed25519.py. All keys here are throwaway test keys.

The suite is the adversarial corpus the acceptance criteria call for: a good
signature is accepted, and a bad signature, tampered manifest, hash mismatch,
wrong key id, wrong key, or malformed envelope is each refused — fail closed.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from minisign_fixture import OTHER_SEED as _OTHER_SEED
from minisign_fixture import TEST_KEY_ID as _KEY_ID
from minisign_fixture import manifest_bytes
from minisign_fixture import public_key_text as _public_key_text
from minisign_fixture import signature_text as _signature_text

from silentfrog import update_trust
from silentfrog.update_trust import (
    TrustError,
    ensure_archive_matches,
    parse_public_key,
    pinned_public_key,
    verify_detached,
    verify_manifest,
)

_MANIFEST_JSON = manifest_bytes("silentfrog-2.0.0.zip", "a" * 64)


@pytest.fixture
def public_key():
    return parse_public_key(_public_key_text())


# --- signature verification (prehashed + legacy) -----------------------------


@pytest.mark.parametrize("prehashed", [True, False])
def test_good_signature_verifies(public_key, prehashed: bool) -> None:
    message = b"release manifest body"
    assert verify_detached(message, _signature_text(message, prehashed=prehashed), public_key) is True


def test_tampered_message_is_rejected(public_key) -> None:
    sig_text = _signature_text(b"original body")
    assert verify_detached(b"original bodX", sig_text, public_key) is False


def test_flipped_signature_byte_is_rejected(public_key) -> None:
    message = b"release manifest body"
    sig_text = _signature_text(message)
    lines = sig_text.splitlines()
    blob = bytearray(base64.b64decode(lines[1]))
    blob[20] ^= 0x01  # flip a byte inside the 64-byte signature
    lines[1] = base64.b64encode(bytes(blob)).decode()
    assert verify_detached(message, "\n".join(lines) + "\n", public_key) is False


def test_wrong_key_id_is_rejected(public_key) -> None:
    # A signature made under a different key id must not verify against the
    # pinned key even if the math would otherwise check out.
    message = b"release manifest body"
    sig_text = _signature_text(message, key_id=bytes(8))
    assert verify_detached(message, sig_text, public_key) is False


def test_signature_from_a_different_key_is_rejected(public_key) -> None:
    message = b"release manifest body"
    # Same key id (so the id check passes) but signed by another private key.
    sig_text = _signature_text(message, seed=_OTHER_SEED)
    assert verify_detached(message, sig_text, public_key) is False


def test_tampered_trusted_comment_breaks_global_signature(public_key) -> None:
    message = b"release manifest body"
    sig_text = _signature_text(message)
    lines = sig_text.splitlines()
    lines[2] = "trusted comment: attacker rewrote this"
    assert verify_detached(message, "\n".join(lines) + "\n", public_key) is False


@pytest.mark.parametrize("text", ["", "untrusted comment: x\nonly-two\nlines", "garbage"])
def test_malformed_signature_envelope_is_rejected(public_key, text: str) -> None:
    assert verify_detached(b"body", text, public_key) is False


# --- manifest authentication + archive hash binding --------------------------


def test_verify_manifest_returns_typed_record(public_key) -> None:
    manifest = verify_manifest(_MANIFEST_JSON, _signature_text(_MANIFEST_JSON), public_key)
    assert manifest.tag == "v2.0.0"
    assert manifest.archive_name == "silentfrog-2.0.0.zip"
    assert manifest.archive_sha256 == "a" * 64


def test_verify_manifest_refuses_tampered_body(public_key) -> None:
    sig_text = _signature_text(_MANIFEST_JSON)
    tampered = _MANIFEST_JSON.replace(b"v2.0.0", b"v9.9.9")
    with pytest.raises(TrustError):
        verify_manifest(tampered, sig_text, public_key)


def test_verify_manifest_rejects_unsupported_format(public_key) -> None:
    body = b'{"format": 2, "tag": "v2", "source": {"name": "x", "sha256": "x"}}'
    with pytest.raises(TrustError):
        verify_manifest(body, _signature_text(body), public_key)


def test_ensure_archive_matches(public_key, tmp_path) -> None:
    archive = tmp_path / "silentfrog.zip"
    archive.write_bytes(b"the real release archive bytes")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    body = (
        b'{"format": 1, "tag": "v2.0.0", "source": {"name": "silentfrog.zip", "sha256": "'
        + digest.encode()
        + b'"}, "python_installer": {"url": "https://python.org/x.exe", "sha256": "'
        + b"c" * 64
        + b'"}}'
    )
    manifest = verify_manifest(body, _signature_text(body), public_key)
    ensure_archive_matches(manifest, archive)  # exact hash: no raise
    archive.write_bytes(b"a malicious archive with the same name")
    with pytest.raises(TrustError):
        ensure_archive_matches(manifest, archive)


# --- pinned-key fail-closed default ------------------------------------------


def test_no_pinned_key_means_fail_closed(monkeypatch) -> None:
    # Shipped state: no key pinned -> pinned_public_key() is None, so the
    # updater has nothing to verify against and must refuse every update.
    monkeypatch.setattr(update_trust, "PINNED_PUBLIC_KEY", "")
    assert pinned_public_key() is None


def test_pinned_key_parses_when_present(monkeypatch) -> None:
    monkeypatch.setattr(update_trust, "PINNED_PUBLIC_KEY", _public_key_text())
    pinned = pinned_public_key()
    assert pinned is not None
    assert pinned.key_id == _KEY_ID


def test_shipped_pinned_key_is_a_wellformed_minisign_key() -> None:
    # Guard the real in-repo trust anchor: if a key is pinned it must be a valid
    # 42-byte minisign Ed25519 public key, so a corrupted paste can never ship.
    if not update_trust.PINNED_PUBLIC_KEY.strip():
        pytest.skip("no key pinned in this build")
    pinned = pinned_public_key()
    assert pinned is not None
    assert len(pinned.key_id) == 8
    assert len(pinned.key) == 32


# A real signature produced by the genuine `minisign` tool over the probe string
# "silentfrog-pr18-keycheck" (prehashed/"ED" mode). Public keys and signatures
# are public data, so both are safe to commit. This pair is the only fixture
# made by the real tool rather than our own test signer, so it is what proves
# the vendored verifier interoperates with actual minisign output.
#
# The key below was the repo's trust anchor until 2.0.0 unpinned it (no private
# counterpart was ever held). It is kept here purely as a TEST VECTOR — it is
# deliberately NOT read from PINNED_PUBLIC_KEY, so the interop check keeps
# running whether or not a key is pinned.
_REAL_MINISIGN_PUBLIC_KEY = "RWTwmgvci/k/s0YtnM0nBg/MOCf7aMn9aHe3y1MprEeMnghlphnMCvUn"
_REAL_MINISIGN_KEY_ID = "f09a0bdc8bf93fb3"
_REAL_MINISIGN_PROBE = b"silentfrog-pr18-keycheck"
_REAL_MINISIGN_SIG = (
    "untrusted comment: signature from minisign secret key\n"
    "RUTwmgvci/k/s2HrSuVaJ9MHjlR+M19FpQ7M+EXkEtgxY0x4SYkxI2CfrSvHrzyG3tejd0DAzvuwXKP7WLF8jkFX1sncYxb1tQ0=\n"
    "trusted comment: timestamp:1782309004\tfile:probe.txt\thashed\n"
    "hcXI3RfyCVhnlLgq9TmY+qcZUUO3j2GhpsL/2eQyZ6ltaXtQQnRrAUrniyXn7r5mKF1TB3xZjrcR1cgqkQL5CA==\n"
)


def test_vendored_verifier_interoperates_with_real_minisign_output() -> None:
    key = parse_public_key(_REAL_MINISIGN_PUBLIC_KEY)
    assert key.key_id.hex() == _REAL_MINISIGN_KEY_ID
    # Authentic minisign output must verify; a tampered byte must not.
    assert verify_detached(_REAL_MINISIGN_PROBE, _REAL_MINISIGN_SIG, key) is True
    assert verify_detached(_REAL_MINISIGN_PROBE + b"!", _REAL_MINISIGN_SIG, key) is False
