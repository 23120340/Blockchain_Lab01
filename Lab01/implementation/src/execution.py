"""Lớp thực thi: state key-value + nonce, áp dụng transaction một cách xác định.

Quy tắc sở hữu: sender chỉ được ghi khóa bắt đầu bằng "<sender>/".
Chống replay: nonce của mỗi sender nằm TRONG state (và trong state hash), mỗi
transaction phải mang đúng nonce kế tiếp nên chỉ áp dụng được một lần.
"""
from .crypto import hash_obj
from .models import TX_FIELDS, TX_SPEC, check_signed, has_shape, tx_domain


class InvalidTx(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class State:
    def __init__(self, data=None, nonces=None):
        self.data = dict(data or {})
        self.nonces = dict(nonces or {})

    def copy(self):
        return State(self.data, self.nonces)

    def hash(self) -> str:
        return hash_obj({"data": self.data, "nonces": self.nonces})


def check_tx_static(tx, accounts, chain_id):
    """Kiểm tra không phụ thuộc state: dạng, chain, domain, chữ ký, quyền sở hữu."""
    if not has_shape(tx, TX_SPEC) or tx["nonce"] < 0:
        return "malformed"
    if tx["chain_id"] != chain_id:
        return "wrong_chain"
    if tx["domain"] != tx_domain(chain_id):
        return "wrong_domain"
    pub = accounts.get(tx["sender"])
    if pub is None:
        return "unknown_sender"
    reason = check_signed(tx, TX_FIELDS, tx_domain(chain_id), chain_id, pub)
    if reason:
        return reason
    if not tx["key"].startswith(tx["sender"] + "/"):
        return "not_owner"
    return None


def apply_tx(state: State, tx, accounts, chain_id):
    """Sửa `state` tại chỗ; ném InvalidTx nếu transaction không hợp lệ."""
    reason = check_tx_static(tx, accounts, chain_id)
    if reason:
        raise InvalidTx(reason)
    expected = state.nonces.get(tx["sender"], 0)
    if tx["nonce"] != expected:
        raise InvalidTx("replayed_nonce" if tx["nonce"] < expected else "future_nonce")
    state.data[tx["key"]] = tx["value"]
    state.nonces[tx["sender"]] = expected + 1


def execute_block(state: State, txs, accounts, chain_id) -> State:
    """Thực thi trên BẢN SAO; state đầu vào không bao giờ bị sửa."""
    candidate = state.copy()
    for tx in txs:
        apply_tx(candidate, tx, accounts, chain_id)
    return candidate
