"""Kiểm tra độ nhạy của bộ test: cố tình làm hỏng giao thức rồi xem oracle có bắt được không.

Một phép thử luôn đạt trông y hệt một phép thử tốt. Ở đây node ĐÚNG bị sửa (chỉ trong
bộ nhớ, trong lúc test) để vi phạm một luật; scenario tương ứng phải sinh ra finalize
xung đột và oracle phải báo trượt. Mã nguồn trong src/ không bị đụng tới.
"""
import contextlib

from src.byzantine import ByzantineNode
from src.node import PROPOSE_STEP, Node
from tests.scenarios import run_config


@contextlib.contextmanager
def quorum_off_by_one():
    """Node đúng dùng quorum 2f thay vì 2f + 1."""
    original = Node.__init__

    def patched(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if not isinstance(self, ByzantineNode):
            self.quorum = 2 * self.f

    Node.__init__ = patched
    try:
        yield
    finally:
        Node.__init__ = original


@contextlib.contextmanager
def lock_ignored():
    """Node đúng quên lock khi prevote (vi phạm luật 5 mục 6.1)."""
    original = Node._step_once

    def patched(self):
        if isinstance(self, ByzantineNode) or self.step != PROPOSE_STEP:
            return original(self)
        saved, self.locked_hash = self.locked_hash, None
        try:
            return original(self)
        finally:
            if self.locked_hash is None:
                self.locked_hash = saved

    Node._step_once = patched
    try:
        yield
    finally:
        Node._step_once = original


# (tên, đột biến, scenario, phép kiểm của oracle phải trượt)
MUTATIONS = [
    ("quorum 2f thay vì 2f+1", quorum_off_by_one, "t7_byzantine_equivocation",
     "no_conflicting_finalization"),
    ("bỏ luật lock khi prevote", lock_ignored, "x3_withheld_commit",
     "no_conflicting_finalization"),
]


def run_mutations(seeds=(1, 2, 3)):
    rows = []
    for label, mutation, scenario, must_fail in MUTATIONS:
        caught = 0
        for seed in seeds:
            with mutation():
                _, _, _, verdict = run_config(scenario, seed)
            checks = {c["name"]: c["ok"] for c in verdict["checks"]}
            caught += 0 if checks[must_fail] else 1
        _, _, _, clean = run_config(scenario, seeds[0])
        clean_ok = {c["name"]: c["ok"] for c in clean["checks"]}[must_fail]
        rows.append({"mutation": label, "scenario": scenario, "check": must_fail,
                     "seeds": len(seeds), "caught": caught, "clean_passes": clean_ok,
                     "pass": caught == len(seeds) and clean_ok})
    return rows
