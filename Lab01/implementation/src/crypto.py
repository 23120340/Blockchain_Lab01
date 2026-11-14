"""Ed25519 + SHA-256 với domain separation.

Bytes được ký = domain (UTF-8) + 0x00 + canonical(payload). Domain chứa chain_id
(ví dụ "VOTE:lab01-chain") nên chữ ký của loại thông điệp này không dùng lại được
cho loại khác hoặc chain khác.
"""
import functools
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .encoding import canonical


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_obj(obj) -> str:
    return sha256_hex(canonical(obj))


class KeyPair:
    def __init__(self, seed: bytes):
        self._priv = Ed25519PrivateKey.from_private_bytes(seed)
        self.pub_hex = self._priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()

    def sign_bytes(self, data: bytes) -> str:
        return self._priv.sign(data).hex()


def fixture_keypair(chain_id: str, name: str) -> KeyPair:
    """Khóa CỐ ĐỊNH cho kiểm thử, suy ra từ tên. Không dùng cho hệ thống thật."""
    seed = hashlib.sha256(f"lab01-fixture|{chain_id}|{name}".encode("utf-8")).digest()
    return KeyPair(seed)


def signing_bytes(domain: str, payload) -> bytes:
    return domain.encode("utf-8") + b"\x00" + canonical(payload)


def sign(keypair: KeyPair, domain: str, payload) -> str:
    return keypair.sign_bytes(signing_bytes(domain, payload))


@functools.lru_cache(maxsize=200_000)
def _verify_raw(pub_hex: str, data: bytes, sig_hex: str) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        pub.verify(bytes.fromhex(sig_hex), data)
        return True
    except (InvalidSignature, ValueError):
        return False


def verify(pub_hex: str, domain: str, payload, sig_hex: str) -> bool:
    """Hàm thuần: cùng đầu vào luôn cho cùng kết quả (cache chỉ để nhanh hơn)."""
    return _verify_raw(pub_hex, signing_bytes(domain, payload), sig_hex)
