"""Mạng mô phỏng không tin cậy.

Mạng chỉ chuyển bytes, lên lịch và tạo lỗi; không đọc nội dung để quyết định
thay node. Mỗi thông điệp được mã hóa thành bytes khi gửi và giải mã khi nhận
nên hai node không bao giờ dùng chung một đối tượng.

Sự kiện log: send, delay, drop, duplicate, deliver, block, unblock.
"""
from .encoding import canonical, decode


class OutboundLimiter:
    """Mỗi node gửi tối đa `max_msgs` thông điệp trong một cửa sổ `window` ms.
    Thông điệp vượt hạn mức được XẾP HÀNG sang cửa sổ sau (không bị bỏ)."""

    def __init__(self, window, max_msgs):
        self.window = window
        self.max_msgs = max_msgs
        self._win = -1
        self._count = 0

    def reserve(self, now) -> int:
        """Trả về thời điểm thông điệp thực sự rời node (>= now)."""
        current = now // self.window
        if self._win < current:
            self._win, self._count = current, 0
        while self._count >= self.max_msgs:
            self._win, self._count = self._win + 1, 0
        self._count += 1
        return max(now, self._win * self.window)


class PeerGuard:
    """Phía nhận: peer gửi quá `max_msgs` trong một cửa sổ sẽ bị chặn `block_ms`."""

    def __init__(self, window, max_msgs, block_ms):
        self.window = window
        self.max_msgs = max_msgs
        self.block_ms = block_ms
        self._count = {}
        self.blocked_until = {}

    def admit(self, peer, now):
        """Trả về 'ok', 'blocked' hoặc 'block_now'."""
        if self.blocked_until.get(peer, -1) > now:
            return "blocked"
        win = now // self.window
        last_win, count = self._count.get(peer, (-1, 0))
        count = count + 1 if last_win == win else 1
        self._count[peer] = (win, count)
        if count > self.max_msgs:
            self.blocked_until[peer] = now + self.block_ms
            # Xóa bộ đếm: nếu không, peer hết hạn chặn trong cùng cửa sổ sẽ bị chặn lại ngay.
            self._count[peer] = (win, 0)
            return "block_now"
        return "ok"


DEFAULT_NET = {
    "gst": 0,
    "delta": 50,
    "pre_gst": {"delay_min": 5, "delay_max": 40, "drop_permille": 0, "dup_permille": 0},
    "post_gst": {"delay_min": 5, "delay_max": 40, "dup_permille": 0},
    "outbound": {"window_ms": 10, "max_msgs": 200},
    "inbound": {"window_ms": 100, "max_msgs_per_peer": 400, "block_ms": 300},
    "partitions": [],
}


def merge_net_config(cfg):
    out = {}
    for key, default in DEFAULT_NET.items():
        value = (cfg or {}).get(key, default)
        out[key] = {**default, **value} if isinstance(default, dict) else value
    return out


