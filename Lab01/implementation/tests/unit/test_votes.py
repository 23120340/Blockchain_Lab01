"""Đếm phiếu, quorum, chọn proposer."""
from src.consensus import VotePool, fault_bound, proposer_for, quorum_size
from src.crypto import fixture_keypair
from src.models import NIL, PRECOMMIT, PREVOTE, make_vote

CHAIN = "unit-chain"
KEYS = {f"v{i}": fixture_keypair(CHAIN, f"v{i}") for i in range(10)}
A, B = "aa" * 32, "bb" * 32


def vote(v, round_, phase, hash_):
    return make_vote(KEYS[v], CHAIN, 1, round_, phase, hash_, v)


def test_quorum_for_default_validator_set():
    assert (fault_bound(10), quorum_size(10)) == (3, 7)
    assert (fault_bound(4), quorum_size(4)) == (1, 3)
    assert (fault_bound(13), quorum_size(13)) == (4, 9)


def test_proposer_rotation_is_deterministic():
    validators = sorted(KEYS)
    assert proposer_for(validators, 1, 0) == "v1"
    assert proposer_for(validators, 1, 1) == "v2"
    assert proposer_for(validators, 9, 3) == "v2"
    assert [proposer_for(validators, h, 0) for h in range(1, 11)] == \
        [f"v{h % 10}" for h in range(1, 11)]


def test_duplicate_vote_is_not_counted_twice():
    pool = VotePool()
    assert pool.add(vote("v0", 0, PREVOTE, A)) == "added"
    for _ in range(5):
        assert pool.add(vote("v0", 0, PREVOTE, A)) == "duplicate"
    assert pool.count(0, PREVOTE, A) == 1 and pool.total(0, PREVOTE) == 1


def test_equivocation_keeps_only_first_vote():
    pool = VotePool()
    pool.add(vote("v0", 0, PREVOTE, A))
    assert pool.add(vote("v0", 0, PREVOTE, B)) == "equivocation"
    assert pool.add(vote("v0", 0, PREVOTE, NIL)) == "equivocation"
    assert pool.count(0, PREVOTE, A) == 1 and pool.count(0, PREVOTE, B) == 0
    assert pool.total(0, PREVOTE) == 1


def test_quorum_needs_same_block_round_and_phase():
    pool = VotePool()
    for i in range(4):
        pool.add(vote(f"v{i}", 0, PREVOTE, A))
    for i in range(4, 7):
        pool.add(vote(f"v{i}", 0, PREVOTE, B))        # block khác
    for i in range(7, 10):
        pool.add(vote(f"v{i}", 1, PREVOTE, A))        # round khác
    for i in range(4, 7):
        pool.add(vote(f"v{i}", 0, PRECOMMIT, A))      # phase khác
    assert pool.total(0, PREVOTE) == 7                # đủ 7 phiếu nhưng không cùng block
    assert pool.quorums(PREVOTE, 7) == [] and pool.quorums(PRECOMMIT, 7) == []
    for i in range(4, 7):
        assert pool.add(vote(f"v{i}", 0, PREVOTE, A)) == "equivocation"
    assert pool.quorums(PREVOTE, 7) == []             # đổi phiếu không được tính


def test_quorum_reached_exactly_at_2f_plus_1():
    pool = VotePool()
    for i in range(6):
        pool.add(vote(f"v{i}", 2, PRECOMMIT, A))
    assert pool.quorums(PRECOMMIT, 7) == []
    pool.add(vote("v6", 2, PRECOMMIT, A))
    assert pool.quorums(PRECOMMIT, 7) == [(2, A)]
    assert [v["validator"] for v in pool.votes_for(2, PRECOMMIT, A)] == [f"v{i}" for i in range(7)]


def test_nil_is_tallied_separately_from_blocks():
    pool = VotePool()
    for i in range(7):
        pool.add(vote(f"v{i}", 0, PREVOTE, NIL))
    assert pool.quorums(PREVOTE, 7) == [(0, NIL)]
    assert pool.count(0, PREVOTE, A) == 0
    assert pool.voters_in_round(0) == {f"v{i}" for i in range(7)}
