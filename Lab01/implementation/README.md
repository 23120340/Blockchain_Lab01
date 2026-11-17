# Lab 01 — Blockchain Layer 1 tối thiểu trong mạng mô phỏng

Một mạng blockchain nhỏ chạy hoàn toàn trong simulator: 10 validator, mỗi node có ledger,
state, mempool, vote pool và lock riêng; các node chỉ trao đổi qua mạng mô phỏng (trễ, mất,
nhân đôi, đảo thứ tự, giới hạn tốc độ) và đồng thuận hai pha `PREVOTE` / `PRECOMMIT`.
Chạy lại cùng cấu hình cho log giống từng byte và cùng state hash cuối.

## 1. Yêu cầu

| Thành phần | Phiên bản đã dùng để kiểm chứng |
|---|---|
| Python | 3.12.10 (cần 3.10 trở lên) |
| cryptography (Ed25519) | 50.0.2 |
| pytest | 9.2.0 |
| Hệ điều hành | Windows 11 |

Không có bước build.

## 2. Cài đặt

Đứng tại thư mục gốc của bài nộp (thư mục chứa file này):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install cryptography==50.0.2 pytest==9.2.0
```

Linux/macOS: `python3 -m venv .venv && .venv/bin/python -m pip install cryptography==50.0.2 pytest==9.2.0`,
rồi thay `.\.venv\Scripts\python.exe` bằng `.venv/bin/python` trong các lệnh dưới.

## 3. Chạy simulator

```powershell
.\.venv\Scripts\python.exe -m src.main --config config/t1_normal.json --output logs/t1_normal
```

Lệnh in tóm tắt, từng phép kiểm của oracle và `KẾT QUẢ: PASS/FAIL` (mã thoát 0/1), đồng thời
ghi ba file vào thư mục `--output`:

| File | Nội dung |
|---|---|
| `events.log` | Mỗi dòng một sự kiện JSON: `t` (ms mô phỏng), `node`, `type`, `height`, thêm `round`, `hash`, `reason`, `peer`… |
| `summary.json` | Height, tip, state hash của từng node; state cuối (`final_state`, `final_state_hash`) lấy tại height chung cao nhất mà mọi node đúng đã finalize; thống kê mạng; `sha256` của log |
| `verdict.json` | Kết quả từng phép kiểm của oracle và số lần xuất hiện mỗi loại sự kiện |

Tùy chọn `--seed N` ghi đè seed trong cấu hình. Sinh lại genesis: `python -m src.genesis`.

## 4. Chạy kiểm thử

Một entry point cho tất cả:

```powershell
.\.venv\Scripts\python.exe -m tests.run_all
```

Lệnh này lần lượt chạy (khoảng 1–2 phút):

1. 84 unit test (`tests/unit`): chữ ký/domain, luật state, đếm phiếu, kiểm tra block, locking, mạng,
   và chính oracle (phải trượt khi log có vi phạm).
2. End-to-end T1–T7 và ba kịch bản bổ sung X1–X3; ghi log vào `logs/<scenario>/`.
3. Quét 20 seed cho T5, T7, X3 (safety phải đúng với mọi lịch mạng).
4. T8: mỗi scenario chạy hai lần ở hai process riêng, so **bytes** của `events.log` và state hash.
5. Độ nhạy: cố tình làm hỏng node đúng (quorum thiếu 1, bỏ luật lock); oracle phải báo finalize xung đột.

Kết quả tổng hợp nằm ở `logs/RESULTS.md` và `logs/results.json`. Mã thoát 0 khi tất cả đạt.

Các lệnh riêng lẻ:

```powershell
.\.venv\Scripts\python.exe -m tests.check_determinism                       # chỉ T8, mọi scenario
.\.venv\Scripts\python.exe -m tests.check_determinism t5_drop_delay_before_gst   # chỉ một scenario
.\.venv\Scripts\python.exe -m pytest tests -q                               # 114 test qua pytest
.\.venv\Scripts\python.exe -m pytest tests/unit -q                          # chỉ unit test
.\.venv\Scripts\python.exe -m tests.experiment_scaling                      # thí nghiệm n = 10…22 validator
```

`tests.experiment_scaling` không thuộc bộ test bắt buộc: nó chạy lại T1 với 10, 13, 16, 19, 22
validator, kiểm bằng oracle và ghi số thông điệp, thời gian mỗi height vào `logs/experiment_scaling.json`.

## 5. Các scenario

| Mã | File trong `config/` | Lỗi được tiêm |
|---|---|---|
| T1 | `t1_normal.json` | Không có |
| T2 | `t2_duplicate_reorder.json` | Nhân đôi 30% thông điệp, trễ 1–45 ms |
| T3 | `t3_invalid_signature_domain.json` | Client và validator `v3` gửi chữ ký sai, sai domain, sai chain, mạo danh |
| T4 | `t4_replay_transaction.json` | Client gửi lại transaction; `v7` phát lại qua mạng; proposer `v2` nhét transaction cũ vào block |
| T5 | `t5_drop_delay_before_gst.json` | Trước GST = 3000 ms: mất 5%, trễ tới 80 ms, cô lập `v8`, `v9` trong 2500 ms |
| T6 | `t6_silent_proposer.json` | `v1` im lặng từ đầu, `v5` crash lúc 600 ms |
| T7 | `t7_byzantine_equivocation.json` | `v1`, `v4`, `v7` (đúng f = 3) ký phiếu xung đột và đề xuất hai block |
| T8 | mọi file ở trên | Chạy lại cùng seed ở hai process |
| X1 | `x1_rate_limit_block.json` | Giới hạn gửi 12 tin/10 ms; `v9` gửi dồn 600 tin vào `v0` |
| X2 | `x2_invalid_block_proposer.json` | Proposer ghi state hash sai / ghi vào khóa người khác |
| X3 | `x3_withheld_commit.json` | Byzantine giấu commit để dụ node đã lock đổi phiếu |

Trường chính của file cấu hình: `seed`, `target_height`, `max_time`, `network` (`gst`, `delta`,
`pre_gst`, `post_gst`, `outbound`, `inbound`, `partitions`), `byzantine` (node lỗi và kiểu lỗi),
`workload` (transaction của client), `expect` (kỳ vọng để oracle đối chiếu).
Số validator phải có dạng 3f + 1 và ≥ 8 (10, 13, 16…); cấu hình khác bị từ chối.

## 6. Cấu trúc thư mục

```text
src/
  encoding.py    canonical byte encoding (JSON sắp khóa, cấm số thực)
  crypto.py      Ed25519, SHA-256, domain separation, key fixture
  models.py      transaction, header, vote, proposal, certificate
  execution.py   state key-value + nonce, luật sở hữu, thực thi block
  scheduler.py   event queue thời gian mô phỏng, log JSONL
  network.py     mạng mô phỏng: delay/drop/duplicate, rate limit, block/unblock
  consensus.py   quorum, chọn proposer, vote pool
  node.py        node đúng: handshake header/body, hai pha, lock, đồng bộ
  byzantine.py   node Byzantine cho fault injection
  simulator.py   dựng scenario từ cấu hình, bơm workload, tóm tắt
  oracle.py      test oracle chỉ đọc log
  genesis.py     sinh config/genesis.json
  main.py        CLI
tests/
  unit/          unit test
  test_e2e.py, test_mutations.py   end-to-end qua pytest
  scenarios.py   danh sách scenario
  mutations.py   đột biến để thử độ nhạy của oracle
  check_determinism.py   T8
  run_all.py     entry point duy nhất
config/          genesis.json và cấu hình từng scenario
logs/            log, summary, verdict thật của lần chạy gần nhất; RESULTS.md
```

## 7. Lưu ý

- Khóa của validator và tài khoản là **key fixture** suy ra từ tên, chỉ để kiểm thử tái lập
  được; seed của simulator không phải nguồn ngẫu nhiên mật mã.
- Thời gian trong log là thời gian mô phỏng (ms); không có wall-clock, PID hay đường dẫn.
- `logs/` tái tạo được hoàn toàn bằng `python -m tests.run_all`.
