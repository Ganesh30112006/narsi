"""Hashing helpers.

Detected values are hashed with a *keyed* HMAC: identifier spaces are small (an Aadhaar number has
~10¹¹ possibilities), so a plain SHA-256 could be reversed by brute force.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable
from typing import BinaryIO

from app.core.enums import PIIType

CHUNK_SIZE = 1024 * 1024


def value_hash(value: str, pii_type: PIIType, key: bytes) -> str:
    return hmac.new(key, f"{pii_type.value}:{value}".encode(), hashlib.sha256).hexdigest()


def sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_chunks(chunks: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


def token_digest(token: str) -> str:
    """Digest used to store refresh tokens (tokens are 256-bit random, so an unkeyed hash is sufficient)."""
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())
