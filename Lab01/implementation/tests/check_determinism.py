"""T8: chạy cùng scenario hai lần ở HAI PROCESS RIÊNG rồi so bytes của log thật.

    python -m tests.check_determinism                 # mọi scenario
    python -m tests.check_determinism t5_drop_delay_before_gst

So sánh nguyên văn events.log (không bỏ trường nào), summary.json và state hash cuối.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

from tests.scenarios import LOG_DIR, ROOT, SCENARIOS, config_path


def _run_process(name, out_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONHASHSEED="random")
    proc = subprocess.run(
        [sys.executable, "-m", "src.main", "--config", config_path(name), "--output", out_dir],
        cwd=ROOT, env=env, capture_output=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    with open(os.path.join(out_dir, "events.log"), "rb") as fh:
        log = fh.read()
    with open(os.path.join(out_dir, "summary.json"), "rb") as fh:
        summary = fh.read()
    return log, summary


def compare_two_processes(name, work_dir):
    run1, run2 = (os.path.join(work_dir, name, f"run{i}") for i in (1, 2))
    log1, sum1 = _run_process(name, run1)
    log2, sum2 = _run_process(name, run2)
    s1, s2 = json.loads(sum1), json.loads(sum2)
    return {
        "scenario": name,
        "log_bytes": len(log1),
        "log_sha256_run1": hashlib.sha256(log1).hexdigest(),
        "log_sha256_run2": hashlib.sha256(log2).hexdigest(),
        "identical_log_bytes": log1 == log2,
        "identical_summary_bytes": sum1 == sum2,
        "state_hash_run1": s1["final_state_hash"],
        "state_hash_run2": s2["final_state_hash"],
        "identical_state_hash": s1["final_state_hash"] is not None
        and s1["final_state_hash"] == s2["final_state_hash"],
    }


KEEP = ("t5_drop_delay_before_gst", "t7_byzantine_equivocation")


def run(names=None, work_dir=None, keep=KEEP):
    """So sánh mọi scenario; chỉ giữ lại hai bộ log run1/run2 của các scenario trong
    `keep` làm bằng chứng (các scenario khác đã có log ở logs/<scenario>/)."""
    full = not names
    names = names or [s[1] for s in SCENARIOS]
    work_dir = work_dir or os.path.join(LOG_DIR, "t8_determinism")
    results = []
    for name in names:
        # Chỉ dọn thư mục của scenario đang so; bằng chứng của scenario khác giữ nguyên.
        shutil.rmtree(os.path.join(work_dir, name), ignore_errors=True)
        results.append(compare_two_processes(name, work_dir))
        if name not in keep:
            shutil.rmtree(os.path.join(work_dir, name), ignore_errors=True)
    ok = all(r["identical_log_bytes"] and r["identical_summary_bytes"]
             and r["identical_state_hash"] for r in results)
    if full:
        # result.json là kết quả của lần so TOÀN BỘ scenario; lần chạy lẻ không ghi đè.
        with open(os.path.join(work_dir, "result.json"), "wb") as fh:
            fh.write(json.dumps({"pass": ok, "runs": results}, indent=2, sort_keys=True)
                     .encode("utf-8") + b"\n")
    return ok, results


def main():
    ok, results = run(sys.argv[1:] or None)
    for r in results:
        same = r["identical_log_bytes"] and r["identical_state_hash"]
        print(f"[{'PASS' if same else 'FAIL'}] {r['scenario']}: {r['log_bytes']} bytes, "
              f"sha256 {r['log_sha256_run1'][:16]}… == {r['log_sha256_run2'][:16]}…, "
              f"state {str(r['state_hash_run1'])[:16]}…")
    print("T8:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    sys.exit(main())
