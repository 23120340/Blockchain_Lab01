"""MỘT entry point cho toàn bộ kiểm thử:  python -m tests.run_all

  1. Unit tests (pytest tests/unit)
  2. End-to-end T1-T7 + X1, X2: chạy, ghi logs/<scenario>/, oracle đánh giá
  3. Quét nhiều seed cho T5, T7, X3 (safety + tiến triển)
  4. T8: mỗi scenario chạy hai lần ở hai process, so bytes của log và state hash
  5. Độ nhạy: cố tình làm hỏng node đúng, oracle phải báo finalize xung đột
  6. Ghi logs/RESULTS.md và logs/results.json

Mã thoát 0 khi mọi thứ đạt, 1 khi có bất kỳ mục nào trượt.
"""
import json
import os
import subprocess
import sys

from src.simulator import write_outputs
from tests import check_determinism
from tests.mutations import run_mutations
from tests.scenarios import (LOG_DIR, ROOT, SAFETY_CHECKS, SCENARIOS, SWEEP, failed,
                             run_config)


def run_unit_tests():
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/unit", "-q", "-p",
                           "no:cacheprovider"], cwd=ROOT, capture_output=True,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    text = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    with open(os.path.join(LOG_DIR, "unit_tests.txt"), "wb") as fh:
        fh.write(text.replace("\r\n", "\n").encode("utf-8"))
    tail = [line for line in text.splitlines() if line.strip()][-1]
    return proc.returncode == 0, tail


def run_scenarios():
    rows = []
    for test_id, name, scenario, required in SCENARIOS:
        _, log_bytes, summary, verdict = run_config(name)
        write_outputs(os.path.join(LOG_DIR, name), log_bytes, summary, verdict)
        rows.append({"id": test_id, "name": name, "scenario": scenario, "required": required,
                     "pass": verdict["pass"], "failed": failed(verdict),
                     "heights": summary["min_correct_height"], "target": summary["target_height"],
                     "end_time": summary["end_time"], "log_lines": summary["log_lines"],
                     "state_hash": summary["final_state_hash"], "counts": verdict["counts"],
                     "network": summary["network"]})
    return rows