class Network:
    def __init__(self, sched, rng, log, cfg, node_ids, correct_ids):
        self.sched, self.rng, self.log = sched, rng, log
        self.cfg = merge_net_config(cfg)
        self.gst, self.delta = self.cfg["gst"], self.cfg["delta"]
        out_cfg, in_cfg = self.cfg["outbound"], self.cfg["inbound"]
        self.limiters = {n: OutboundLimiter(out_cfg["window_ms"], out_cfg["max_msgs"])
                         for n in node_ids}
        self.guards = {n: PeerGuard(in_cfg["window_ms"], in_cfg["max_msgs_per_peer"],
                                    in_cfg["block_ms"]) for n in node_ids}
        self.correct = set(correct_ids)
        self.exempt = set()          # node Byzantine cố tình bỏ qua giới hạn gửi
        self.handlers = {}
        self._seq = 0
        self.stats = {"sent": 0, "delivered": 0, "dropped": 0, "duplicated": 0,
                      "rate_delayed": 0, "blocks": 0,
                      "max_latency_post_gst_correct": 0, "post_gst_correct_drops": 0,
                      "correct_blocked_by_correct_post_gst": 0}

    def register(self, node_id, handler):
        self.handlers[node_id] = handler

    # ---- gửi --------------------------------------------------------------

    def send(self, src, dst, mtype, payload, height, round=None, block_hash=None):
        raw = canonical(payload)
        self._seq += 1
        meta = {"msg": self._seq, "mtype": mtype, "height": height,
                "round": round, "hash": block_hash}
        now = self.sched.now
        self.stats["sent"] += 1
        # Mọi lần gửi đều có dòng "send", kể cả tin sau đó bị trễ, mất hay bị chặn.
        self._emit(src, "send", meta, peer=dst)
        depart = now if src in self.exempt else self.limiters[src].reserve(now)
        if depart > now:
            self.stats["rate_delayed"] += 1
            self._emit(src, "delay", meta, peer=dst, reason="rate_limit", wait=depart - now)
            self.sched.at(depart, self._transmit, src, dst, raw, meta, now)
        else:
            self._transmit(src, dst, raw, meta, now)

    def _emit(self, node, type_, meta, **extra):
        self.log.emit(self.sched.now, node, type_, meta["height"], msg=meta["msg"],
                      mtype=meta["mtype"], round=meta["round"], hash=meta["hash"], **extra)

    def _partitioned(self, src, dst, now):
        for part in self.cfg["partitions"]:
            if part["from"] <= now < part["to"]:
                side = {n: i for i, group in enumerate(part["groups"]) for n in group}
                if side.get(src) != side.get(dst):
                    return True
        return False

    def _drop(self, node, peer, meta, reason, src, dst):
        self.stats["dropped"] += 1
        # Sau GST, tin giữa hai node đúng không được mất (kể cả tin gửi trước GST nhưng
        # vì xếp hàng mà tới lượt truyền sau GST).
        if self.sched.now >= self.gst and src in self.correct and dst in self.correct:
            self.stats["post_gst_correct_drops"] += 1
        self._emit(node, "drop", meta, peer=peer, reason=reason)

    def _transmit(self, src, dst, raw, meta, submit_t):
        now = self.sched.now
        if self._partitioned(src, dst, now):
            self._drop(src, dst, meta, "partition", src, dst)
            return
        phase = self.cfg["pre_gst"] if now < self.gst else self.cfg["post_gst"]
        lost = self.rng.randrange(1000) < phase.get("drop_permille", 0)
        dup = self.rng.randrange(1000) < phase.get("dup_permille", 0)
        if lost:
            self._drop(src, dst, meta, "random_loss", src, dst)
            return
        self._schedule_delivery(src, dst, raw, meta, submit_t, phase, copy=0)
        if dup:
            self.stats["duplicated"] += 1
            self._emit(src, "duplicate", meta, peer=dst)
            self._schedule_delivery(src, dst, raw, meta, submit_t, phase, copy=1)

    def _schedule_delivery(self, src, dst, raw, meta, submit_t, phase, copy):
        now = self.sched.now
        post_max = self.cfg["post_gst"]["delay_max"]
        delay = self.rng.randint(phase["delay_min"], phase["delay_max"])
        # Partial synchrony: tin gửi lúc t đến chậm nhất tại max(t, GST) + cận đường truyền.
        arrive = min(now + delay, max(now, self.gst) + post_max)
        if arrive - now > post_max:
            self._emit(src, "delay", meta, peer=dst, reason="slow_link", wait=arrive - now)
        self.sched.at(arrive, self._deliver, src, dst, raw, meta, submit_t, copy)

    # ---- nhận -------------------------------------------------------------

    def _deliver(self, src, dst, raw, meta, submit_t, copy=0):
        now = self.sched.now
        verdict = self.guards[dst].admit(src, now)
        if verdict != "ok":
            if verdict == "block_now":
                until = self.guards[dst].blocked_until[src]
                self.stats["blocks"] += 1
                if now >= self.gst and src in self.correct and dst in self.correct:
                    self.stats["correct_blocked_by_correct_post_gst"] += 1
                self.log.emit(now, dst, "block", meta["height"], peer=src, until=until,
                              reason="inbound_rate")
                self.sched.at(until, self._unblock, dst, src, meta["height"])
            self._drop(dst, src, meta, "peer_blocked", src, dst)
            return
        self.stats["delivered"] += 1
        if src in self.correct and dst in self.correct:
            # Partial synchrony: tin gửi lúc t phải tới trước max(t, GST) + Delta.
            latency = now - max(submit_t, self.gst)
            if latency > self.stats["max_latency_post_gst_correct"]:
                self.stats["max_latency_post_gst_correct"] = latency
        self._emit(dst, "deliver", meta, peer=src, copy=copy or None)
        self.handlers[dst](src, meta["mtype"], decode(raw))

    def _unblock(self, node, peer, height):
        self.log.emit(self.sched.now, node, "unblock", height, peer=peer)
