"""Node đúng (honest): ledger, state, mempool, vote pool, lock và consensus view riêng.

Consensus hai pha kiểu Tendermint:
  PROPOSAL(header) -> BODY_REQUEST -> BODY -> PREVOTE -> lock -> PRECOMMIT -> finalize

Node chỉ trao đổi qua `net.send`; không đọc trạng thái của node khác.
"""
from .consensus import VotePool, fault_bound, proposer_for, quorum_size
from .execution import InvalidTx, State, check_tx_static, execute_block
from .models import (HEADER_FIELDS, HEADER_SPEC, NIL, PRECOMMIT, PREVOTE, PROPOSAL_FIELDS,
                     PROPOSAL_SPEC, block_hash, check_certificate, check_signed, check_vote,
                     genesis_hash, has_shape, header_domain, make_header, make_proposal,
                     make_vote, proposal_domain, tx_id, tx_root)

PROPOSE_STEP, PREVOTE_STEP, PRECOMMIT_STEP = "propose", "prevote", "precommit"

DEFAULT_PARAMS = {
    "timeout_propose": 200,    # >= 3 chặng mạng: proposal, body request, body
    "timeout_prevote": 100,
    "timeout_precommit": 100,
    "timeout_step": 50,        # cộng thêm cho mỗi round
    "resend_interval": 300,    # gửi lại phiếu của mình khi đứng yên quá lâu
    "sync_delay": 100,         # chờ trước khi xin commit của height đang thiếu
    "sync_retry": 200,
    "fetch_retry": 150,        # xin lại header/body từ peer khác
    "max_block_txs": 10,
    "future_buffer": 2000,
}