def run_sweep():
    out = []
    for name, seeds in SWEEP.items():
        for seed in seeds:
            _, _, summary, verdict = run_config(name, seed)
            checks = {c["name"]: c["ok"] for c in verdict["checks"]}
            out.append({"scenario": name, "seed": seed,
                        "safety": all(checks[c] for c in SAFETY_CHECKS),
                        "progress": checks.get("progress_to_target_height", False),
                        "min_height": summary["min_correct_height"],
                        "end_time": summary["end_time"],
                        "finalize_pre_gst": verdict["counts"].get("finalize_pre_gst", 0),
                        "equivocation": verdict["counts"].get("equivocation", 0)})
    with open(os.path.join(LOG_DIR, "seed_sweep.json"), "wb") as fh:
        fh.write(json.dumps(out, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return out


EVIDENCE = {
    "T1": ["finalize", "timeout", "drop"],
    "T2": ["duplicate", "ignore:duplicate_vote", "equivocation"],
    "T3": ["reject:bad_signature", "reject:wrong_domain", "reject:wrong_chain",
           "reject:unknown_validator"],
    "T4": ["reject:stale_nonce", "ignore:duplicate_tx", "block_invalid:invalid_tx:replayed_nonce"],
    "T5": ["drop", "delay:slow_link", "finalize_pre_gst", "commit_cert"],
    "T6": ["crash", "timeout:propose", "round_start_after_round0"],
    "T7": ["byz_equivocate_proposal", "byz_equivocate_vote", "equivocation"],
    "X1": ["delay:rate_limit", "block", "unblock", "drop:peer_blocked"],
    "X2": ["byz_invalid_block", "block_invalid:state_hash_mismatch",
           "block_invalid:invalid_tx:not_owner"],
    "X3": ["byz_withhold_commit", "commit_cert", "lock", "round_start_after_round0"],
}


def write_results(unit_ok, unit_tail, rows, sweep, t8_ok, t8, mutations):
    lines = ["# Kết quả kiểm thử (sinh tự động bởi `python -m tests.run_all`)", "",
             f"- Unit tests: **{'PASS' if unit_ok else 'FAIL'}** — `{unit_tail.strip('= ')}`",
             "", "| Test | Kịch bản | Kết quả bắt buộc | Kết quả | Height | Thời gian mô phỏng | Bằng chứng trong log |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        evidence = ", ".join(f"{k}={r['counts'].get(k, 0)}" for k in EVIDENCE[r["id"]])
        lines.append(f"| {r['id']} | {r['scenario']} | {r['required']} | "
                     f"**{'PASS' if r['pass'] else 'FAIL'}** | {r['heights']}/{r['target']} | "
                     f"{r['end_time']} ms | {evidence} |")
    lines.append(f"| T8 | Chạy lại cùng seed/config hai lần | Log giống từng byte, cùng state hash | "
                 f"**{'PASS' if t8_ok else 'FAIL'}** | — | — | "
                 f"{sum(r['identical_log_bytes'] for r in t8)}/{len(t8)} scenario giống từng byte |")
    lines += ["", "## Quét seed (safety phải đúng với mọi lịch mạng)", "",
              "| Scenario | Số seed | Safety đạt | Tới target | Finalize trước GST (tổng) | Equivocation bị phát hiện (tổng) |",
              "|---|---|---|---|---|---|"]
    for name in SWEEP:
        part = [s for s in sweep if s["scenario"] == name]
        lines.append(f"| {name} | {len(part)} | {sum(s['safety'] for s in part)}/{len(part)} | "
                     f"{sum(s['progress'] for s in part)}/{len(part)} | "
                     f"{sum(s['finalize_pre_gst'] for s in part)} | "
                     f"{sum(s['equivocation'] for s in part)} |")
    lines += ["", "## T8 — so sánh hai process", "",
              "| Scenario | Bytes log | sha256(log) lần 1 = lần 2 | State hash cuối |", "|---|---|---|---|"]
    for r in t8:
        lines.append(f"| {r['scenario']} | {r['log_bytes']} | "
                     f"{'giống' if r['identical_log_bytes'] else 'KHÁC'} "
                     f"(`{r['log_sha256_run1'][:16]}…`) | `{str(r['state_hash_run1'])[:16]}…` |")
    lines += ["", "## Độ nhạy của bộ test (cố tình làm hỏng node đúng)", "",
              "| Đột biến | Scenario | Phép kiểm phải trượt | Bị bắt | Bản gốc |", "|---|---|---|---|---|"]
    for m in mutations:
        lines.append(f"| {m['mutation']} | {m['scenario']} | {m['check']} | "
                     f"{m['caught']}/{m['seeds']} seed | {'đạt' if m['clean_passes'] else 'TRƯỢT'} |")
    bad = [f"- {r['id']}: {'; '.join(r['failed'])}" for r in rows if not r["pass"]]
    if bad:
        lines += ["", "## Mục trượt", ""] + bad
    with open(os.path.join(LOG_DIR, "RESULTS.md"), "wb") as fh:
        fh.write(("\n".join(lines) + "\n").encode("utf-8"))
    with open(os.path.join(LOG_DIR, "results.json"), "wb") as fh:
        fh.write(json.dumps({"unit": {"pass": unit_ok, "summary": unit_tail}, "scenarios": rows,
                             "sweep": sweep, "t8": {"pass": t8_ok, "runs": t8},
                             "mutations": mutations},
                            indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n")


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    print("[1/5] Unit tests ...")
    unit_ok, unit_tail = run_unit_tests()
    print(f"      {'PASS' if unit_ok else 'FAIL'}  {unit_tail}")
    print("[2/5] End-to-end ...")
    rows = run_scenarios()
    for r in rows:
        print(f"      [{'PASS' if r['pass'] else 'FAIL'}] {r['id']} {r['name']}: "
              f"height {r['heights']}/{r['target']}, {r['end_time']} ms, {r['log_lines']} dòng log")
        for item in r["failed"]:
            print(f"             - {item}")
    print("[3/5] Quét seed T5, T7, X3 ...")
    sweep = run_sweep()
    sweep_ok = all(s["safety"] and s["progress"] for s in sweep)
    print(f"      {'PASS' if sweep_ok else 'FAIL'}  {sum(s['safety'] for s in sweep)}/{len(sweep)} "
          f"lượt giữ safety, {sum(s['progress'] for s in sweep)}/{len(sweep)} lượt tới target")
    print("[4/5] T8 - hai process, so bytes ...")
    t8_ok, t8 = check_determinism.run()
    print(f"      [{'PASS' if t8_ok else 'FAIL'}] T8: "
          f"{sum(r['identical_log_bytes'] for r in t8)}/{len(t8)} scenario giống từng byte")
    print("[5/5] Độ nhạy của bộ test (đột biến) ...")
    mutations = run_mutations()
    for m in mutations:
        print(f"      [{'PASS' if m['pass'] else 'FAIL'}] {m['mutation']} trên {m['scenario']}: "
              f"oracle bắt được {m['caught']}/{m['seeds']} seed")
    write_results(unit_ok, unit_tail, rows, sweep, t8_ok, t8, mutations)
    ok = (unit_ok and all(r["pass"] for r in rows) and sweep_ok and t8_ok
          and all(m["pass"] for m in mutations))
    print("TỔNG KẾT:", "PASS" if ok else "FAIL", "- chi tiết: logs/RESULTS.md")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    sys.exit(main())
