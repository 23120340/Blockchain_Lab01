"""Test oracle: CHỈ đọc log và summary sau khi chạy, không can thiệp vào node.

Kiểm tra safety xuyên suốt mọi sự kiện finalize (không chỉ state cuối), các luật
ký phiếu/locking của node đúng, ràng buộc header-trước-body, và các kỳ vọng riêng
của từng scenario khai báo trong khối `expect` của file cấu hình.
"""
import json

from .models import NIL, PREVOTE


def parse_log(log_bytes):
    return [json.loads(line) for line in log_bytes.decode("utf-8").splitlines() if line]


def count_events(events):
    counts = {}
    for ev in events:
        counts[ev["type"]] = counts.get(ev["type"], 0) + 1
        for field in ("reason", "kind", "mtype"):
            if field in ev:
                key = f"{ev['type']}:{ev[field]}"
                counts[key] = counts.get(key, 0) + 1
    return counts


def evaluate(cfg, log_bytes, summary):
    events = parse_log(log_bytes)
    correct = set(summary["correct_nodes"])
    quorum = summary["quorum"]
    validators = set(summary["nodes"])
    counts = count_events(events)
    counts["finalize_pre_gst"] = sum(
        1 for ev in events if ev["type"] == "finalize" and ev["t"] < summary["gst"])
    counts["round_start_after_round0"] = sum(
        1 for ev in events if ev["type"] == "round_start" and ev["round"] > 0)
    checks = []

    def check(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    # ---- safety trên mọi sự kiện finalize ---------------------------------
    by_height, per_node, bad_quorum, tx_seen = {}, {}, [], {}
    for ev in events:
        if ev["type"] != "finalize" or ev["node"] not in correct:
            continue
        by_height.setdefault(ev["height"], {}).setdefault(
            (ev["hash"], ev["state_hash"]), []).append(ev["node"])
        per_node.setdefault(ev["node"], []).append(ev)
        signers = ev["signers"]
        if len(set(signers)) != len(signers) or len(signers) < quorum or not set(signers) <= validators:
            bad_quorum.append((ev["node"], ev["height"]))
        for tid in ev["txs"]:
            tx_seen.setdefault((ev["node"], tid), 0)
            tx_seen[(ev["node"], tid)] += 1
    conflicts = {h: v for h, v in by_height.items() if len(v) > 1}
    check("no_conflicting_finalization", not conflicts,
          f"{len(by_height)} height đã finalize; xung đột: {sorted(conflicts)}")

    broken = []
    for node, evs in per_node.items():
        parent = None
        for i, ev in enumerate(evs):
            if ev["height"] != i + 1 or (parent is not None and ev["parent"] != parent):
                broken.append((node, ev["height"]))
            parent = ev["hash"]
    check("finalized_history_immutable", not broken,
          f"lịch sử không liên tục/đổi parent: {broken[:5]}")
    check("commit_has_quorum_of_distinct_validators", not bad_quorum, bad_quorum[:5])
    dup_tx = [k for k, v in tx_seen.items() if v > 1]
    check("tx_applied_at_most_once", not dup_tx, dup_tx[:5])

    # ---- luật ký phiếu và locking của node đúng ---------------------------
    signed, double, lock_viol = set(), [], []
    locks = {}   # (node, height) -> (hash, round)
    for ev in events:
        node = ev["node"]
        if node not in correct:
            continue
        if ev["type"] == "lock":
            prev = locks.get((node, ev["height"]))
            if prev is not None and ev["round"] <= prev[1]:
                lock_viol.append((node, ev["height"], "lock_round_not_later"))
            locks[(node, ev["height"])] = (ev["hash"], ev["round"])
        elif ev["type"] == "vote_sign":
            key = (node, ev["height"], ev["round"], ev["phase"])
            if key in signed:
                double.append(key)
            signed.add(key)
            lock = locks.get((node, ev["height"]))
            if (ev["phase"] == PREVOTE and ev["hash"] != NIL and lock is not None
                    and lock[0] != ev["hash"]):
                lock_viol.append((node, ev["height"], ev["round"]))
    check("one_vote_per_height_round_phase", not double, double[:5])
    check("lock_rule_respected", not lock_viol, lock_viol[:5])

    # ---- header trước body ------------------------------------------------
    accepted, requested, body_viol = set(), set(), []
    for ev in events:
        if ev["type"] == "header_accept":
            accepted.add((ev["node"], ev["hash"]))
        elif ev["type"] == "send" and ev.get("mtype") == "BODY_REQUEST" and ev["node"] in correct:
            if (ev["node"], ev["hash"]) not in accepted:
                body_viol.append(("request_before_accept", ev["node"], ev["hash"][:8]))
        elif ev["type"] == "deliver" and ev.get("mtype") == "BODY_REQUEST":
            requested.add((ev["node"], ev["peer"], ev["hash"]))
        elif ev["type"] in ("send", "delay") and ev.get("mtype") == "BODY" and ev["node"] in correct:
            if (ev["node"], ev["peer"], ev["hash"]) not in requested:
                body_viol.append(("body_before_request", ev["node"], ev["peer"]))
    check("body_only_after_header_accepted", not body_viol, body_viol[:5])

    # ---- kỳ vọng riêng của scenario ---------------------------------------
    expect = cfg.get("expect", {})
    heights = [summary["nodes"][v]["finalized_height"] for v in summary["correct_nodes"]]
    if expect.get("progress", True):
        check("progress_to_target_height", min(heights) >= summary["target_height"] > 0,
              f"min height={min(heights)}, target={summary['target_height']}, "
              f"t={summary['end_time']} ms")
    common = min(heights)
    states = {tuple(k) for k in by_height.get(common, {})} if common else set()
    check("same_chain_and_state_at_common_height", common == 0 or len(states) == 1,
          f"height chung={common}")
    if expect.get("delta_bound", True):
        net = summary["network"]
        ok = (net["max_latency_post_gst_correct"] <= summary["delta"]
              and net["post_gst_correct_drops"] == 0
              and net["correct_blocked_by_correct_post_gst"] == 0)
        check("post_gst_delivery_within_delta", ok,
              f"max latency={net['max_latency_post_gst_correct']} ms, Delta={summary['delta']} ms, "
              f"drop sau GST giữa node đúng={net['post_gst_correct_drops']}")
    for key, minimum in sorted(expect.get("min_counts", {}).items()):
        check(f"count[{key}]>={minimum}", counts.get(key, 0) >= minimum, counts.get(key, 0))
    for key, maximum in sorted(expect.get("max_counts", {}).items()):
        check(f"count[{key}]<={maximum}", counts.get(key, 0) <= maximum, counts.get(key, 0))
    for key, value in sorted(expect.get("state", {}).items()):
        actual = summary["final_state"]["data"].get(key)
        check(f"state[{key}]", actual == value, f"thực tế={actual!r}, mong đợi={value!r}")
    for key, value in sorted(expect.get("nonces", {}).items()):
        actual = summary["final_state"]["nonces"].get(key, 0)
        check(f"nonce[{key}]", actual == value, f"thực tế={actual}, mong đợi={value}")

    return {"scenario": summary["scenario"], "pass": all(c["ok"] for c in checks),
            "checks": checks, "counts": {k: counts[k] for k in sorted(counts)},
            "finalized_heights": {v: summary["nodes"][v]["finalized_height"]
                                  for v in summary["correct_nodes"]},
            "final_state_hash": summary["final_state_hash"]}
