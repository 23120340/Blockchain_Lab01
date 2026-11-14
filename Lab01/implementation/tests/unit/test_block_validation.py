"""Kiểm tra block: parent, proposer, chữ ký, transaction, state hash, header/body."""
from src.models import NIL, PREVOTE, block_hash
from tests.helpers import Env


def reasons(env):
    return [e["reason"] for e in env.events("reject")]


def test_valid_block_is_accepted_and_prevoted():
    env = Env()
    header, txs = env.block("v1", [env.tx("alice", 0, "alice/message", "hello")])
    hash_ = env.give_block("v1", 0, header, txs)
    assert [e["hash"] for e in env.events("header_accept")] == [hash_]
    assert [e["hash"] for e in env.events("block_valid")] == [hash_]
    assert [v["block_hash"] for v in env.my_votes(PREVOTE, 0)] == [hash_]
    assert env.node.state.data == {}          # chưa finalize thì state chính chưa đổi


def test_header_must_be_accepted_before_body_is_requested_or_sent():
    env = Env()
    header, txs = env.block("v1")
    env.deliver("v1", "PROPOSAL", env.proposal("v1", 0, header))
    requests = env.net.of("BODY_REQUEST")
    assert [(m["dst"], m["payload"]["block_hash"]) for m in requests] == [("v1", block_hash(header))]
    assert env.my_votes() == []               # chưa có body thì chưa bỏ phiếu


def test_proposer_sends_header_first_and_body_only_on_request():
    env = Env(node="v1")                      # v1 là proposer của (height 1, round 0)
    proposals = env.net.of("PROPOSAL")
    assert sorted(m["dst"] for m in proposals) == ["v0", "v2", "v3"]
    assert env.net.of("BODY") == []
    hash_ = proposals[0]["payload"]["block_hash"]
    env.deliver("v2", "BODY_REQUEST", {"height": 1, "block_hash": hash_})
    assert [m["dst"] for m in env.net.of("BODY")] == ["v2"]
    env.deliver("v3", "BODY_REQUEST", {"height": 1, "block_hash": "00" * 32})
    assert [m["dst"] for m in env.net.of("BODY")] == ["v2"]      # block lạ: không gửi gì


def test_unsolicited_body_is_rejected():
    env = Env()
    header, txs = env.block("v1")
    env.deliver("v1", "BODY", {"height": 1, "block_hash": block_hash(header), "txs": txs})
    assert reasons(env) == ["body_without_accepted_header"]
    assert env.my_votes() == []


def test_bad_parent_is_rejected():
    env = Env()
    header, _ = env.block("v1", parent="00" * 32)
    env.deliver("v1", "PROPOSAL", env.proposal("v1", 0, header))
    assert reasons(env) == ["bad_parent"]
    assert env.net.of("BODY_REQUEST") == []


def test_wrong_proposer_is_rejected():
    env = Env()
    header, _ = env.block("v2")
    env.deliver("v2", "PROPOSAL", env.proposal("v2", 0, header))    # round 0 thuộc về v1
    assert reasons(env) == ["wrong_proposer"]
    # v1 đúng lượt nhưng mang header do v3 ký làm block mới.
    header3, _ = env.block("v3")
    env.deliver("v1", "PROPOSAL", env.proposal("v1", 0, header3))
    assert reasons(env) == ["wrong_proposer", "wrong_proposer"]


def test_bad_header_or_proposal_signature_is_rejected():
    env = Env()
    header, _ = env.block("v1")
    broken = dict(header, sig="00" * 64)
    env.deliver("v1", "PROPOSAL", env.proposal("v1", 0, broken))
    proposal = env.proposal("v1", 0, header)
    env.deliver("v1", "PROPOSAL", dict(proposal, sig="00" * 64))
    env.deliver("v1", "PROPOSAL", dict(proposal, round=1))           # sửa round sau khi ký
    assert reasons(env) == ["bad_signature", "bad_signature", "bad_signature"]
    assert env.events("header_accept") == []


def test_wrong_state_hash_makes_block_invalid_and_prevote_nil():
    env = Env()
    before = env.node.state.hash()
    header, txs = env.block("v1", [env.tx("alice", 0, "alice/message", "x")],
                            state_hash="ff" * 32)
    env.give_block("v1", 0, header, txs)
    assert [e["reason"] for e in env.events("block_invalid")] == ["state_hash_mismatch"]
    assert [v["block_hash"] for v in env.my_votes(PREVOTE, 0)] == [NIL]
    assert env.node.state.hash() == before and env.node.ledger == []


def test_block_with_invalid_transaction_is_invalid():
    for txs_of, expected in [
        (lambda e: [e.tx("alice", 0, "bob/message", "stolen")], "invalid_tx:not_owner"),
        (lambda e: [e.tx("alice", 0, "alice/m", "x", signer="mallory")], "invalid_tx:bad_signature"),
        (lambda e: [e.tx("alice", 0, "alice/m", "x")] * 2, "invalid_tx:replayed_nonce"),
        (lambda e: [e.tx("alice", 3, "alice/m", "x")], "invalid_tx:future_nonce"),
    ]:
        env = Env()
        header, txs = env.block("v1", txs_of(env), state_hash="ab" * 32)
        env.give_block("v1", 0, header, txs)
        assert [e["reason"] for e in env.events("block_invalid")] == [expected]
        assert [v["block_hash"] for v in env.my_votes(PREVOTE, 0)] == [NIL]
        assert env.node.state.data == {}


def test_body_that_does_not_match_header_is_rejected_then_real_body_accepted():
    env = Env()
    real = [env.tx("alice", 0, "alice/message", "real")]
    header, txs = env.block("v1", real)
    hash_ = block_hash(header)
    env.deliver("v1", "PROPOSAL", env.proposal("v1", 0, header))
    fake = [env.tx("alice", 0, "alice/message", "fake")]
    env.deliver("v2", "BODY", {"height": 1, "block_hash": hash_, "txs": fake})
    assert reasons(env) == ["tx_root_mismatch"] and env.my_votes() == []
    env.deliver("v1", "BODY", {"height": 1, "block_hash": hash_, "txs": txs})
    assert [v["block_hash"] for v in env.my_votes(PREVOTE, 0)] == [hash_]


def test_second_conflicting_proposal_in_same_round_is_not_adopted():
    env = Env()
    h1, t1 = env.block("v1", [env.tx("alice", 0, "alice/m", "1")])
    h2, t2 = env.block("v1", [env.tx("alice", 0, "alice/m", "2")])
    first = env.give_block("v1", 0, h1, t1)
    env.deliver("v1", "PROPOSAL", env.proposal("v1", 0, h2))
    assert len(env.events("equivocation")) == 1
    assert [v["block_hash"] for v in env.my_votes(PREVOTE, 0)] == [first]
    assert block_hash(h2) not in env.node.headers
