"""Giá đỡ cho unit test: một node thật nối vào mạng giả chỉ ghi lại thông điệp gửi đi."""
import json

from src.crypto import fixture_keypair
from src.execution import State, execute_block
from src.models import (PRECOMMIT, PREVOTE, block_hash, genesis_hash, make_header,
                        make_proposal, make_tx, make_vote)
from src.node import Node
from src.scheduler import EventLog, Scheduler

CHAIN = "unit-chain"


class FakeNet:
    def __init__(self):
        self.sent = []
        self.exempt = set()

    def send(self, src, dst, mtype, payload, height, round=None, block_hash=None):
        self.sent.append({"src": src, "dst": dst, "mtype": mtype,
                          "payload": json.loads(json.dumps(payload))})

    def of(self, mtype):
        return [m for m in self.sent if m["mtype"] == mtype]


class Env:
    """n validator (mặc định 4: f = 1, quorum = 3) và node đang được kiểm thử là v0."""

    def __init__(self, n=4, node="v0"):
        self.ids = [f"v{i}" for i in range(n)]
        self.keys = {name: fixture_keypair(CHAIN, name)
                     for name in self.ids + ["alice", "bob", "mallory"]}
        validators = {v: self.keys[v].pub_hex for v in self.ids}
        accounts = {**validators, "alice": self.keys["alice"].pub_hex,
                    "bob": self.keys["bob"].pub_hex}
        self.genesis = {"chain_id": CHAIN, "validators": validators, "accounts": accounts}
        self.sched, self.log, self.net = Scheduler(), EventLog(), FakeNet()
        self.node = Node(node, self.keys[node], self.genesis, None, self.sched, self.net, self.log)
        self.node.start()

    # ---- dựng dữ liệu ----------------------------------------------------
    def tx(self, sender, nonce, key, value, signer=None):
        return make_tx(self.keys[signer or sender], CHAIN, sender, nonce, key, value)

    def block(self, proposer, txs=(), height=1, parent=None, state=None, state_hash=None):
        txs = list(txs)
        if state_hash is None:
            state_hash = execute_block(state or State(), txs, self.genesis["accounts"],
                                       CHAIN).hash()
        header = make_header(self.keys[proposer], CHAIN, height,
                             parent or genesis_hash(self.genesis), txs, state_hash, proposer)
        return header, txs

    def proposal(self, proposer, round_, header, pol_round=-1, pol_votes=(), height=1):
        return make_proposal(self.keys[proposer], CHAIN, height, round_, pol_round, header,
                             proposer, list(pol_votes))

    def vote(self, validator, round_, phase, hash_, height=1):
        return make_vote(self.keys[validator], CHAIN, height, round_, phase, hash_, validator)

    # ---- đưa thông điệp vào node -----------------------------------------
    def deliver(self, src, mtype, msg):
        self.node.on_message(src, mtype, json.loads(json.dumps(msg)))

    def give_block(self, proposer, round_, header, txs, **kw):
        """Proposal rồi body, đúng thứ tự handshake."""
        hash_ = block_hash(header)
        self.deliver(proposer, "PROPOSAL", self.proposal(proposer, round_, header, **kw))
        self.deliver(proposer, "BODY", {"height": header["height"], "block_hash": hash_,
                                        "txs": txs})
        return hash_

    def votes_from(self, validators, round_, phase, hash_):
        for v in validators:
            self.deliver(v, "VOTE", self.vote(v, round_, phase, hash_))

    def my_votes(self, phase=None, round_=None):
        """Các phiếu KHÁC NHAU mà node đã ký (mỗi phiếu được broadcast tới mọi peer)."""
        seen, out = set(), []
        for m in self.net.of("VOTE"):
            v = m["payload"]
            key = (v["height"], v["round"], v["phase"], v["block_hash"])
            if v["validator"] == self.node.id and key not in seen:
                seen.add(key)
                if (phase is None or v["phase"] == phase) and (round_ is None or v["round"] == round_):
                    out.append(v)
        return out

    def events(self, type_):
        return [json.loads(line) for line in self.log.lines
                if json.loads(line)["type"] == type_]


__all__ = ["Env", "FakeNet", "CHAIN", "PREVOTE", "PRECOMMIT"]
