"""Luật ký phiếu và locking (mục 6.1 của đề) trên một node, n = 4, quorum = 3.

Proposer của height 1: round 0 = v1, round 1 = v2, round 2 = v3, round 3 = v0.
"""
from src.models import NIL, PRECOMMIT, PREVOTE, block_hash
from tests.helpers import Env


def locked_on_a():
    """v0 nhận block A ở round 0 và thấy quorum PREVOTE cho A."""
    env = Env()
    header, txs = env.block("v1", [env.tx("alice", 0, "alice/message", "A")])
    a = env.give_block("v1", 0, header, txs)
    env.votes_from(["v1", "v2"], 0, PREVOTE, a)
    return env, a


def to_round_1(env):
    """Round 0 không đủ PRECOMMIT cho block nào: hết giờ thì sang round 1."""
    env.votes_from(["v1", "v2"], 0, PRECOMMIT, NIL)
    env.sched.run(env.sched.now + 150)
    assert env.node.round == 1


def block_c(env):
    return env.block("v2", [env.tx("bob", 0, "bob/message", "C")])


def test_quorum_of_prevotes_locks_block_and_records_round():
    env, a = locked_on_a()
    assert (env.node.locked_hash, env.node.locked_round) == (a, 0)
    assert [(e["hash"], e["round"]) for e in env.events("lock")] == [(a, 0)]
    assert [v["block_hash"] for v in env.my_votes(PRECOMMIT, 0)] == [a]


def test_no_lock_below_quorum_or_on_nil():
    env = Env()
    header, txs = env.block("v1")
    a = env.give_block("v1", 0, header, txs)
    env.votes_from(["v1"], 0, PREVOTE, a)                 # mới có 2/3 phiếu
    assert env.node.locked_hash is None and env.my_votes(PRECOMMIT) == []
    env2 = Env()
    env2.votes_from(["v1", "v2", "v3"], 0, PREVOTE, NIL)
    assert env2.node.locked_hash is None


def test_at_most_one_prevote_and_one_precommit_per_round():
    env, a = locked_on_a()
    env.node._vote(PREVOTE, NIL)                           # cố ký lần hai
    env.node._vote(PRECOMMIT, NIL)
    header, txs = env.block("v1")
    env.deliver("v1", "PROPOSAL", env.proposal("v1", 0, header))   # gửi lại proposal
    env.votes_from(["v1", "v2", "v3"], 0, PREVOTE, a)              # gửi lại phiếu
    assert [v["block_hash"] for v in env.my_votes(PREVOTE, 0)] == [a]
    assert [v["block_hash"] for v in env.my_votes(PRECOMMIT, 0)] == [a]
    assert len(env.events("double_sign_blocked")) == 2


def test_locked_validator_prevotes_nil_for_a_different_block():
    env, a = locked_on_a()
    to_round_1(env)
    header, txs = block_c(env)
    c = env.give_block("v2", 1, header, txs)
    assert c != a and c in env.node.blocks                 # C hợp lệ, chỉ là không phải block đã lock
    assert [v["block_hash"] for v in env.my_votes(PREVOTE, 1)] == [NIL]
    assert (env.node.locked_hash, env.node.locked_round) == (a, 0)


def test_locked_validator_still_prevotes_its_locked_block_when_reproposed():
    env, a = locked_on_a()
    to_round_1(env)
    header = env.node.headers[a]
    pol = [env.vote(v, 0, PREVOTE, a) for v in ("v0", "v1", "v2")]
    env.deliver("v2", "PROPOSAL", env.proposal("v2", 1, header, pol_round=0, pol_votes=pol))
    assert [v["block_hash"] for v in env.my_votes(PREVOTE, 1)] == [a]


def test_timeouts_never_release_the_lock():
    env, a = locked_on_a()
    to_round_1(env)
    env.sched.run(env.sched.now + 5000)                    # mọi timeout lần lượt nổ
    assert (env.node.locked_hash, env.node.locked_round) == (a, 0)
    later = [v for v in env.my_votes(PREVOTE) if v["round"] > 0]
    assert later and all(v["block_hash"] == NIL for v in later)
    assert len(env.events("timeout")) >= 2


def test_lock_moves_only_after_quorum_of_prevotes_in_a_later_round():
    env, a = locked_on_a()
    to_round_1(env)
    header, txs = block_c(env)
    c = env.give_block("v2", 1, header, txs)               # round 1: NIL vì đang lock A
    pol = [env.vote(v, 1, PREVOTE, c) for v in ("v1", "v2", "v3")]
    env.deliver("v3", "PROPOSAL", env.proposal("v3", 2, header, pol_round=1, pol_votes=pol))
    env.votes_from(["v1", "v2"], 2, PREVOTE, c)            # f+1 node đã ở round 2
    assert env.node.round == 2
    # Lock chuyển A -> C nhờ bằng chứng ở round 1 (> 0); sau đó chính round 2 cũng đủ quorum.
    assert [(e["hash"], e["round"]) for e in env.events("lock")] == [(a, 0), (c, 1), (c, 2)]
    assert [v["block_hash"] for v in env.my_votes(PREVOTE, 2)] == [c]
    assert [v["block_hash"] for v in env.my_votes(PRECOMMIT, 2)] == [c]


