"""Luật cập nhật state: sở hữu, chữ ký, chống replay, tính xác định."""
import pytest

from src.crypto import fixture_keypair, sign
from src.execution import InvalidTx, State, apply_tx, check_tx_static, execute_block
from src.models import TX_FIELDS, make_tx, payload, vote_domain

CHAIN = "unit-chain"
ALICE, BOB = fixture_keypair(CHAIN, "alice"), fixture_keypair(CHAIN, "bob")
ACCOUNTS = {"alice": ALICE.pub_hex, "bob": BOB.pub_hex}


def tx(kp, sender, nonce, key, value):
    return make_tx(kp, CHAIN, sender, nonce, key, value)


def reason_of(state, t):
    with pytest.raises(InvalidTx) as info:
        apply_tx(state, t, ACCOUNTS, CHAIN)
    return info.value.reason


def test_example_from_assignment():
    state = State()
    apply_tx(state, tx(ALICE, "alice", 0, "alice/message", "hello"), ACCOUNTS, CHAIN)
    apply_tx(state, tx(BOB, "bob", 0, "bob/message", "hi"), ACCOUNTS, CHAIN)
    assert state.data == {"alice/message": "hello", "bob/message": "hi"}
    assert state.nonces == {"alice": 1, "bob": 1}


def test_sender_can_only_write_own_keys():
    state = State()
    assert reason_of(state, tx(ALICE, "alice", 0, "bob/message", "x")) == "not_owner"
    assert reason_of(state, tx(ALICE, "alice", 0, "alicex/message", "x")) == "not_owner"
    assert state.data == {} and state.nonces == {}


def test_signature_must_match_sender():
    state = State()
    forged = make_tx(BOB, CHAIN, "alice", 0, "alice/message", "x")   # Bob ký thay Alice
    assert reason_of(state, forged) == "bad_signature"
    good = tx(ALICE, "alice", 0, "alice/message", "x")
    assert reason_of(state, {**good, "value": "y"}) == "bad_signature"
    assert check_tx_static({**good, "sender": "nobody"}, ACCOUNTS, CHAIN) == "unknown_sender"
    assert check_tx_static({"sender": "alice"}, ACCOUNTS, CHAIN) == "malformed"


def test_wrong_domain_and_wrong_chain_are_rejected():
    good = tx(ALICE, "alice", 0, "alice/message", "x")
    relabeled = {**good, "domain": vote_domain(CHAIN),
                 "sig": sign(ALICE, vote_domain(CHAIN), payload(good, TX_FIELDS))}
    assert check_tx_static(relabeled, ACCOUNTS, CHAIN) == "wrong_domain"
    cross = {**good, "sig": relabeled["sig"]}
    assert check_tx_static(cross, ACCOUNTS, CHAIN) == "bad_signature"
    other = make_tx(ALICE, "other-chain", "alice", 0, "alice/message", "x")
    assert check_tx_static(other, ACCOUNTS, CHAIN) == "wrong_chain"


def test_transaction_applies_at_most_once():
    state = State()
    first = tx(ALICE, "alice", 0, "alice/message", "a")
    apply_tx(state, first, ACCOUNTS, CHAIN)
    apply_tx(state, tx(ALICE, "alice", 1, "alice/message", "b"), ACCOUNTS, CHAIN)
    assert reason_of(state, first) == "replayed_nonce"      # replay ở block sau
    assert state.data["alice/message"] == "b"
    assert reason_of(state, tx(ALICE, "alice", 5, "alice/message", "c")) == "future_nonce"


def test_state_hash_is_deterministic_and_covers_nonces():
    a = State({"x/1": "a", "y/1": "b"}, {"x": 1, "y": 1})
    b = State({"y/1": "b", "x/1": "a"}, {"y": 1, "x": 1})      # thứ tự chèn khác
    assert a.hash() == b.hash()
    assert a.hash() != State({"x/1": "a", "y/1": "b"}, {"x": 2, "y": 1}).hash()
    assert a.hash() != State({"x/1": "a", "y/1": "c"}, {"x": 1, "y": 1}).hash()


def test_same_ordered_txs_give_same_result_on_independent_states():
    txs = [tx(ALICE, "alice", 0, "alice/k", "1"), tx(BOB, "bob", 0, "bob/k", "2"),
           tx(ALICE, "alice", 1, "alice/k", "3")]
    one = execute_block(State(), txs, ACCOUNTS, CHAIN)
    two = execute_block(State(), [dict(t) for t in txs], ACCOUNTS, CHAIN)
    assert one.hash() == two.hash()
    assert one.data == {"alice/k": "3", "bob/k": "2"}


def test_invalid_block_never_touches_committed_state():
    committed = State({"alice/k": "old"}, {"alice": 1})
    before = committed.hash()
    txs = [tx(ALICE, "alice", 1, "alice/k", "new"), tx(ALICE, "alice", 1, "alice/k", "dup")]
    with pytest.raises(InvalidTx):
        execute_block(committed, txs, ACCOUNTS, CHAIN)
    assert committed.hash() == before and committed.data == {"alice/k": "old"}
    result = execute_block(committed, txs[:1], ACCOUNTS, CHAIN)
    assert committed.data == {"alice/k": "old"} and result.data == {"alice/k": "new"}


def test_account_name_with_slash_is_rejected():
    """Có cả "alice" và "alice/bob" thì alice ghi được khóa "alice/bob/..." của người kia."""
    from src.simulator import ConfigError, Simulation, build_genesis
    for bad in (["alice", "alice/bob"], [""]):
        with pytest.raises(ConfigError):
            build_genesis(CHAIN, 10, bad)
    genesis = build_genesis(CHAIN, 10, ["alice"])
    genesis["accounts"]["alice/bob"] = fixture_keypair(CHAIN, "alice/bob").pub_hex
    with pytest.raises(ConfigError):                     # genesis nạp từ file cũng bị kiểm
        Simulation({"name": "unit", "seed": 1, "target_height": 1, "max_time": 100,
                    "genesis": genesis})
