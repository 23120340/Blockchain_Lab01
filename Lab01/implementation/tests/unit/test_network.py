"""Mạng mô phỏng: thứ tự sự kiện, delay/drop/duplicate, rate limit, block/unblock, cô lập node."""
import json
import random

import pytest

from src.network import Network, OutboundLimiter, PeerGuard
from src.scheduler import EventLog, Scheduler
from src.simulator import ConfigError, Simulation, build_genesis

NODES = ["a", "b", "c"]


def make_net(cfg, seed=1, correct=NODES):
    sched, log = Scheduler(), EventLog()
    net = Network(sched, random.Random(seed), log, cfg, NODES, correct)
    inbox = {n: [] for n in NODES}
    for n in NODES:
        net.register(n, lambda src, mtype, msg, n=n: inbox[n].append((sched.now, src, mtype, msg)))
    return sched, log, net, inbox


def types(log):
    return [json.loads(line)["type"] for line in log.lines]


def test_event_queue_breaks_ties_by_scheduling_order():
    sched, out = Scheduler(), []
    sched.at(5, out.append, "b1")
    sched.at(3, out.append, "a")
    sched.at(5, out.append, "b2")
    sched.at(5, out.append, "b3")
    sched.run(100)
    assert out == ["a", "b1", "b2", "b3"] and sched.now == 5
    with pytest.raises(ValueError):
        sched.at(1, out.append, "past")


def test_outbound_limiter_queues_excess_messages():
    limiter = OutboundLimiter(window=10, max_msgs=2)
    assert [limiter.reserve(0) for _ in range(5)] == [0, 0, 10, 10, 20]
    assert limiter.reserve(35) == 35


def test_peer_guard_blocks_then_releases():
    guard = PeerGuard(window=100, max_msgs=3, block_ms=50)
    assert [guard.admit("x", 1) for _ in range(4)] == ["ok", "ok", "ok", "block_now"]
    assert guard.admit("x", 40) == "blocked"
    assert guard.admit("y", 40) == "ok"                   # peer khác không bị ảnh hưởng
    assert guard.admit("x", 51) == "ok"


def test_delivery_is_delayed_within_configured_bounds_and_logged():
    sched, log, net, inbox = make_net({"post_gst": {"delay_min": 5, "delay_max": 40}})
    for i in range(50):
        net.send("a", "b", "VOTE", {"i": i}, height=1)
    sched.run(1000)
    assert len(inbox["b"]) == 50 and all(5 <= t <= 40 for t, *_ in inbox["b"])
    assert [m[3]["i"] for m in inbox["b"]] != list(range(50))      # có đảo thứ tự
    first = json.loads(log.lines[0])
    assert {"t", "node", "type", "height"} <= set(first) and first["type"] == "send"
    assert net.stats["max_latency_post_gst_correct"] <= 40


def test_drop_duplicate_and_partition_before_gst():
    cfg = {"gst": 1000, "pre_gst": {"delay_min": 1, "delay_max": 5, "drop_permille": 1000}}
    sched, log, net, inbox = make_net(cfg)
    net.send("a", "b", "VOTE", {}, height=1)
    sched.run(100)
    assert inbox["b"] == [] and types(log) == ["drop"]

    cfg = {"post_gst": {"delay_min": 1, "delay_max": 5, "dup_permille": 1000}}
    sched, log, net, inbox = make_net(cfg)
    net.send("a", "b", "VOTE", {}, height=1)
    sched.run(100)
    assert len(inbox["b"]) == 2 and "duplicate" in types(log)

    cfg = {"partitions": [{"from": 0, "to": 50, "groups": [["a"], ["b", "c"]]}]}
    sched, log, net, inbox = make_net(cfg)
    net.send("a", "b", "VOTE", {}, height=1)
    net.send("b", "c", "VOTE", {}, height=1)
    sched.at(60, net.send, "a", "b", "VOTE", {}, 1)
    sched.run(200)
    assert len(inbox["c"]) == 1 and len(inbox["b"]) == 1 and inbox["b"][0][0] >= 60
    assert json.loads(log.lines[0])["reason"] == "partition"


def test_message_sent_before_gst_arrives_by_gst_plus_bound():
    cfg = {"gst": 100, "delta": 50,
           "pre_gst": {"delay_min": 5000, "delay_max": 9000},
           "post_gst": {"delay_min": 5, "delay_max": 40}}
    sched, log, net, inbox = make_net(cfg)
    net.send("a", "b", "VOTE", {}, height=1)
    sched.run(20000)
    assert inbox["b"][0][0] == 140
    assert "delay" in types(log)


