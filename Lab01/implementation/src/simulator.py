"""Dựng và chạy một scenario từ file cấu hình.

Simulator chỉ: tạo node, chuyển thông điệp, lên lịch, tiêm lỗi, bơm workload của
client và ghi log. Nó không chọn block, không đếm phiếu và không sửa state hộ node.
"""
import json
import os
import random

from .byzantine import ByzantineNode
from .crypto import fixture_keypair, sha256_hex, sign
from .encoding import canonical
from .execution import State
from .models import TX_FIELDS, make_tx, payload, vote_domain
from .network import Network, merge_net_config
from .node import Node
from .scheduler import EventLog, Scheduler


class ConfigError(Exception):
    pass


def check_account_name(name):
    """Luật sở hữu dùng tiền tố "<sender>/", nên tên tài khoản không được rỗng hay chứa "/".

    Nếu có cả "alice" và "alice/bob" thì khóa "alice/bob/x" thuộc về cả hai, và alice
    ghi đè được dữ liệu của alice/bob.
    """
    if not isinstance(name, str) or not name or "/" in name:
        raise ConfigError(f"tên tài khoản không hợp lệ (rỗng hoặc chứa '/'): {name!r}")


def build_genesis(chain_id, n_validators, account_names):
    """Genesis tái lập được: khóa công khai suy từ key fixture theo tên."""
    if n_validators < 8 or n_validators % 3 != 1:
        raise ConfigError(
            f"số validator phải có dạng 3f+1 và >= 8 (10, 13, 16...), nhận {n_validators}")
    validators = {f"v{i}": fixture_keypair(chain_id, f"v{i}").pub_hex
                  for i in range(n_validators)}
    accounts = dict(validators)
    for name in account_names:
        check_account_name(name)
        accounts[name] = fixture_keypair(chain_id, name).pub_hex
    return {"chain_id": chain_id, "validators": validators, "accounts": accounts}


def load_config(path):
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    base = os.path.dirname(os.path.abspath(path))
    if isinstance(cfg.get("genesis"), str):
        with open(os.path.join(base, cfg["genesis"]), "r", encoding="utf-8") as fh:
            cfg["genesis"] = json.load(fh)
    return cfg


def _genesis_of(cfg):
    genesis = cfg.get("genesis")
    if genesis is None:
        genesis = build_genesis(cfg.get("chain_id", "lab01-chain"), cfg.get("validators", 10),
                                cfg.get("workload", {}).get("accounts", []))
    n = len(genesis["validators"])
    if n < 8 or n % 3 != 1:
        raise ConfigError(f"số validator phải có dạng 3f+1 và >= 8, nhận {n}")
    for name, pub in genesis["accounts"].items():
        check_account_name(name)
        if fixture_keypair(genesis["chain_id"], name).pub_hex != pub:
            raise ConfigError(f"khóa công khai của {name} không khớp key fixture")
    return genesis


def _make_workload_tx(chain_id, spec):
    """Tạo transaction của client; `corrupt` dùng để tiêm lỗi chữ ký/domain."""
    signer = fixture_keypair(chain_id, spec.get("signer", spec["sender"]))
    tx = make_tx(signer, chain_id, spec["sender"], spec["nonce"], spec["key"], spec["value"])
    corrupt = spec.get("corrupt")
    if corrupt == "bad_sig":
        tx["sig"] = ("0" if tx["sig"][0] != "0" else "1") + tx["sig"][1:]
    elif corrupt == "tampered":
        tx["value"] = tx["value"] + "-tampered"       # sửa nội dung sau khi ký
    elif corrupt == "wrong_domain":
        # Tự khai domain VOTE và ký đúng dưới domain đó.
        tx["domain"] = vote_domain(chain_id)
        tx["sig"] = sign(signer, vote_domain(chain_id), payload(tx, TX_FIELDS))
    elif corrupt == "cross_domain":
        # Khai domain TX nhưng chữ ký được tạo dưới domain VOTE.
        tx["sig"] = sign(signer, vote_domain(chain_id), payload(tx, TX_FIELDS))
    elif corrupt == "wrong_chain":
        tx = make_tx(signer, "other-chain", spec["sender"], spec["nonce"], spec["key"],
                     spec["value"])
    elif corrupt is not None:
        raise ConfigError(f"corrupt không hỗ trợ: {corrupt}")
    return tx


