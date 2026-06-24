"""Known-answer tests pinning the vendored Ed25519 verifier (v2.0 H7 / PR-18).

The updater's whole trust chain rests on this verify path, so it is anchored
to RFC 8032 section 7.1 external test vectors (not just self-consistency): a
valid signature must verify, and any single-byte change to the signature,
message, or public key — or any malformed length — must be rejected.
"""

from __future__ import annotations

import pytest

from silentfrog._vendor.ed25519 import verify  # type: ignore[reportMissingImports]

# RFC 8032 section 7.1, TEST 1 (empty message) and TEST 2 (one-byte message).
# The "secret key" column is the seed and is not needed by the verify path.
RFC8032_VECTORS = [
    (
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
]


@pytest.mark.parametrize("pk_hex, msg_hex, sig_hex", RFC8032_VECTORS)
def test_rfc8032_vectors_verify(pk_hex: str, msg_hex: str, sig_hex: str) -> None:
    pk = bytes.fromhex(pk_hex)
    msg = bytes.fromhex(msg_hex)
    sig = bytes.fromhex(sig_hex)
    assert verify(sig, msg, pk) is True


@pytest.mark.parametrize("pk_hex, msg_hex, sig_hex", RFC8032_VECTORS)
def test_rfc8032_single_byte_tampering_is_rejected(pk_hex: str, msg_hex: str, sig_hex: str) -> None:
    pk = bytes.fromhex(pk_hex)
    msg = bytes.fromhex(msg_hex)
    sig = bytes.fromhex(sig_hex)
    assert verify(bytes([sig[0] ^ 0x01]) + sig[1:], msg, pk) is False  # flipped signature
    assert verify(sig, msg + b"\x00", pk) is False  # appended message byte
    assert verify(sig, msg, bytes([pk[0] ^ 0x01]) + pk[1:]) is False  # flipped public key


def test_malformed_inputs_fail_closed() -> None:
    pk = bytes.fromhex(RFC8032_VECTORS[0][0])
    sig = bytes.fromhex(RFC8032_VECTORS[0][2])
    # Wrong lengths and wrong types return False rather than raising, so a
    # caller treats any malformed signature/key as "reject".
    assert verify(b"", b"", pk) is False
    assert verify(sig, b"", b"too-short") is False
    assert verify(sig[:-1], b"", pk) is False