def test_quorum_from_same_or_earlier_round_does_not_move_the_lock():
    env, a = locked_on_a()
    to_round_1(env)
    header, txs = block_c(env)
    c = env.give_block("v2", 1, header, txs)
    stale = [env.vote(v, 0, PREVOTE, c) for v in ("v1", "v2", "v3")]   # bằng chứng ở round 0
    env.deliver("v3", "PROPOSAL", env.proposal("v3", 2, header, pol_round=0, pol_votes=stale))
    env.votes_from(["v1", "v2"], 2, PREVOTE, c)
    assert env.node.round == 2
    assert (env.node.locked_hash, env.node.locked_round) == (a, 0)
    assert [v["block_hash"] for v in env.my_votes(PREVOTE, 2)] == [NIL]


def test_reproposal_with_insufficient_evidence_is_rejected():
    env, a = locked_on_a()
    header, txs = block_c(env)
    c = block_hash(header)
    weak = [env.vote(v, 1, PREVOTE, c) for v in ("v1", "v2")]            # 2 < quorum
    env.deliver("v3", "PROPOSAL", env.proposal("v3", 2, header, pol_round=1, pol_votes=weak))
    twice = weak + [weak[0]]                                            # lặp một validator
    env.deliver("v3", "PROPOSAL", env.proposal("v3", 2, header, pol_round=1, pol_votes=twice))
    assert [e["reason"] for e in env.events("reject")] == ["bad_pol", "bad_pol"]
    assert c not in env.node.headers


def test_finalize_needs_precommit_quorum_for_same_block_and_round():
    env = Env()
    header, txs = env.block("v1", [env.tx("alice", 0, "alice/message", "hello")])
    a = env.give_block("v1", 0, header, txs)
    env.deliver("v1", "VOTE", env.vote("v1", 0, PRECOMMIT, a))
    env.deliver("v2", "VOTE", env.vote("v2", 1, PRECOMMIT, a))      # round khác
    env.deliver("v3", "VOTE", env.vote("v3", 0, PREVOTE, a))        # phase khác
    env.deliver("v3", "VOTE", env.vote("v3", 1, PRECOMMIT, NIL))    # NIL
    assert env.node.ledger == [] and env.node.state.data == {}
    env.votes_from(["v2", "v3"], 0, PRECOMMIT, a)
    assert [e["hash"] for e in env.node.ledger] == [a]
    assert env.node.state.data == {"alice/message": "hello"}
    assert env.node.height == 2 and env.node.tip_hash == a
    final = env.events("finalize")[0]
    assert sorted(final["signers"]) == ["v1", "v2", "v3"] and final["round"] == 0


def test_precommit_quorum_for_nil_never_finalizes():
    env = Env()
    env.votes_from(["v1", "v2", "v3"], 0, PRECOMMIT, NIL)
    env.sched.run(env.sched.now + 150)
    assert env.node.ledger == [] and env.node.round == 1


def test_commit_for_unknown_block_fetches_header_then_body_before_finalizing():
    env = Env()
    header, txs = env.block("v1", [env.tx("alice", 0, "alice/message", "hello")])
    a = block_hash(header)
    env.votes_from(["v1", "v2", "v3"], 0, PRECOMMIT, a)    # proposal đã bị mất
    assert env.node.ledger == []
    asked = env.net.of("HEADER_REQUEST")
    assert len(asked) == 1 and asked[0]["payload"]["block_hash"] == a
    env.deliver(asked[0]["dst"], "HEADER", {"header": header})
    assert [m["payload"]["block_hash"] for m in env.net.of("BODY_REQUEST")] == [a]
    assert env.node.ledger == []                           # chưa có body thì chưa commit
    env.deliver(asked[0]["dst"], "BODY", {"height": 1, "block_hash": a, "txs": txs})
    assert [e["hash"] for e in env.node.ledger] == [a]
    assert env.node.state.data == {"alice/message": "hello"}


def test_votes_for_other_heights_are_not_counted_now():
    env = Env()
    header, txs = env.block("v1")
    a = env.give_block("v1", 0, header, txs)
    for v in ("v1", "v2", "v3"):
        env.deliver(v, "VOTE", env.vote(v, 0, PRECOMMIT, a, height=2))   # height tương lai
        env.deliver(v, "VOTE", env.vote(v, 0, PRECOMMIT, a, height=3))
    assert env.node.ledger == [] and env.node.votes.total(0, PRECOMMIT) == 0
    assert len(env.node.future) == 3                       # chỉ giữ tạm phiếu của height kế tiếp
