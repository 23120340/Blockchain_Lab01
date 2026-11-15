"""Oracle phải TRƯỢT khi log có vi phạm (một phép kiểm luôn đạt thì vô dụng).

Log được dựng tay bằng EventLog, đúng định dạng node và mạng ghi ra.
"""
from src.oracle import evaluate
from src.scheduler import EventLog

NODES = ["v0", "v1", "v2", "v3"]          # n = 4, quorum = 3
H1, H2 = "aa" * 32, "bb" * 32
CFG = {"expect": {"progress": False, "delta_bound": False}}


def summary(heights=None):
    heights = heights or {v: 0 for v in NODES}
    return {"scenario": "unit", "correct_nodes": NODES, "quorum": 3, "gst": 0, "delta": 50,
            "target_height": 1, "end_time": 0, "final_state_hash": None,
            "final_state": {"height": 0, "data": {}, "nonces": {}},
            "nodes": {v: {"finalized_height": heights[v]} for v in NODES}, "network": {}}


def verdict(build, heights=None):
    log = EventLog()
    build(log)
    out = evaluate(CFG, log.to_bytes(), summary(heights))
    return {c["name"]: c["ok"] for c in out["checks"]}


def finalize(log, node, height, hash_, parent="00" * 32, signers=("v0", "v1", "v2"), txs=()):
    log.emit(10 * height, node, "finalize", height, round=0, hash=hash_, parent=parent,
             state_hash="s" + hash_[:4], signers=list(signers), txs=list(txs))


def test_clean_log_passes():
    def build(log):
        for v in NODES:
            finalize(log, v, 1, H1)
    checks = verdict(build, {v: 1 for v in NODES})
    assert all(checks.values()), checks


def test_conflicting_finalization_is_caught():
    def build(log):
        finalize(log, "v0", 1, H1)
        finalize(log, "v1", 1, H2)
    checks = verdict(build, {"v0": 1, "v1": 1, "v2": 0, "v3": 0})
    assert not checks["no_conflicting_finalization"]


def test_broken_history_and_weak_quorum_are_caught():
    def build(log):
        finalize(log, "v0", 1, H1)
        finalize(log, "v0", 2, H2, parent="cc" * 32)                 # parent sai
        finalize(log, "v1", 1, H1, signers=("v0", "v0", "v1"))      # lặp người ký
    checks = verdict(build)
    assert not checks["finalized_history_immutable"]
    assert not checks["commit_has_quorum_of_distinct_validators"]


def test_double_sign_and_lock_violation_are_caught():
    def build(log):
        log.emit(1, "v0", "vote_sign", 1, round=0, phase="PREVOTE", hash=H1)
        log.emit(2, "v0", "vote_sign", 1, round=0, phase="PREVOTE", hash="NIL")
        log.emit(3, "v1", "lock", 1, round=0, hash=H1)
        log.emit(4, "v1", "vote_sign", 1, round=1, phase="PREVOTE", hash=H2)
    checks = verdict(build)
    assert not checks["one_vote_per_height_round_phase"]
    assert not checks["lock_rule_respected"]


def test_body_sent_without_request_is_caught_even_if_dropped():
    def build(log):
        log.emit(1, "v0", "send", 1, msg=1, mtype="BODY", hash=H1, peer="v1")
        log.emit(1, "v0", "drop", 1, msg=1, mtype="BODY", hash=H1, peer="v1",
                 reason="partition")
    assert not verdict(build)["body_only_after_header_accepted"]


def test_body_after_request_passes_and_request_needs_accepted_header():
    def ok(log):
        log.emit(1, "v1", "header_accept", 1, hash=H1, peer="v0")
        log.emit(1, "v1", "send", 1, msg=1, mtype="BODY_REQUEST", hash=H1, peer="v0")
        log.emit(5, "v0", "deliver", 1, msg=1, mtype="BODY_REQUEST", hash=H1, peer="v1")
        log.emit(5, "v0", "send", 1, msg=2, mtype="BODY", hash=H1, peer="v1")
    assert verdict(ok)["body_only_after_header_accepted"]

    def premature(log):
        log.emit(1, "v1", "send", 1, msg=1, mtype="BODY_REQUEST", hash=H1, peer="v0")
    assert not verdict(premature)["body_only_after_header_accepted"]


def test_transaction_applied_twice_is_caught():
    def build(log):
        finalize(log, "v0", 1, H1, txs=["t1"])
        finalize(log, "v0", 2, H2, parent=H1, txs=["t1"])
    assert not verdict(build)["tx_applied_at_most_once"]


def test_progress_and_delta_bound_can_fail():
    cfg = {"expect": {"progress": True, "delta_bound": True}}
    s = summary()
    s["network"] = {"max_latency_post_gst_correct": 51, "post_gst_correct_drops": 0,
                    "correct_blocked_by_correct_post_gst": 0}
    out = evaluate(cfg, b"", s)
    checks = {c["name"]: c["ok"] for c in out["checks"]}
    assert not checks["progress_to_target_height"]
    assert not checks["post_gst_delivery_within_delta"]