def test_rate_limit_delays_and_logs_but_never_drops():
    cfg = {"outbound": {"window_ms": 10, "max_msgs": 2},
           "post_gst": {"delay_min": 1, "delay_max": 1}}
    sched, log, net, inbox = make_net(cfg)
    for i in range(6):
        net.send("a", "b", "VOTE", {"i": i}, height=1)
    sched.run(1000)
    assert [t for t, *_ in inbox["b"]] == [1, 1, 11, 11, 21, 21]
    assert types(log).count("delay") == 4 and net.stats["dropped"] == 0


def test_overactive_peer_is_blocked_then_unblocked():
    cfg = {"inbound": {"window_ms": 100, "max_msgs_per_peer": 5, "block_ms": 200},
           "post_gst": {"delay_min": 1, "delay_max": 1}}
    sched, log, net, inbox = make_net(cfg, correct=["b", "c"])
    net.exempt.add("a")
    for _ in range(20):
        net.send("a", "b", "VOTE", {}, height=1)
    sched.at(150, net.send, "a", "b", "VOTE", {"late": 1}, 1)     # vẫn đang bị chặn
    sched.at(300, net.send, "a", "b", "VOTE", {"ok": 1}, 1)       # đã được mở
    sched.at(10, net.send, "c", "b", "VOTE", {"other": 1}, 1)     # peer khác vẫn qua
    sched.run(1000)
    got = [m[3] for m in inbox["b"]]
    assert len(got) == 7 and {"ok": 1} in got and {"other": 1} in got and {"late": 1} not in got
    kinds = types(log)
    assert kinds.count("block") == 1 and kinds.count("unblock") == 1
    assert kinds.index("block") < kinds.index("unblock")


def test_messages_are_copied_not_shared():
    sched, log, net, inbox = make_net({})
    payload = {"list": [1, 2]}
    net.send("a", "b", "X", payload, height=1)
    net.send("a", "c", "X", payload, height=1)
    payload["list"].append(3)                                # sửa sau khi gửi
    sched.run(1000)
    got_b, got_c = inbox["b"][0][3], inbox["c"][0][3]
    assert got_b == {"list": [1, 2]} and got_b is not got_c and got_b["list"] is not got_c["list"]


def test_same_seed_same_log_different_seed_different_log():
    def run(seed):
        sched, log, net, _ = make_net({"gst": 50, "pre_gst": {
            "delay_min": 1, "delay_max": 30, "drop_permille": 300, "dup_permille": 200}}, seed)
        for i in range(40):
            sched.at(i, net.send, "a", "b", "VOTE", {"i": i}, 1)
        sched.run(1000)
        return log.to_bytes()
    assert run(7) == run(7) and run(7) != run(8)


# ---- simulator ------------------------------------------------------------

SMALL = {"name": "unit", "seed": 3, "target_height": 3, "max_time": 20000,
         "workload": {"accounts": ["alice"], "txs": [
             {"t": 5, "to": ["v0"], "sender": "alice", "nonce": 0,
              "key": "alice/message", "value": "hello"}]}}


@pytest.mark.parametrize("n", [4, 7, 8, 9, 11])
def test_validator_count_must_be_3f_plus_1_and_at_least_8(n):
    with pytest.raises(ConfigError):
        build_genesis("c", n, [])


def test_valid_validator_counts():
    assert len(build_genesis("c", 10, [])["validators"]) == 10
    assert len(build_genesis("c", 13, ["alice"])["accounts"]) == 14


def test_more_than_f_faulty_nodes_is_outside_the_model():
    cfg = dict(SMALL, byzantine={f"v{i}": {"modes": ["silent"]} for i in range(4)})
    with pytest.raises(ConfigError):
        Simulation(cfg)


def test_nodes_do_not_share_mutable_state():
    sim = Simulation(dict(SMALL))
    sim.run()
    a, b = sim.nodes["v0"], sim.nodes["v1"]
    assert len(a.ledger) >= 3 and a.state.hash() == b.state.hash()
    assert a.state is not b.state and a.state.data is not b.state.data
    assert a.ledger is not b.ledger and a.votes is not b.votes and a.mempool is not b.mempool
    assert a.ledger[0]["header"] is not b.ledger[0]["header"]
    assert a.ledger[0]["precommits"] is not b.ledger[0]["precommits"]
    a.state.data["alice/message"] = "corrupted"
    a.ledger[0]["header"]["state_hash"] = "corrupted"
    assert b.state.data["alice/message"] == "hello"
    assert b.ledger[0]["header"]["state_hash"] != "corrupted"


def test_simulation_is_reproducible_in_process():
    log1, sum1 = Simulation(dict(SMALL)).run()
    log2, sum2 = Simulation(dict(SMALL)).run()
    assert log1 == log2 and sum1 == sum2 and sum1["final_state_hash"] is not None
    log3, _ = Simulation(dict(SMALL, seed=4)).run()
    assert log3 != log1
