"""CLI: python -m src.main --config config/t1_normal.json --output logs/t1"""
import argparse
import sys

from .oracle import evaluate
from .simulator import ConfigError, load_config, run_scenario, write_outputs


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lab 01 - mô phỏng blockchain Layer 1")
    parser.add_argument("--config", required=True, help="file cấu hình scenario (JSON)")
    parser.add_argument("--output", required=True, help="thư mục ghi events.log, summary.json")
    parser.add_argument("--seed", type=int, help="ghi đè seed trong cấu hình")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.seed is not None:
            cfg["seed"] = args.seed
        log_bytes, summary = run_scenario(cfg)
    except ConfigError as exc:
        print(f"Lỗi cấu hình: {exc}", file=sys.stderr)
        return 2
    verdict = evaluate(cfg, log_bytes, summary)
    write_outputs(args.output, log_bytes, summary, verdict)
    print(f"scenario        : {summary['scenario']} (seed {summary['seed']})")
    print(f"validators      : n={summary['n']} f={summary['f']} quorum={summary['quorum']}")
    print(f"thời gian mô phỏng: {summary['end_time']} ms, {summary['log_lines']} dòng log")
    print(f"height finalize : {verdict['finalized_heights']}")
    print(f"state hash cuối : {summary['final_state_hash']}")
    print(f"sha256(log)     : {summary['log_sha256']}")
    for item in verdict["checks"]:
        print(f"  [{'PASS' if item['ok'] else 'FAIL'}] {item['name']}  {item['detail']}")
    print("KẾT QUẢ:", "PASS" if verdict["pass"] else "FAIL")
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    sys.exit(main())