class Node:
    def __init__(self, node_id, keypair, genesis, params, sched, net, log):
        self.id, self.kp = node_id, keypair
        self.sched, self.net, self.log = sched, net, log
        self.chain_id = genesis["chain_id"]
        self.val_pubs = dict(genesis["validators"])
        self.accounts = dict(genesis["accounts"])
        self.validators = sorted(self.val_pubs)
        self.peers = [v for v in self.validators if v != node_id]
        self.n = len(self.validators)
        self.f = fault_bound(self.n)
        self.quorum = quorum_size(self.n)
        self.p = {**DEFAULT_PARAMS, **(params or {})}

        self.state = State()            # state đã commit
        self.ledger = []                # block đã finalize, ledger[i] là height i+1
        self.by_hash = {}
        self.tip_hash = genesis_hash(genesis)
        self.height = 1                 # height đang quyết định
        self.mempool = {}
        self.signed = {}                # (height, round, phase) -> block_hash đã ký
        self.future = []                # thông điệp của height kế tiếp
        self.crashed = False
        self.sync_peer = None
        self._evaluating = False
        self._progress = 0
        self._handlers = {
            "TX": self._on_tx, "PROPOSAL": self._on_proposal, "VOTE": self._on_vote,
            "BODY_REQUEST": self._on_body_request, "BODY": self._on_body,
            "HEADER_REQUEST": self._on_header_request, "HEADER": self._on_header,
            "SYNC_REQUEST": self._on_sync_request, "COMMIT": self._on_commit,
        }
        self._reset_height()

    def _reset_height(self):
        self.round, self.step = -1, None
        self.locked_hash, self.locked_round = None, -1
        self.valid_hash, self.valid_round = None, -1
        self.votes = VotePool()
        self.proposals = {}      # round -> proposal đầu tiên hợp lệ
        self.headers = {}        # block_hash -> header đã chấp nhận
        self.blocks = {}         # block_hash -> (txs, state sau thực thi)  [đã kiểm tra]
        self.invalid = {}        # block_hash -> lý do
        self.pol_certs = {}      # (round, block_hash) -> quorum PREVOTE kèm proposal
        self.commit_certs = {}   # block_hash -> (round, quorum PRECOMMIT)
        self.fetching = {}       # block_hash -> số lần đã thử
        self.timeouts_set = set()
        self.behind_peers = []
        self.sync_attempt = 0

    # ---- tiện ích ---------------------------------------------------------

    def _log(self, type_, **fields):
        self.log.emit(self.sched.now, self.id, type_, self.height, **fields)

    def _send(self, dst, mtype, payload, round_=None, hash_=None):
        self.net.send(self.id, dst, mtype, payload, self.height, round_, hash_)

    def _broadcast(self, mtype, payload, round_=None, hash_=None):
        for peer in self.peers:
            self._send(peer, mtype, payload, round_, hash_)

    def _reject(self, mtype, reason, peer, **extra):
        self._log("reject", mtype=mtype, reason=reason, peer=peer, **extra)

    def _ignore(self, mtype, reason, peer, **extra):
        self._log("ignore", mtype=mtype, reason=reason, peer=peer, **extra)

    def _bump(self):
        """Đánh dấu có tiến triển; hẹn giờ gửi lại nếu sau đó đứng yên."""
        self._progress += 1
        self.sched.after(self.p["resend_interval"], self._on_resend, self._progress)

    def _timeout(self, kind, round_):
        return self.p["timeout_" + kind] + round_ * self.p["timeout_step"]

    # ---- vòng đời ---------------------------------------------------------

    def start(self):
        self._start_round(0)
        self._evaluate()

    def crash(self):
        self.crashed = True
        self._log("crash")

    def on_message(self, src, mtype, msg):
        if self.crashed:
            return
        self._dispatch(src, mtype, msg)
        self._evaluate()

    def _dispatch(self, src, mtype, msg):
        handler = self._handlers.get(mtype)
        if handler is None or not isinstance(msg, dict):
            self._reject(mtype, "malformed", src)
            return
        handler(src, msg)

    def _route_height(self, src, mtype, msg, height):
        """True nếu thông điệp thuộc height đang xử lý."""
        if height < self.height:
            self._ignore(mtype, "stale_height", src, msg_height=height)
            return False
        if height > self.height:
            if height == self.height + 1 and len(self.future) < self.p["future_buffer"]:
                self.future.append((src, mtype, msg))
            self._note_behind(src)
            return False
        return True

    # ---- transaction ------------------------------------------------------

    def submit_tx(self, tx):
        """Client gửi transaction vào node này."""
        if self.crashed:
            return
        self._log("tx_submit", tx=tx_id(tx) if isinstance(tx, dict) else None)
        if self._admit_tx(tx, "client"):
            self._broadcast("TX", tx)

    def _on_tx(self, src, tx):
        self._admit_tx(tx, src)

    def _admit_tx(self, tx, src):
        reason = check_tx_static(tx, self.accounts, self.chain_id)
        if reason is None and tx["nonce"] < self.state.nonces.get(tx["sender"], 0):
            reason = "stale_nonce"
        if reason:
            self._reject("TX", reason, src)
            return False
        tid = tx_id(tx)
        if tid in self.mempool:
            self._ignore("TX", "duplicate_tx", src, tx=tid)
            return False
        self.mempool[tid] = tx
        self._log("tx_accept", tx=tid, peer=src)
        return True

    def _select_txs(self):
        """Chọn transaction cho block mới: theo sender, nonce liên tiếp từ state."""
        by_sender = {}
        for tid in sorted(self.mempool):
            tx = self.mempool[tid]
            by_sender.setdefault(tx["sender"], {}).setdefault(tx["nonce"], tx)
        chosen = []
        for sender in sorted(by_sender):
            nonce = self.state.nonces.get(sender, 0)
            while nonce in by_sender[sender] and len(chosen) < self.p["max_block_txs"]:
                chosen.append(by_sender[sender][nonce])
                nonce += 1
        return chosen

    # ---- proposal / header / body ----------------------------------------

    def _check_header(self, header, expect_hash):
        if not has_shape(header, HEADER_SPEC):
            return "malformed"
        if block_hash(header) != expect_hash:
            return "header_hash_mismatch"
        pub = self.val_pubs.get(header["proposer"])
        reason = check_signed(header, HEADER_FIELDS, header_domain(self.chain_id),
                              self.chain_id, pub)
        if reason:
            return reason
        if header["height"] != self.height:
            return "wrong_height"
        if header["parent_hash"] != self.tip_hash:
            return "bad_parent"
        return None

    def _on_proposal(self, src, p):
        if not has_shape(p, PROPOSAL_SPEC) or p["round"] < 0 or p["pol_round"] < -1:
            return self._reject("PROPOSAL", "malformed", src)
        pub = self.val_pubs.get(p["proposer"])
        reason = check_signed(p, PROPOSAL_FIELDS, proposal_domain(self.chain_id),
                              self.chain_id, pub)
        if reason:
            return self._reject("PROPOSAL", reason, src, round=p["round"])
        if not self._route_height(src, "PROPOSAL", p, p["height"]):
            return
        round_, hash_ = p["round"], p["block_hash"]
        if p["proposer"] != proposer_for(self.validators, self.height, round_):
            return self._reject("PROPOSAL", "wrong_proposer", src, round=round_)
        reason = self._check_header(p["header"], hash_)
        if reason:
            return self._reject("PROPOSAL", reason, src, round=round_, hash=hash_)
        if p["pol_round"] == -1:
            if p["header"]["proposer"] != p["proposer"]:
                return self._reject("PROPOSAL", "wrong_proposer", src, round=round_, hash=hash_)
        elif p["pol_round"] >= round_ or not check_certificate(
                p["pol_votes"], PREVOTE, self.height, p["pol_round"], hash_,
                self.chain_id, self.val_pubs, self.quorum):
            return self._reject("PROPOSAL", "bad_pol", src, round=round_, hash=hash_)
        existing = self.proposals.get(round_)
        if existing is not None:
            if existing["block_hash"] == hash_:
                return self._ignore("PROPOSAL", "duplicate_proposal", src, round=round_)
            return self._log("equivocation", mtype="PROPOSAL", peer=p["proposer"],
                             round=round_, hash=hash_, first=existing["block_hash"])
        self.proposals[round_] = p
        if p["pol_round"] >= 0:
            self.pol_certs[(p["pol_round"], hash_)] = p["pol_votes"]
        self._accept_header(hash_, p["header"], src)

    def _accept_header(self, hash_, header, src):
        if hash_ not in self.headers:
            self.headers[hash_] = header
            self._log("header_accept", hash=hash_, peer=src)
        if hash_ not in self.blocks and hash_ not in self.invalid and hash_ not in self.fetching:
            self.fetching[hash_] = 0
            self._send(src, "BODY_REQUEST", {"height": self.height, "block_hash": hash_},
                       hash_=hash_)
            self.sched.after(self.p["fetch_retry"], self._on_fetch_retry, self.height, hash_)

    def _find_block(self, hash_):
        if hash_ in self.blocks:
            return self.headers[hash_], self.blocks[hash_][0]
        entry = self.by_hash.get(hash_)
        if entry is not None:
            return entry["header"], entry["txs"]
        return None

    def _on_body_request(self, src, m):
        if not has_shape(m, {"height": int, "block_hash": str}):
            return self._reject("BODY_REQUEST", "malformed", src)
        found = self._find_block(m["block_hash"])
        if found is None:
            return self._ignore("BODY_REQUEST", "unknown_block", src, hash=m["block_hash"])
        # Body chỉ rời node sau khi bên nhận báo đã chấp nhận header (chính yêu cầu này).
        self._send(src, "BODY", {"height": found[0]["height"], "block_hash": m["block_hash"],
                                 "txs": found[1]}, hash_=m["block_hash"])

    def _on_body(self, src, m):
        if not has_shape(m, {"height": int, "block_hash": str, "txs": list}):
            return self._reject("BODY", "malformed", src)
        hash_ = m["block_hash"]
        if hash_ not in self.headers:
            return self._reject("BODY", "body_without_accepted_header", src, hash=hash_)
        if hash_ in self.blocks or hash_ in self.invalid:
            return self._ignore("BODY", "duplicate_body", src, hash=hash_)
        header = self.headers[hash_]
        if not all(isinstance(tx, dict) for tx in m["txs"]) or tx_root(m["txs"]) != header["tx_root"]:
            return self._reject("BODY", "tx_root_mismatch", src, hash=hash_)
        self._validate_block(hash_, header, m["txs"])

    def _validate_block(self, hash_, header, txs):
        """Thực thi trên state tạm; state đã commit không đổi."""
        try:
            post = execute_block(self.state, txs, self.accounts, self.chain_id)
            reason = None if post.hash() == header["state_hash"] else "state_hash_mismatch"
        except InvalidTx as exc:
            post, reason = None, "invalid_tx:" + exc.reason
        self.fetching.pop(hash_, None)
        if reason:
            self.invalid[hash_] = reason
            self._log("block_invalid", hash=hash_, reason=reason)
        else:
            self.blocks[hash_] = (txs, post)
            self._log("block_valid", hash=hash_, txs=len(txs))

    def _fetch_candidates(self, hash_):
        names = set(self.votes.voters_for_hash(hash_))
        names.update(p["proposer"] for p in self.proposals.values() if p["block_hash"] == hash_)
        if hash_ in self.commit_certs:
            names.update(v["validator"] for v in self.commit_certs[hash_][1])
        names.discard(self.id)
        return sorted(names)

    def _ensure_fetch(self, hash_):
        """Đã có quorum PRECOMMIT cho block chưa có đủ dữ liệu: đi lấy qua mạng."""
        if hash_ in self.fetching:
            return
        self.fetching[hash_] = 0
        self._on_fetch_retry(self.height, hash_, immediate=True)

    def _on_fetch_retry(self, height, hash_, immediate=False):
        if self.crashed or height != self.height or hash_ not in self.fetching:
            return
        candidates = self._fetch_candidates(hash_)
        if candidates:
            attempt = self.fetching[hash_]
            self.fetching[hash_] = attempt + 1
            peer = candidates[attempt % len(candidates)]
            mtype = "BODY_REQUEST" if hash_ in self.headers else "HEADER_REQUEST"
            self._log("fetch", mtype=mtype, hash=hash_, peer=peer)
            self._send(peer, mtype, {"height": self.height, "block_hash": hash_}, hash_=hash_)
        self.sched.after(self.p["fetch_retry"], self._on_fetch_retry, height, hash_)

    def _on_header_request(self, src, m):
        if not has_shape(m, {"height": int, "block_hash": str}):
            return self._reject("HEADER_REQUEST", "malformed", src)
        header = self.headers.get(m["block_hash"])
        if header is None and m["block_hash"] in self.by_hash:
            header = self.by_hash[m["block_hash"]]["header"]
        if header is None:
            return self._ignore("HEADER_REQUEST", "unknown_block", src, hash=m["block_hash"])
        self._send(src, "HEADER", {"header": header}, hash_=m["block_hash"])

    def _on_header(self, src, m):
        if not has_shape(m, {"header": dict}) or not has_shape(m["header"], HEADER_SPEC):
            return self._reject("HEADER", "malformed", src)
        hash_ = block_hash(m["header"])
        if hash_ not in self.fetching or hash_ in self.headers:
            return self._ignore("HEADER", "unrequested_header", src, hash=hash_)
        reason = self._check_header(m["header"], hash_)
        if reason:
            return self._reject("HEADER", reason, src, hash=hash_)
        self.headers[hash_] = m["header"]
        self._log("header_accept", hash=hash_, peer=src)
        self._send(src, "BODY_REQUEST", {"height": self.height, "block_hash": hash_}, hash_=hash_)

    # ---- vote -------------------------------------------------------------

    def _on_vote(self, src, vote):
        reason = check_vote(vote, self.chain_id, self.val_pubs)
        if reason:
            return self._reject("VOTE", reason, src)
        if not self._route_height(src, "VOTE", vote, vote["height"]):
            return
        result = self.votes.add(vote)
        if result == "duplicate":
            self._ignore("VOTE", "duplicate_vote", src, validator=vote["validator"],
                         round=vote["round"], phase=vote["phase"])
        elif result == "equivocation":
            self._log("equivocation", mtype="VOTE", peer=vote["validator"], round=vote["round"],
                      phase=vote["phase"], hash=vote["block_hash"])

    def _vote(self, phase, hash_):
        """Ký tối đa một phiếu cho mỗi (height, round, phase)."""
        key = (self.height, self.round, phase)
        if key in self.signed:
            self._log("double_sign_blocked", round=self.round, phase=phase)
            return
        self.signed[key] = hash_
        vote = make_vote(self.kp, self.chain_id, self.height, self.round, phase, hash_, self.id)
        self.votes.add(vote)
        self._log("vote_sign", round=self.round, phase=phase, hash=hash_)
        self._broadcast_vote(vote)

    def _broadcast_vote(self, vote):
        self._broadcast("VOTE", vote, vote["round"], vote["block_hash"])

    # ---- đồng bộ height ---------------------------------------------------

    def _note_behind(self, src):
        if src not in self.behind_peers:
            self.behind_peers.append(src)
            if len(self.behind_peers) == 1:
                self.sched.after(self.p["sync_delay"], self._on_sync_timer, self.height)

    def _on_sync_timer(self, height):
        if self.crashed or height != self.height or not self.behind_peers:
            return
        peer = self.behind_peers[self.sync_attempt % len(self.behind_peers)]
        self.sync_attempt += 1
        self._log("sync_request", peer=peer)
        self._send(peer, "SYNC_REQUEST", {"height": self.height})
        self.sched.after(self.p["sync_retry"], self._on_sync_timer, height)

    def _on_sync_request(self, src, m):
        if not has_shape(m, {"height": int}):
            return self._reject("SYNC_REQUEST", "malformed", src)
        if not 1 <= m["height"] < self.height:
            return self._ignore("SYNC_REQUEST", "not_finalized", src, msg_height=m["height"])
        entry = self.ledger[m["height"] - 1]
        self._send(src, "COMMIT", {"height": m["height"], "header": entry["header"],
                                   "round": entry["round"], "precommits": entry["precommits"]},
                   entry["round"], entry["hash"])

    def _on_commit(self, src, m):
        if not has_shape(m, {"height": int, "header": dict, "round": int, "precommits": list}):
            return self._reject("COMMIT", "malformed", src)
        if m["height"] != self.height:
            return self._ignore("COMMIT", "stale_height", src, msg_height=m["height"])
        if not has_shape(m["header"], HEADER_SPEC):
            return self._reject("COMMIT", "malformed", src)
        hash_ = block_hash(m["header"])
        reason = self._check_header(m["header"], hash_)
        if reason is None and not check_certificate(
                m["precommits"], PRECOMMIT, self.height, m["round"], hash_,
                self.chain_id, self.val_pubs, self.quorum):
            reason = "bad_commit_cert"
        if reason:
            return self._reject("COMMIT", reason, src, hash=hash_)
        self.sync_peer = src
        if hash_ not in self.commit_certs:
            self.commit_certs[hash_] = (m["round"], m["precommits"])
            self._log("commit_cert", hash=hash_, round=m["round"], peer=src)
        self._accept_header(hash_, m["header"], src)

    # ---- máy trạng thái consensus ----------------------------------------

    def _start_round(self, round_):
        self.round, self.step = round_, PROPOSE_STEP
        self._bump()
        proposer = proposer_for(self.validators, self.height, round_)
        self._log("round_start", round=round_, proposer=proposer)
        if proposer == self.id:
            self._propose()
        self.sched.after(self._timeout("propose", round_), self._on_timeout,
                         "propose", self.height, round_)

    def _pol_votes(self, round_, hash_):
        votes = self.votes.votes_for(round_, PREVOTE, hash_)
        return votes if len(votes) >= self.quorum else self.pol_certs[(round_, hash_)]

    def _build_block(self, txs):
        post = execute_block(self.state, txs, self.accounts, self.chain_id)
        header = make_header(self.kp, self.chain_id, self.height, self.tip_hash, txs,
                             post.hash(), self.id)
        return header, post

    def _propose(self):
        if self.valid_hash is not None:
            # Đề xuất lại block đã có quorum PREVOTE, kèm bằng chứng để node khác đổi lock.
            header, pol_round = self.headers[self.valid_hash], self.valid_round
            pol_votes = self._pol_votes(pol_round, self.valid_hash)
        else:
            txs = self._select_txs()
            header, post = self._build_block(txs)
            hash_ = block_hash(header)
            self.headers[hash_] = header
            self.blocks[hash_] = (txs, post)
            pol_round, pol_votes = -1, []
        proposal = make_proposal(self.kp, self.chain_id, self.height, self.round, pol_round,
                                 header, self.id, pol_votes)
        self.proposals.setdefault(self.round, proposal)
        self._log("propose", round=self.round, hash=proposal["block_hash"], pol_round=pol_round)
        self._broadcast("PROPOSAL", proposal, self.round, proposal["block_hash"])

    def _pols(self):
        """Mọi (round, block) có quorum PREVOTE đã quan sát (từ pool hoặc bằng chứng kèm)."""
        found = {(r, h) for r, h in self.votes.quorums(PREVOTE, self.quorum) if h != NIL}
        found.update(self.pol_certs)
        return sorted(found)

    def _commit_quorums(self):
        found = {}
        for round_, hash_ in self.votes.quorums(PRECOMMIT, self.quorum):
            if hash_ != NIL:
                found[(round_, hash_)] = self.votes.votes_for(round_, PRECOMMIT, hash_)
        for hash_, (round_, votes) in self.commit_certs.items():
            found.setdefault((round_, hash_), votes)
        return [(r, h, found[(r, h)]) for r, h in sorted(found)]

    def _evaluate(self):
        if self.crashed or self._evaluating:
            return
        self._evaluating = True
        try:
            while self._step_once():
                pass
        finally:
            self._evaluating = False

    def _step_once(self) -> bool:
        """Áp dụng MỘT luật; trả True nếu có thay đổi để vòng lặp xét lại từ đầu."""
        # 1. Finalize: quorum PRECOMMIT cho cùng block, cùng round, block đã kiểm tra.
        for round_, hash_, votes in self._commit_quorums():
            if hash_ in self.blocks:
                self._finalize(hash_, round_, votes)
                return True
            if hash_ not in self.invalid:
                self._ensure_fetch(hash_)

        # 2. Bắt kịp round: f+1 validator đã ở round cao hơn.
        ahead = [r for r in self.votes.rounds()
                 if r > self.round and len(self.votes.voters_in_round(r)) >= self.f + 1]
        if ahead:
            self._start_round(max(ahead))
            return True

        # 3. Lock: quan sát quorum PREVOTE cho block (không NIL) ở round MUỘN HƠN lock hiện tại.
        changed = False
        for round_, hash_ in self._pols():
            if hash_ not in self.blocks:
                continue
            if round_ > self.locked_round:
                self.locked_hash, self.locked_round = hash_, round_
                self._log("lock", round=round_, hash=hash_)
                changed = True
            if round_ > self.valid_round:
                self.valid_hash, self.valid_round = hash_, round_
        if changed:
            return True

        # 4. PREVOTE cho proposal của round hiện tại.
        if self.step == PROPOSE_STEP:
            proposal = self.proposals.get(self.round)
            if proposal is not None:
                hash_ = proposal["block_hash"]
                if hash_ in self.invalid:
                    return self._enter(PREVOTE_STEP, PREVOTE, NIL)
                if hash_ in self.blocks:
                    # Đã lock block khác thì chỉ được prevote block này nếu luật 3 ở trên đã
                    # chuyển lock nhờ quorum PREVOTE ở round muộn hơn; nếu không thì NIL.
                    free = self.locked_hash is None or self.locked_hash == hash_
                    return self._enter(PREVOTE_STEP, PREVOTE, hash_ if free else NIL)

        # 5. PRECOMMIT.
        if self.step == PREVOTE_STEP:
            if self.locked_round == self.round and self.locked_hash is not None:
                return self._enter(PRECOMMIT_STEP, PRECOMMIT, self.locked_hash)
            if self.votes.count(self.round, PREVOTE, NIL) >= self.quorum:
                return self._enter(PRECOMMIT_STEP, PRECOMMIT, NIL)
            self._arm("prevote", PREVOTE)

        # 6. Đủ quorum PRECOMMIT bất kỳ mà chưa quyết định: hẹn giờ sang round sau.
        self._arm("precommit", PRECOMMIT)
        return False

    def _enter(self, step, phase, hash_) -> bool:
        self.step = step
        self._bump()
        self._vote(phase, hash_)
        return True

    def _arm(self, kind, phase):
        key = (kind, self.round)
        if key not in self.timeouts_set and self.votes.total(self.round, phase) >= self.quorum:
            self.timeouts_set.add(key)
            self.sched.after(self._timeout(kind, self.round), self._on_timeout,
                             kind, self.height, self.round)

    def _on_timeout(self, kind, height, round_):
        if self.crashed or height != self.height or round_ != self.round:
            return
        if kind == "propose" and self.step == PROPOSE_STEP:
            self._log("timeout", kind=kind, round=round_)
            self._enter(PREVOTE_STEP, PREVOTE, NIL)
        elif kind == "prevote" and self.step == PREVOTE_STEP:
            self._log("timeout", kind=kind, round=round_)
            self._enter(PRECOMMIT_STEP, PRECOMMIT, NIL)
        elif kind == "precommit":
            self._log("timeout", kind=kind, round=round_)
            self._start_round(round_ + 1)   # lock KHÔNG bị xóa khi timeout
        self._evaluate()

    def _on_resend(self, token):
        if self.crashed or token != self._progress:
            return
        self._log("resend", round=self.round)
        proposal = self.proposals.get(self.round)
        if proposal is not None and proposal["proposer"] == self.id:
            self._broadcast("PROPOSAL", proposal, self.round, proposal["block_hash"])
        for phase in (PREVOTE, PRECOMMIT):
            vote = self.votes.get(self.round, phase, self.id)
            if vote is not None:
                self._broadcast_vote(vote)
        self.sched.after(self.p["resend_interval"], self._on_resend, token)

    def _finalize(self, hash_, round_, votes):
        txs, post = self.blocks[hash_]
        header = self.headers[hash_]
        entry = {"hash": hash_, "header": header, "txs": txs, "round": round_,
                 "precommits": votes, "state": post}
        self.ledger.append(entry)
        self.by_hash[hash_] = entry
        self.state = post
        self.tip_hash = hash_
        self._log("finalize", round=round_, hash=hash_, parent=header["parent_hash"],
                  state_hash=post.hash(), signers=[v["validator"] for v in votes],
                  txs=[tx_id(tx) for tx in txs])
        for tid in [t for t, tx in self.mempool.items()
                    if tx["nonce"] < self.state.nonces.get(tx["sender"], 0)]:
            del self.mempool[tid]
        synced = hash_ in self.commit_certs
        self.height += 1
        self._reset_height()
        buffered, self.future = self.future, []
        self._start_round(0)
        if synced and self.sync_peer is not None:
            # Vừa bắt kịp nhờ commit certificate: xin luôn height kế tiếp.
            self._log("sync_request", peer=self.sync_peer)
            self._send(self.sync_peer, "SYNC_REQUEST", {"height": self.height})
        for src, mtype, msg in buffered:
            self._dispatch(src, mtype, msg)
