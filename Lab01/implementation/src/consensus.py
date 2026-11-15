"""Thành phần thuần của consensus: quorum, chọn proposer, vote pool."""


def fault_bound(n) -> int:
    return (n - 1) // 3


def quorum_size(n) -> int:
    return 2 * fault_bound(n) + 1


def proposer_for(validators, height, round_) -> str:
    """Xoay vòng xác định theo (height + round) trên danh sách validator đã sắp."""
    return validators[(height + round_) % len(validators)]


class VotePool:
    """Phiếu của MỘT height. Mỗi validator được tính tối đa một phiếu cho mỗi
    (round, phase): phiếu đầu tiên hợp lệ được giữ, phiếu lặp bị bỏ qua, phiếu
    thứ hai khác nội dung bị ghi nhận là equivocation và không được tính."""

    def __init__(self):
        self._votes = {}  # (round, phase) -> {validator: vote}

    def add(self, vote) -> str:
        slot = self._votes.setdefault((vote["round"], vote["phase"]), {})
        existing = slot.get(vote["validator"])
        if existing is None:
            slot[vote["validator"]] = vote
            return "added"
        if existing["block_hash"] == vote["block_hash"]:
            return "duplicate"
        return "equivocation"

    def get(self, round_, phase, validator):
        return self._votes.get((round_, phase), {}).get(validator)

    def count(self, round_, phase, block_hash) -> int:
        return sum(1 for v in self._votes.get((round_, phase), {}).values()
                   if v["block_hash"] == block_hash)

    def total(self, round_, phase) -> int:
        return len(self._votes.get((round_, phase), {}))

    def votes_for(self, round_, phase, block_hash):
        slot = self._votes.get((round_, phase), {})
        return [slot[v] for v in sorted(slot) if slot[v]["block_hash"] == block_hash]

    def quorums(self, phase, quorum):
        """Mọi (round, block_hash) đã đủ quorum cho `phase`, theo thứ tự cố định."""
        out = []
        for (round_, ph) in sorted(self._votes):
            if ph != phase:
                continue
            tally = {}
            for vote in self._votes[(round_, ph)].values():
                tally[vote["block_hash"]] = tally.get(vote["block_hash"], 0) + 1
            out.extend((round_, h) for h in sorted(tally) if tally[h] >= quorum)
        return out

    def voters_in_round(self, round_):
        voters = set()
        for (r, _), slot in self._votes.items():
            if r == round_:
                voters.update(slot)
        return voters

    def rounds(self):
        return sorted({r for (r, _) in self._votes})

    def voters_for_hash(self, block_hash):
        return sorted({v["validator"] for slot in self._votes.values()
                       for v in slot.values() if v["block_hash"] == block_hash})
