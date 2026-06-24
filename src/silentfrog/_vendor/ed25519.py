"""Pure-Python Ed25519 verification (RFC 8032 reference).

Vendored so Silentfrog's updater can verify minisign release signatures with
zero third-party dependencies and no external binary (v2.0 H7 / PR-18). This
is the public-domain Bernstein/RFC 8032 reference implementation; the only
adaptations are using Python's builtin ``pow`` for modular exponentiation and
an iterative double-and-add ``scalarmult`` so deep recursion cannot exhaust
the stack. Curve constants and the verification equation are unchanged.

Correctness is pinned by the RFC 8032 known-answer vectors in
``tests/test_vendor_ed25519.py``. ``verify`` is the only public entry point;
it is constant-shape (no early-out on content) and returns a bool rather than
raising, so callers fail closed on any malformed input.
"""

import hashlib

b = 256
q = 2 ** 255 - 19
ell = 2 ** 252 + 27742317777372353535851937790883648493


def _H(m):
    return hashlib.sha512(m).digest()


def _inv(x):
    return pow(x, q - 2, q)


d = -121665 * _inv(121666) % q
_I = pow(2, (q - 1) // 4, q)


def _xrecover(y):
    xx = (y * y - 1) * _inv(d * y * y + 1)
    x = pow(xx, (q + 3) // 8, q)
    if (x * x - xx) % q != 0:
        x = (x * _I) % q
    if x % 2 != 0:
        x = q - x
    return x


_By = 4 * _inv(5)
_Bx = _xrecover(_By)
B = [_Bx % q, _By % q]


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - d * x1 * x2 * y1 * y2)
    return [x3 % q, y3 % q]


def _scalarmult(P, e):
    # Iterative double-and-add (the reference's recursive form rewritten so a
    # 512-bit scalar cannot blow the Python recursion limit).
    result = [0, 1]
    addend = P
    while e > 0:
        if e & 1:
            result = _edwards(result, addend)
        addend = _edwards(addend, addend)
        e >>= 1
    return result


def _bit(h, i):
    return (h[i // 8] >> (i % 8)) & 1


def _encodepoint(P):
    x, y = P
    bits = [(y >> i) & 1 for i in range(b - 1)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(b // 8))


def _Hint(m):
    h = _H(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * b))


def _isoncurve(P):
    x, y = P
    return (-x * x + y * y - 1 - d * x * x * y * y) % q == 0


def _decodeint(s):
    return sum(2 ** i * _bit(s, i) for i in range(0, b))


def _decodepoint(s):
    y = sum(2 ** i * _bit(s, i) for i in range(0, b - 1))
    x = _xrecover(y)
    if x & 1 != _bit(s, b - 1):
        x = q - x
    P = [x, y]
    if not _isoncurve(P):
        raise ValueError("decoding point that is not on curve")
    return P


def _checkvalid(s, m, pk):
    if len(s) != b // 4:
        raise ValueError("signature length is wrong")
    if len(pk) != b // 8:
        raise ValueError("public-key length is wrong")
    R = _decodepoint(s[0:b // 8])
    A = _decodepoint(pk)
    S = _decodeint(s[b // 8:b // 4])
    h = _Hint(_encodepoint(R) + pk + m)
    return _scalarmult(B, S) == _edwards(R, _scalarmult(A, h))


def verify(signature: bytes, message: bytes, public_key: bytes) -> bool:
    """Return True iff ``signature`` is a valid Ed25519 signature of
    ``message`` under ``public_key``. Returns False on any malformed input;
    never raises, so callers can treat a False as "reject and fail closed"."""
    try:
        return _checkvalid(signature, message, public_key)
    except (ValueError, IndexError, TypeError):
        return False
