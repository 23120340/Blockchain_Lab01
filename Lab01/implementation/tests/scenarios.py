"""Danh sách scenario end-to-end và hàm chạy dùng chung cho pytest và run_all."""
import os

from src.oracle import evaluate
from src.simulator import load_config, run_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
LOG_DIR = os.path.join(ROOT, "logs")

# (mã test, file cấu hình, kịch bản, kết quả bắt buộc theo đề)
SCENARIOS = [
    ("T1", "t1_normal", "Chạy bình thường, không lỗi",
     "Mọi node đúng finalize cùng chain và state hash"),
    ("T2", "t2_duplicate_reorder", "Thông điệp bị nhân đôi/đảo thứ tự",
     "Không đếm phiếu lặp, không finalize xung đột"),
    ("T3", "t3_invalid_signature_domain", "Chữ ký sai / sai domain",
     "Thông điệp bị từ chối, có log lý do"),
    ("T4", "t4_replay_transaction", "Transaction bị phát lại / gửi lặp",
     "Áp dụng tối đa một lần"),
    ("T5", "t5_drop_delay_before_gst", "Mất/trễ tin trước synchrony",
     "Safety giữ; không double finalization ở cùng height"),
    ("T6", "t6_silent_proposer", "Proposer im lặng/crash",
     "Timeout kích hoạt đổi round, chain tiếp tục"),
    ("T7", "t7_byzantine_equivocation", "f validator Byzantine equivocate",
     "Không finalize xung đột"),
    ("X1", "x1_rate_limit_block", "(bổ sung) Giới hạn gửi và chặn peer quá tải",
     "Tin xếp hàng chứ không mất; peer gửi dồn bị chặn rồi mở lại"),
    ("X2", "x2_invalid_block_proposer", "(bổ sung) Proposer đề xuất block sai",
     "Block bị bác, state không đổi, chain tiếp tục"),
    ("X3", "x3_withheld_commit", "(bổ sung) Byzantine giấu commit để phá lock",
     "Node đã lock không đổi phiếu; không finalize xung đột"),
]

# Chạy lại T5, T7 và X3 với nhiều seed: safety là tính chất phải đúng với MỌI lịch mạng.
SWEEP = {"t5_drop_delay_before_gst": list(range(1, 21)),
         "t7_byzantine_equivocation": list(range(1, 21)),
         "x3_withheld_commit": list(range(1, 21))}

SAFETY_CHECKS = ("no_conflicting_finalization", "finalized_history_immutable",
                 "commit_has_quorum_of_distinct_validators", "tx_applied_at_most_once",
                 "one_vote_per_height_round_phase", "lock_rule_respected",
                 "body_only_after_header_accepted", "same_chain_and_state_at_common_height")


def config_path(name):
    return os.path.join(CONFIG_DIR, name + ".json")


def run_config(name, seed=None):
    cfg = load_config(config_path(name))
    if seed is not None:
        cfg["seed"] = seed
    log_bytes, summary = run_scenario(cfg)
    return cfg, log_bytes, summary, evaluate(cfg, log_bytes, summary)


def failed(verdict):
    return [f"{c['name']}: {c['detail']}" for c in verdict["checks"] if not c["ok"]]
