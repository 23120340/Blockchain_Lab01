"""Node Byzantine dùng cho fault injection.

Lõi vẫn là node đúng (để theo kịp chain), còn hành vi lỗi được bật theo `modes`:
  equivocate    - ký hai phiếu xung đột cho hai nhóm node; khi làm proposer thì
                  gửi hai block khác nhau cho hai nhóm.
  forge         - gửi phiếu/proposal sai chữ ký, sai domain, sai chain, sai người ký
                  và body không ai yêu cầu.
  invalid_block - khi làm proposer thì đề xuất block sai (`variant`).
  replay        - phát lại phiếu, proposal và transaction đã thấy trước đó.
  flood         - gửi dồn dập vào một peer, bỏ qua giới hạn gửi của chính mình.

Các node Byzantine được phép thông đồng qua `adversary` (dict dùng chung của
phe tấn công). Node đúng không bao giờ thấy đối tượng này.
"""
from .crypto import fixture_keypair, hash_obj, sign
from .models import (NIL, PRECOMMIT, PREVOTE, block_hash, make_header, make_proposal, make_tx, make_vote,
                     tx_domain, VOTE_FIELDS, payload)
from .node import Node


class ByzantineNode(Node):
    def __init__(self, node_id, keypair, genesis, params, sched, net, log, behavior, adversary):
        super().__init__(node_id, keypair, genesis, params, sched, net, log)
        self.modes = set(behavior.get("modes", []))
        self.behavior = behavior
        self.adversary = adversary
        self.byz_bodies = {}      # block sai/khác mà lõi đúng không công nhận
        self.recorded = []        # thông điệp đã thấy, dùng để replay
        self.group_b = set(behavior.get("group_b", []))
        adversary.setdefault("members", set()).add(node_id)
        if "flood" in self.modes:
            net.exempt.add(node_id)

    # ---- ghi lại để replay ------------------------------------------------

    def _dispatch(self, src, mtype, msg):
        if "replay" in self.modes and mtype in ("VOTE", "PROPOSAL") and len(self.recorded) < 400:
            self.recorded.append((mtype, msg))
        super()._dispatch(src, mtype, msg)

    def _on_body_request(self, src, m):
        if isinstance(m, dict) and m.get("block_hash") in self.byz_bodies:
            hash_ = m["block_hash"]
            self._send(src, "BODY", {"height": self.height, "block_hash": hash_,
                                     "txs": self.byz_bodies[hash_]}, hash_=hash_)
            return
        super()._on_body_request(src, m)

    # ---- hành vi theo round ----------------------------------------------

    def _start_round(self, round_):
        super()._start_round(round_)
        if "forge" in self.modes and round_ == 0:
            self._forge()
        if "replay" in self.modes:
            self._replay()
        if "flood" in self.modes:
            self._flood()

    def _forge(self):
        h, r = self.height, self.round
        good = make_vote(self.kp, self.chain_id, h, r, PREVOTE, NIL, self.id)
        forged = []
        bad_sig = dict(good)
        bad_sig["sig"] = ("0" if good["sig"][0] != "0" else "1") + good["sig"][1:]
        forged.append(("VOTE", bad_sig))
        # Phiếu tự khai domain TX.
        wrong_domain = dict(good)
        wrong_domain["domain"] = tx_domain(self.chain_id)
        wrong_domain["sig"] = sign(self.kp, tx_domain(self.chain_id), payload(good, VOTE_FIELDS))
        forged.append(("VOTE", wrong_domain))
        # Khai domain VOTE nhưng chữ ký được tạo dưới domain TX.
        cross = dict(good)
        cross["sig"] = wrong_domain["sig"]
        forged.append(("VOTE", cross))
        other = "other-chain"
        forged.append(("VOTE", make_vote(self.kp, other, h, r, PREVOTE, NIL, self.id)))
        mallory = fixture_keypair(self.chain_id, "mallory")
        forged.append(("VOTE", make_vote(mallory, self.chain_id, h, r, PREVOTE, NIL, "mallory")))
        # Mạo danh validator khác: tên của nạn nhân, chữ ký của mình.
        victim = self.peers[0]
        forged.append(("VOTE", make_vote(self.kp, self.chain_id, h, r, PREVOTE, NIL, victim)))
        # Proposal mang header sai chữ ký.
        header, _ = self._build_block([])
        header = dict(header)
        header["sig"] = bad_sig["sig"]
        forged.append(("PROPOSAL", make_proposal(self.kp, self.chain_id, h, r, -1, header,
                                                 self.id, [])))
        # Body không ai yêu cầu, cho header chưa ai chấp nhận.
        forged.append(("BODY", {"height": h, "block_hash": hash_obj(["forged", h]), "txs": []}))
        self._log("byz_forge", round=r, count=len(forged))
        for mtype, msg in forged:
            self._broadcast(mtype, msg, r)

    def _replay(self):
        old = self.recorded[: self.behavior.get("replay_count", 12)]
        txs = [tx for entry in self.ledger[-2:] for tx in entry["txs"]]
        if not old and not txs:
            return
        self._log("byz_replay", round=self.round, count=len(old) + len(txs))
        for mtype, msg in old:
            self._broadcast(mtype, msg)
        for tx in txs:
            self._broadcast("TX", tx)

    def _flood(self):
        target = self.behavior.get("target", self.peers[0])
        burst = self.behavior.get("burst", 600)
        if self.height % self.behavior.get("every", 3) != 0 or self.round != 0:
            return
        self._log("byz_flood", peer=target, count=burst)
        for _ in range(burst):
            self._send(target, "SYNC_REQUEST", {"height": 0})

    # ---- equivocation -----------------------------------------------------

    def _in_group_b(self, peer):
        return peer in self.group_b

    def _broadcast_vote(self, vote):
        if "equivocate" not in self.modes:
            return super()._broadcast_vote(vote)
        pair = self.adversary.get((vote["height"], vote["round"]))
        if pair and vote["block_hash"] == pair[0]:
            other = pair[1]
        elif vote["block_hash"] != NIL:
            other = NIL
        else:
            other = None
        favor = self.behavior.get("favor")
        if favor:
            if not (pair and vote["block_hash"] == pair[0]):
                return super()._broadcast_vote(vote)      # ngoài block A thì bỏ phiếu thẳng
            if vote["phase"] == PRECOMMIT:
                return self._withhold_commit(vote, pair[1], favor)
        conflict = None
        if other is not None:
            conflict = make_vote(self.kp, self.chain_id, vote["height"], vote["round"],
                                 vote["phase"], other, self.id)
            self._log("byz_equivocate_vote", round=vote["round"], phase=vote["phase"],
                      hash=vote["block_hash"], other=other)
        # Mọi peer nhận CẢ HAI phiếu; nhóm B nhận phiếu xung đột trước. Phiếu thứ hai được
        # gửi trễ hơn cận mạng để phiếu thứ nhất chắc chắn đến trước: mỗi nhóm thấy một
        # "sự thật" khác nhau. Node đúng phải chỉ tính phiếu đầu và ghi nhận equivocation.
        late = self.behavior.get("second_vote_delay", 60)
        for peer in self.peers:
            first, second = (conflict, vote) if self._in_group_b(peer) else (vote, conflict)
            if conflict is None:
                first, second = vote, None
            self._send(peer, "VOTE", first, first["round"], first["block_hash"])
            if second is not None:
                self.sched.after(late, self._send_late, peer, second)

    def _withhold_commit(self, vote, other, favor):
        """Giấu commit: chỉ `favor` nhận PRECOMMIT cho A (đủ để nó finalize A một mình);
        các node đúng khác nhận PRECOMMIT cho B; đồng bọn không nhận gì để còn ở lại
        height này và bỏ phiếu cho block khác ở round sau."""
        conflict = make_vote(self.kp, self.chain_id, vote["height"], vote["round"],
                             vote["phase"], other, self.id)
        self._log("byz_withhold_commit", round=vote["round"], hash=vote["block_hash"],
                  peer=favor)
        for peer in self.peers:
            if peer == favor:
                self._send(peer, "VOTE", vote, vote["round"], vote["block_hash"])
            elif peer not in self.adversary["members"]:
                self._send(peer, "VOTE", conflict, conflict["round"], conflict["block_hash"])

    def _enter(self, step, phase, hash_):
        # Trong đòn giấu commit, node Byzantine phớt lờ lock của chính nó: thay vì NIL,
        # nó prevote luôn block mới được đề xuất để kéo các node đúng rời khỏi block A.
        if self.behavior.get("favor") and phase == PREVOTE and hash_ == NIL:
            proposal = self.proposals.get(self.round)
            if proposal is not None and proposal["block_hash"] in self.blocks:
                hash_ = proposal["block_hash"]
        return super()._enter(step, phase, hash_)

    def _send_late(self, peer, vote):
        if not self.crashed:
            self._send(peer, "VOTE", vote, vote["round"], vote["block_hash"])

    def _propose(self):
        if "invalid_block" in self.modes:
            return self._propose_invalid()
        if "equivocate" not in self.modes or self.valid_hash is not None:
            return super()._propose()
        # Hai block khác nhau cho cùng (height, round).
        txs_a = self._select_txs()
        extra = make_tx(self.kp, self.chain_id, self.id, self.state.nonces.get(self.id, 0),
                        f"{self.id}/equivocation", f"h{self.height}r{self.round}")
        txs_b = txs_a + [extra]
        proposals = []
        for txs in (txs_a, txs_b):
            header, post = self._build_block(txs)
            hash_ = block_hash(header)
            self.headers[hash_] = header
            self.blocks[hash_] = (txs, post)
            proposals.append(make_proposal(self.kp, self.chain_id, self.height, self.round,
                                           -1, header, self.id, []))
        prop_a, prop_b = proposals
        self.proposals.setdefault(self.round, prop_a)
        self.adversary[(self.height, self.round)] = (prop_a["block_hash"], prop_b["block_hash"])
        self._log("byz_equivocate_proposal", round=self.round, hash=prop_a["block_hash"],
                  other=prop_b["block_hash"])
        for peer in self.peers:
            prop = prop_b if self._in_group_b(peer) else prop_a
            self._send(peer, "PROPOSAL", prop, self.round, prop["block_hash"])

    # ---- block sai --------------------------------------------------------

    def _propose_invalid(self):
        variant = self.behavior.get("variant", "bad_state_hash")
        txs = self._select_txs()
        state_hash = None
        if variant == "replay_tx" and self.ledger and any(e["txs"] for e in self.ledger):
            old = next(e["txs"][0] for e in self.ledger if e["txs"])
            txs = [old] + txs
        elif variant == "dup_tx" and txs:
            txs = txs + [txs[0]]
        elif variant == "foreign_key":
            # Chữ ký thật của mình nhưng ghi vào khóa của người khác.
            victim = sorted(a for a in self.accounts if a != self.id)[0]
            txs = txs + [make_tx(self.kp, self.chain_id, self.id,
                                 self.state.nonces.get(self.id, 0), f"{victim}/message", "stolen")]
        else:
            variant = "bad_state_hash"
            state_hash = hash_obj(["wrong-state", self.height, self.round])
        if state_hash is None:
            state_hash = self.state.hash()
        header = make_header(self.kp, self.chain_id, self.height, self.tip_hash, txs,
                             state_hash, self.id)
        hash_ = block_hash(header)
        self.byz_bodies[hash_] = txs
        proposal = make_proposal(self.kp, self.chain_id, self.height, self.round, -1, header,
                                 self.id, [])
        self._log("byz_invalid_block", round=self.round, hash=hash_, variant=variant)
        self._broadcast("PROPOSAL", proposal, self.round, hash_)
