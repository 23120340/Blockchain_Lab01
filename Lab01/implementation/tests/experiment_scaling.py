"""Thí nghiệm phụ: số thông điệp và thời gian mỗi height khi tăng số validator.

    python -m tests.experiment_scaling

Chạy lại kịch bản T1 (cùng seed, mạng, workload) với n = 10, 13, 16, 19, 22 validator,
kiểm tra bằng oracle như mọi scenario, rồi đếm số lần gửi theo loại thông điệp. Kết quả
ghi vào logs/experiment_scaling.json. Đây không phải test bắt buộc; run_all không gọi file này.
"""
import json
import os
from collections import Counter

from src.oracle import evaluate
from src.simulator import load_config, run_scenario
from tests.scenarios import LOG_DIR, config_path, failed

SIZES = [10, 13, 16, 19, 22]


def run(n):
    cfg = load_config(config_path("t1_normal"))
    cfg.pop("genesis")                  # genesis dựng lại từ số validator
    cfg["validators"] = n
    cfg["name"] = f"t1_normal_n{n}"
    log_bytes, summary = run_scenario(cfg)
    verdict = evaluate(cfg, log_bytes, summary)
    sends, finals = Counter(), []
    for line in log_bytes.decode("utf-8").splitlines():
        ev = json.loads(line)
        if ev["type"] == "send":
            sends[ev["mtype"]] += 1
        elif ev["type"] == "finalize" and ev["node"] == "v0":
            finals.append(ev["t"])
    heights = summary["target_height"]
    reached = finals[:heights]
    return {
        "n": n, "f": (n - 1) // 3, "quorum": summary["quorum"], "pass": verdict["pass"],
        "failed_checks": failed(verdict),
        "sends_total": sum(sends.values()), "sends_by_type": dict(sorted(sends.items())),
        "votes_per_height": round(sends["VOTE"] / heights, 1),
        "votes_per_height_theory": 2 * n * (n - 1),
        "ms_per_height": round(reached[-1] / len(reached), 1),
    }


def main():
    rows = [run(n) for n in SIZES]
    with open(os.path.join(LOG_DIR, "experiment_scaling.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"{'n':>3} {'f':>2} {'q':>3} {'đạt':>4} {'tin gửi':>8} {'phiếu/height':>13} "
          f"{'lý thuyết':>10} {'ms/height':>10}")
    for r in rows:
        print(f"{r['n']:>3} {r['f']:>2} {r['quorum']:>3} {'có' if r['pass'] else 'KHÔNG':>4} "
              f"{r['sends_total']:>8} {r['votes_per_height']:>13} "
              f"{r['votes_per_height_theory']:>10} {r['ms_per_height']:>10}")
    return 0 if all(r["pass"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
