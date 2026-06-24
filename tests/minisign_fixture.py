"""Throwaway minisign-format signer for updater tests (v2.0 H7 / PR-18).

minisign tooling is not available in CI, so this builds genuine minisign
public-key and signature files. The Ed25519 signer below is **self-contained**
— it deliberately does NOT import ``silentfrog._vendor.ed25519`` (the module
the production verifier uses), so a latent bug in the vendored primitives
cannot be mirrored here and silently make the verification tests pass. The
signer and the production parser/verifier are therefore genuinely separate
implementations of the documented minisign byte layout and cross-check each
other; the verify side is additionally pinned to RFC 8032 vectors in
test_vendor_ed25519.py. Test keys only — never used in production.
"""

from __future__ import annotations

import base64
import hashlib

# --- self-contained Ed25519 sign (RFC 8032), independent of the vendored
# --- module under test. Slow but only used to mint test fixtures.
_B_BITS = 256
_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _Q - 2, _Q)


_D = -121665 * _inv(121666) % _Q
_ROOT = pow(2, (_Q - 1) // 4, _Q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = (x * _ROOT) % _Q
    return _Q - x if x % 2 != 0 else x


_BY = 4 * _inv(5)
_BASE = (_xrecover(_BY) % _Q, _BY % _Q)


def _add(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p
    x2, y2 = q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _D * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _D * x1 * x2 * y1 * y2)
    return (x3 % _Q, y3 % _Q)


def _mul(p: tuple[int, int], e: int) -> tuple[int, int]:
    result = (0, 1)
    while e > 0:
        if e & 1:
            result = _add(result, p)
        p = _add(p, p)
        e >>= 1
    return result


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def _encodepoint(p: tuple[int, int]) -> bytes:
    x, y = p
    bits = [(y >> i) & 1 for i in range(_B_BITS - 1)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(_B_BITS // 8))


def _encodeint(y: int) -> bytes:
    bits = [(y >> i) & 1 for i in range(_B_BITS)]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(_B_BITS // 8))


def _hint(m: bytes) -> int:
    h = hashlib.sha512(m).digest()
    return sum(2**i * _bit(h, i) for i in range(2 * _B_BITS))


TEST_SEED = bytes(range(32))
OTHER_SEED = bytes(range(100, 132))
TEST_KEY_ID = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0x11, 0x22, 0x33, 0x44])


def ed25519_sign(message: bytes, seed: bytes) -> tuple[bytes, bytes]:
    """Return (64-byte signature, 32-byte public key) for ``message``."""
    h = hashlib.sha512(seed).digest()
    a = 2 ** (_B_BITS - 2) + sum(2**i * _bit(h, i) for i in range(3, _B_BITS - 2))
    pub = _encodepoint(_mul(_BASE, a))
    r = _hint(h[_B_BITS // 8 : _B_BITS // 4] + message)
    big_r = _encodepoint(_mul(_BASE, r))
    s = (r + _hint(big_r + pub + message) * a) % _L
    return big_r + _encodeint(s), pub


def public_key_text(seed: bytes = TEST_SEED, key_id: bytes = TEST_KEY_ID) -> str:
    _sig, pub = ed25519_sign(b"", seed)
    blob = base64.b64encode(b"Ed" + key_id + pub).decode()
    return f"untrusted comment: minisign public key TEST\n{blob}\n"


def signature_text(
    message: bytes,
    *,
    seed: bytes = TEST_SEED,
    key_id: bytes = TEST_KEY_ID,
    prehashed: bool = True,
    trusted_comment: str = "timestamp:0\tfile:manifest.json",
) -> str:
    algorithm = b"ED" if prehashed else b"Ed"
    payload = hashlib.blake2b(message, digest_size=64).digest() if prehashed else message
    sig, _pub = ed25519_sign(payload, seed)
    line2 = base64.b64encode(algorithm + key_id + sig).decode()
    global_sig, _pub = ed25519_sign(sig + trusted_comment.encode("utf-8"), seed)
    line4 = base64.b64encode(global_sig).decode()
    return f"untrusted comment: TEST\n{line2}\ntrusted comment: {trusted_comment}\n{line4}\n"


def manifest_bytes(archive_name: str, archive_sha256: str, *, tag: str = "v2.0.0") -> bytes:
    import json

    return json.dumps(
        {
            "format": 1,
            "tag": tag,
            "source": {"name": archive_name, "sha256": archive_sha256},
            "python_installer": {"url": "https://python.org/x.exe", "sha256": "c" * 64},
        }
    ).encode("utf-8")
