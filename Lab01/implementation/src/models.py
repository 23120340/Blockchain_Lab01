"""Cấu trúc dữ liệu được ký: transaction, block header, vote, proposal.

Mọi thông điệp là dict thuần để mã hóa canonical được. Mỗi thông điệp mang
`chain_id`, `domain` và `sig`; phần được ký là mọi trường định danh còn lại.
"""
from .crypto import hash_obj, sign, verify

NIL = "NIL"
PREVOTE = "PREVOTE"
PRECOMMIT = "PRECOMMIT"
PHASES = (PREVOTE, PRECOMMIT)


def tx_domain(chain_id):
    return f"TX:{chain_id}"


def header_domain(chain_id):
    return f"HEADER:{chain_id}"


def vote_domain(chain_id):
    return f"VOTE:{chain_id}"


def proposal_domain(chain_id):
    return f"PROPOSAL:{chain_id}"


TX_FIELDS = ("chain_id", "sender", "nonce", "key", "value")
HEADER_FIELDS = ("chain_id", "height", "parent_hash", "tx_root", "state_hash", "proposer")
VOTE_FIELDS = ("chain_id", "height", "round", "phase", "block_hash", "validator")
PROPOSAL_FIELDS = ("chain_id", "height", "round", "pol_round", "block_hash", "proposer")

_SIG = {"domain": str, "sig": str}
TX_SPEC = {"chain_id": str, "sender": str, "nonce": int, "key": str, "value": str, **_SIG}
HEADER_SPEC = {"chain_id": str, "height": int, "parent_hash": str, "tx_root": str,
               "state_hash": str, "proposer": str, **_SIG}
VOTE_SPEC = {"chain_id": str, "height": int, "round": int, "phase": str,
             "block_hash": str, "validator": str, **_SIG}
PROPOSAL_SPEC = {"chain_id": str, "height": int, "round": int, "pol_round": int,
                 "block_hash": str, "proposer": str, "header": dict, "pol_votes": list, **_SIG}


def has_shape(obj, spec) -> bool:
    """Kiểm tra kiểu chặt (bool không được coi là int)."""
    return isinstance(obj, dict) and all(
        key in obj and type(obj[key]) is kind for key, kind in spec.items()
    )


def payload(obj, fields):
    return {name: obj[name] for name in fields}


def _signed(keypair, domain, body):
    out = dict(body)
    out["domain"] = domain
    out["sig"] = sign(keypair, domain, body)
    return out


def check_signed(obj, fields, expected_domain, chain_id, pub_hex):
    """Trả về None nếu hợp lệ, ngược lại là lý do từ chối."""
    if obj["chain_id"] != chain_id:
        return "wrong_chain"
    if obj["domain"] != expected_domain:
        return "wrong_domain"
    if pub_hex is None:
        return "unknown_signer"
    if not verify(pub_hex, expected_domain, payload(obj, fields), obj["sig"]):
        return "bad_signature"
    return None


# ---- transaction ---------------------------------------------------------

def make_tx(keypair, chain_id, sender, nonce, key, value):
    body = {"chain_id": chain_id, "sender": sender, "nonce": nonce, "key": key, "value": value}
    return _signed(keypair, tx_domain(chain_id), body)


def tx_id(tx) -> str:
    return hash_obj(tx)


def tx_root(txs) -> str:
    """Cam kết danh sách transaction CÓ THỨ TỰ (gồm cả chữ ký)."""
    return hash_obj([tx_id(tx) for tx in txs])


# ---- block header --------------------------------------------------------

def make_header(keypair, chain_id, height, parent_hash, txs, state_hash, proposer):
    body = {"chain_id": chain_id, "height": height, "parent_hash": parent_hash,
            "tx_root": tx_root(txs), "state_hash": state_hash, "proposer": proposer}
    return _signed(keypair, header_domain(chain_id), body)


def block_hash(header) -> str:
    """Định danh block: không chứa round nên ổn định khi được đề xuất lại."""
    return hash_obj(payload(header, HEADER_FIELDS))


# ---- vote ----------------------------------------------------------------

def make_vote(keypair, chain_id, height, round_, phase, block_hash_, validator):
    body = {"chain_id": chain_id, "height": height, "round": round_, "phase": phase,
            "block_hash": block_hash_, "validator": validator}
    return _signed(keypair, vote_domain(chain_id), body)


def check_vote(vote, chain_id, validator_pubs):
    if not has_shape(vote, VOTE_SPEC):
        return "malformed"
    if vote["phase"] not in PHASES or vote["round"] < 0 or vote["height"] < 1:
        return "malformed"
    if vote["chain_id"] != chain_id:
        return "wrong_chain"
    if vote["domain"] != vote_domain(chain_id):
        return "wrong_domain"
    pub = validator_pubs.get(vote["validator"])
    if pub is None:
        return "unknown_validator"
    return check_signed(vote, VOTE_FIELDS, vote_domain(chain_id), chain_id, pub)


def check_certificate(votes, phase, height, round_, block_hash_, chain_id,
                      validator_pubs, quorum):
    """Bằng chứng quorum tự đứng được: >= quorum validator KHÁC NHAU cùng ký
    đúng (height, round, phase, block_hash). Mỗi validator chỉ tính một lần."""
    if not isinstance(votes, list):
        return False
    seen = set()
    for vote in votes:
        if check_vote(vote, chain_id, validator_pubs) is not None:
            return False
        if (vote["height"], vote["round"], vote["phase"], vote["block_hash"]) != (
                height, round_, phase, block_hash_):
            return False
        if vote["validator"] in seen:
            return False
        seen.add(vote["validator"])
    return len(seen) >= quorum


# ---- proposal ------------------------------------------------------------

def make_proposal(keypair, chain_id, height, round_, pol_round, header, proposer, pol_votes):
    body = {"chain_id": chain_id, "height": height, "round": round_, "pol_round": pol_round,
            "block_hash": block_hash(header), "proposer": proposer}
    out = _signed(keypair, proposal_domain(chain_id), body)
    out["header"] = header
    out["pol_votes"] = pol_votes
    return out


def genesis_hash(genesis) -> str:
    return hash_obj({"chain_id": genesis["chain_id"], "validators": genesis["validators"],
                     "accounts": genesis["accounts"]})