def _expand_workload(cfg, validators):
    work = cfg.get("workload", {})
    items = []
    for spec in work.get("txs", []):
        items.append((spec["t"], spec.get("to", [validators[0]]), spec))
    gen = work.get("generated")
    if gen:
        accounts = work["accounts"]
        nonces = {a: gen.get("first_nonce", {}).get(a, 0) for a in accounts}
        for i in range(gen["count"]):
            sender = accounts[i % len(accounts)]
            spec = {"sender": sender, "nonce": nonces[sender],
                    "key": f"{sender}/k{i % 3}", "value": f"v{i}"}
            nonces[sender] += 1
            targets = [validators[i % len(validators)],
                       validators[(i + len(validators) // 2) % len(validators)]]
            items.append((gen.get("start", 5) + i * gen.get("interval", 40), targets, spec))
    return items


class Simulation:
    def __init__(self, cfg):
        self.cfg = cfg
        self.genesis = _genesis_of(cfg)
        self.chain_id = self.genesis["chain_id"]
        self.validators = sorted(self.genesis["validators"])
        self.byz_cfg = cfg.get("byzantine", {})
        unknown = set(self.byz_cfg) - set(self.validators)
        if unknown:
            raise ConfigError(f"node Byzantine không có trong validator set: {sorted(unknown)}")
        self.correct = [v for v in self.validators if v not in self.byz_cfg]
        f = (len(self.validators) - 1) // 3
        if len(self.byz_cfg) > f:
            raise ConfigError(f"quá f={f} node lỗi; scenario nằm ngoài fault model")
        self.sched = Scheduler()
        self.log = EventLog()
        self.rng = random.Random(cfg.get("seed", 1))
        self.net = Network(self.sched, self.rng, self.log, cfg.get("network"),
                           self.validators, self.correct)
        self.adversary = {}
        self.nodes = {}
        default_b = self.correct[(len(self.correct) + 1) // 2:]
        for vid in self.validators:
            keypair = fixture_keypair(self.chain_id, vid)
            args = (vid, keypair, self.genesis, cfg.get("params"), self.sched, self.net, self.log)
            behavior = self.byz_cfg.get(vid)
            active = behavior and set(behavior.get("modes", [])) - {"silent"}
            if active:
                behavior = {"group_b": default_b, **behavior}
                node = ByzantineNode(*args, behavior, self.adversary)
            else:
                node = Node(*args)
            self.nodes[vid] = node
            self.net.register(vid, node.on_message)

    def run(self):
        cfg = self.cfg
        for vid in self.validators:
            behavior = self.byz_cfg.get(vid, {})
            if "silent" in behavior.get("modes", []):
                self.sched.at(behavior.get("crash_at", 0), self.nodes[vid].crash)
        for vid in self.validators:
            self.sched.at(0, self.nodes[vid].start)
        for t, targets, spec in _expand_workload(cfg, self.validators):
            tx = _make_workload_tx(self.chain_id, spec)
            for target in targets:
                # Mỗi node nhận một bản sao riêng (không dùng chung đối tượng).
                self.sched.at(t, self.nodes[target].submit_tx, json.loads(json.dumps(tx)))
        target_height = cfg.get("target_height", 5)
        min_time = cfg.get("min_time", 0)

        def done():
            return self.sched.now >= min_time and all(
                len(self.nodes[v].ledger) >= target_height for v in self.correct)

        self.sched.run(cfg.get("max_time", 60000), done)
        return self.log.to_bytes(), self.summary()

    def summary(self):
        """Tóm tắt sau khi chạy.

        Các node đúng có thể dừng ở height khác nhau (node nhanh đã finalize thêm block
        khi node chậm nhất vừa tới mục tiêu), nên "state cuối" được lấy tại height chung
        cao nhất mà MỌI node đúng đã finalize; state hash của từng node ở height đó phải
        trùng nhau.
        """
        net_cfg = merge_net_config(self.cfg.get("network"))
        nodes = {}
        for vid in self.validators:
            node = self.nodes[vid]
            nodes[vid] = {"finalized_height": len(node.ledger), "tip": node.tip_hash,
                          "state_hash": node.state.hash(),
                          "chain": [entry["hash"] for entry in node.ledger]}
        common = min(nodes[v]["finalized_height"] for v in self.correct)

        def state_at_common(vid):
            ledger = self.nodes[vid].ledger
            return ledger[common - 1]["state"] if common else State()

        hashes = {state_at_common(v).hash() for v in self.correct}
        ref = state_at_common(self.correct[0])
        log_bytes = self.log.to_bytes()
        return {
            "scenario": self.cfg.get("name"), "seed": self.cfg.get("seed", 1),
            "chain_id": self.chain_id, "n": len(self.validators),
            "f": (len(self.validators) - 1) // 3,
            "quorum": 2 * ((len(self.validators) - 1) // 3) + 1,
            "gst": net_cfg["gst"], "delta": net_cfg["delta"],
            "target_height": self.cfg.get("target_height", 5),
            "end_time": self.sched.now,
            "correct_nodes": self.correct,
            "faulty_nodes": {v: self.byz_cfg[v].get("modes", []) for v in sorted(self.byz_cfg)},
            "min_correct_height": common,
            "final_state_hash": hashes.pop() if len(hashes) == 1 else None,
            "final_state": {"height": common, "data": ref.data, "nonces": ref.nonces},
            "nodes": nodes,
            "network": dict(self.net.stats),
            "log_lines": len(self.log.lines),
            "log_sha256": sha256_hex(log_bytes),
        }


def run_scenario(cfg):
    """Trả về (bytes của log, summary)."""
    return Simulation(cfg).run()


def write_outputs(out_dir, log_bytes, summary, verdict=None):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "events.log"), "wb") as fh:
        fh.write(log_bytes)
    with open(os.path.join(out_dir, "summary.json"), "wb") as fh:
        fh.write(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
                 + b"\n")
    if verdict is not None:
        with open(os.path.join(out_dir, "verdict.json"), "wb") as fh:
            fh.write(json.dumps(verdict, indent=2, sort_keys=True, ensure_ascii=False)
                     .encode("utf-8") + b"\n")


__all__ = ["Simulation", "run_scenario", "load_config", "build_genesis", "write_outputs",
           "ConfigError", "canonical"]
