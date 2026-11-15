# Bàn giao cho Claude — Lab 01 Blockchain

## 1. Nhiệm vụ của bạn

Bạn là Claude, nhận nhiệm vụ **triển khai hoàn chỉnh Lab 01**, chạy kiểm thử, lưu bằng chứng và chuẩn bị bộ bài nộp. Hãy bắt đầu bằng việc đọc tài liệu, sau đó thực hiện từng mốc bên dưới. Không dừng ở việc giải thích đề hoặc đưa ra kế hoạch.

Người dùng yêu cầu Codex chuẩn bị file bàn giao này và để Claude làm phần triển khai. Workspace là `D:\repos\Blockchain_Lab01\` (file này nằm ở gốc). Khi dựng workspace ngày 14/11/2026, `Lab01/` chỉ có hai PDF của đề (chép từ `Downloads`, bản gốc giữ nguyên); chưa có simulator hoặc kết quả kiểm thử. Các lệnh ở mục 7 là giao diện mục tiêu, chưa phải chương trình đã chạy được. Khi bắt đầu, kiểm tra lại workspace để tiếp tục từ những thay đổi mới nếu có.

Giao tiếp, README và phần giải thích ưu tiên tiếng Việt. Code và tên định danh có thể dùng tiếng Anh.

## 2. Goal chính

> Xây dựng một blockchain Layer 1 tối thiểu chạy trong mạng mô phỏng không ổn định. Mỗi node có ledger, state và consensus view độc lập; tự xác minh thông điệp, thực thi giao dịch và đồng thuận hai pha. Các node đúng không bao giờ finalize hai block khác nhau ở cùng height, tiếp tục tiến triển sau khi mạng ổn định và tái chạy cùng cấu hình cho log giống từng byte cùng state hash cuối. Hoàn thành unit tests, T1–T8, README, báo cáo và bộ bài nộp đúng đề.

Đây là goal giao cho Claude, **chưa phải kết quả đã hoàn thành**. Nếu môi trường có tính năng quản lý goal/task, dùng nội dung trên làm mục tiêu và các mốc ở mục 8 làm danh sách công việc. Nếu không, theo dõi bằng checklist ngay trong file này.

## 3. Đọc gì và ưu tiên nguồn nào?

Đường dẫn tính từ thư mục gốc workspace chứa file này:

1. [Lab01/Lab01.pdf](Lab01/Lab01.pdf): **đề chính thức, 5 trang**. Đọc toàn bộ, đặc biệt mục 6.1 về locking, mục 9 về T1–T8 và mục 10 về bài nộp.
2. [Lab01/Lab01-presentation.pdf](Lab01/Lab01-presentation.pdf): **slide bài giảng, 21 trang**, về kiến trúc node, state commitment, các chế độ đồng bộ và đánh đổi. Đây là kiến thức nền, **không thêm yêu cầu chấm điểm nào**; các chủ đề slide nhắc tới như Merkle Patricia Trie, receipts, RPC, indexing, WAL/crash recovery, reorg đều nằm ngoài phạm vi bắt buộc.

Bản bàn giao ban đầu có nhắc `Lab01/HUONG_DAN_LAB01_A_Z.md`, nhưng file đó **không tồn tại** trên máy (đã tìm trong `Downloads`, `D:\repos`, `Documents`, `Desktop`). File này cùng đề chính thức là đủ để triển khai; không đi tìm hay dựng lại tài liệu hướng dẫn đó.

Khi có khác biệt, đề chính thức quyết định yêu cầu cần đáp ứng. Python, Ed25519, SHA-256, nonce, full mesh và cấu trúc module trong file này là lựa chọn triển khai; không được mô tả chúng thành công nghệ bắt buộc của đề.

## 4. Lab này thực sự làm gì?

Tự xây một mạng blockchain nhỏ trong simulator: người dùng ký yêu cầu cập nhật dữ liệu của mình; node kiểm tra giao dịch; proposer đề xuất block; các validator xác minh block rồi bỏ phiếu `PREVOTE` và `PRECOMMIT`; đủ bằng chứng đồng thuận thì mỗi node tự finalize và cập nhật state.

Ví dụ, Alice cập nhật `Alice/message = hello`, Bob cập nhật `Bob/message = hi`. Sau khi finalize, mọi node đúng phải thống nhất thứ tự block và commitment của state chứa hai cập nhật này.

Luồng chính:

```text
Signed transaction -> mempool -> proposed header -> header accepted
-> request/receive body -> validate + execute on candidate state
-> PREVOTE -> quorum + lock -> PRECOMMIT -> quorum
-> finalize -> append ledger + commit state + log
```

Trọng tâm là authenticated data, truyền tin, BFT consensus và deterministic execution. Đề không yêu cầu gas, phí hoặc thực thi song song. Không tự mở rộng sang EVM, giao diện web, triển khai blockchain công khai hay các hệ thống RPC/indexing phức tạp trước khi hoàn thành yêu cầu chính. Merkle tree là tùy chọn; hash của state được mã hóa xác định là đủ.

## 5. Các yêu cầu phải triển khai

### 5.1. Node, fault model và mạng

- Validator set và public keys cố định trong một run; `n = 3f + 1`, tối đa `f` validator Byzantine.
- Simulator hỗ trợ số node cấu hình được, ít nhất 8. **Chọn mặc định 10 validator: `f = 3`, quorum `2f + 1 = 7`** để đồng thời thỏa hai điều kiện. Không chọn 8 validator rồi làm tròn `f`. Số validator hợp lệ là `3f + 1` và ≥ 8, tức 10, 13, 16…; cấu hình có số validator khác phải bị từ chối kèm thông báo lỗi, không tự làm tròn.
- Hành vi Byzantine theo mục 3 của đề: im lặng, gửi lặp, vote xung đột, đề xuất block sai, phát lại thông điệp đã thấy. Mỗi hành vi phải có ít nhất một kiểm thử (unit hoặc end-to-end) thực sự tiêm lỗi đó.
- Mỗi node có ledger, state, mempool, vote pool và lock riêng. Không dùng chung mutable state giữa các node; không có authority trung tâm quyết định block thắng.
- Mọi trao đổi giữa node đi qua simulated network; simulator chỉ chuyển thông điệp, lên lịch và tạo lỗi. Test oracle chỉ quan sát, không chỉ đạo quyết định của node.
- Mạng hỗ trợ delay, duplicate, reorder, drop; giới hạn outbound rate và tạm block/unblock peer quá tải.
- **Chỉ gửi body cho receiver sau khi receiver chấp nhận header tương ứng.** Có handshake/request rõ ràng; gửi header trước theo thứ tự gọi hàm là chưa đủ khi mạng reorder/drop.
- Partial synchrony: trước GST có thể mất/trễ tin; sau GST phải bảo đảm thông điệp giữa các node đúng đến trong cận `Delta` đã cấu hình. Rate limit, queue và retry không được âm thầm phá giả định này.
- Có timeout, đổi round, chọn proposer xác định và cơ chế giúp node chậm lấy lại block/bằng chứng còn thiếu qua mạng.

### 5.2. Cryptography, dữ liệu và execution

- Dùng một signature scheme nhất quán và một collision-resistant hash.
- Transaction, block header và vote đều có chữ ký; domain separation rõ ràng, ví dụ `TX:chain_id`, `HEADER:chain_id`, `VOTE:chain_id`.
- Ký đủ định danh/ngữ cảnh. Vote ràng buộc chain, height, round, phase và block hash; kiểm tra người ký thuộc validator registry.
- Định nghĩa canonical byte encoding cho mọi dữ liệu được hash/ký. Cùng nội dung logic phải cho cùng bytes.
- Block chứa danh sách transaction có thứ tự, parent hash và commitment của state sau thực thi; phải ràng buộc cả nội dung transaction vào block identity.
- Transaction chỉ được sửa dữ liệu thuộc sender và phải có chữ ký hợp lệ. Có cơ chế chống replay để một transaction áp dụng tối đa một lần, kể cả ở block sau.
- Với thiết kế nonce, đưa nonce vào state commitment; dedup mempool riêng không đủ ngăn replay xuyên block.
- Execute trên state tạm để validate; chỉ cập nhật state chính khi finalize. Block sai không được làm thay đổi committed state.

### 5.3. Consensus và locking

Bám sát mục 6.1 của đề, không thay bằng bỏ phiếu đa số đơn giản:

1. Mỗi validator đúng ký tối đa một `PREVOTE` và một `PRECOMMIT` cho mỗi `(height, round)`, kể cả vote `NIL`.
2. Chỉ prevote block đã kiểm tra parent, transaction, state hash, proposer và chữ ký hợp lệ.
3. Đủ quorum `PREVOTE` cho block khác `NIL` thì lock block và ghi lock round.
4. Validator đã lock block B chỉ được prevote block khác khi đã quan sát quorum `PREVOTE` hợp lệ cho block khác đó ở round muộn hơn lock round. Không xóa lock chỉ vì timeout.
5. Không ký vote sai chain, height, round, phase hoặc domain.
6. Bỏ qua duplicate; đếm tối đa một vote hợp lệ cho mỗi validator trong `(height, round, phase)`. Không gộp phiếu khác block/round/phase thành quorum.
7. Finalize dựa trên quorum `PRECOMMIT` hợp lệ cho cùng block và ngữ cảnh. Thiếu body/parent thì lấy dữ liệu và validate trước khi commit state.

Thiết kế rõ chứng cứ đổi lock, re-proposal và round catch-up để vừa giữ safety vừa đạt liveness. Block identity phải ổn định khi cùng block được đề xuất lại ở round khác. `NIL` khác block rỗng hợp lệ.

### 5.4. Determinism và log

- Dùng thời gian mô phỏng, event queue có tie-break sequence và PRNG theo seed; ưu tiên event loop một luồng.
- Genesis, workload và key fixtures cho test phải tái lập được. Không xem seed mô phỏng là nguồn ngẫu nhiên mật mã cho ứng dụng thực tế.
- Không đưa wall-clock time, UUID ngẫu nhiên, PID, địa chỉ object hoặc đường dẫn output thay đổi vào log cần so sánh.
- Ghi mọi network/consensus event ảnh hưởng kết quả. Log mạng gồm send/drop/delay/block/unblock; trường tối thiểu là timestamp mô phỏng, node ID, type và height; thêm round, block hash, reason khi phù hợp.
- Có script chạy cùng scenario hai lần ở process riêng, so sánh **bytes của log thực tế** và state hash cuối. Không bỏ trường khác nhau để ép T8 pass.

## 6. Kiểm thử và bằng chứng nghiệm thu

Unit tests theo đề: chữ ký/context, state update, vote counting và block validation. Bổ sung kiểm tra lock qua round, node isolation, rate limit và header/body vì đây là các ràng buộc dễ bị vi phạm.

| Test | Kịch bản | Kết quả bắt buộc theo đề |
|---|---|---|
| T1 | Chạy bình thường | Mọi node đúng finalize cùng chain và state hash |
| T2 | Duplicate/reorder message | Không đếm phiếu lặp, không finalize xung đột |
| T3 | Chữ ký sai hoặc sai domain | Từ chối thông điệp, log lý do |
| T4 | Replay/duplicate transaction | Transaction được áp dụng tối đa một lần |
| T5 | Drop/delay trước synchrony | Luôn giữ safety, không double finalization ở cùng height |
| T6 | Proposer im lặng/crash | Timeout kích hoạt đổi round và chain tiếp tục |
| T7 | Tối đa `f` Byzantine equivocate | Không finalize xung đột |
| T8 | Chạy lại cùng seed/config | Log giống từng byte và cùng state hash cuối |

Mọi test phải tái lập và gọi được từ **một entry point**. Fault injection phải thực sự xảy ra và có bằng chứng trong log; chỉ đặt tên test là Byzantine/drop không đủ.

Kiểm tra safety xuyên suốt các sự kiện finalize và tính bất biến của finalized history, không chỉ so state cuối. Với scenario yêu cầu tiến triển, đặt `target_height > 0`, giới hạn thời gian mô phỏng và fail nếu các node đúng không đạt mục tiêu. Hai chain rỗng giống nhau không chứng minh hệ thống hoạt động.

T7 chạy với **đúng `f` validator Byzantine** (3 trên 10), là trường hợp nặng nhất mà đề cho phép; trong đó phải có lượt validator Byzantine làm proposer và gửi hai block khác nhau cho hai nhóm node.

T5/T7 có thể kiểm tra thêm phục hồi tiến triển sau GST như một kiểm tra bổ sung. Phân biệt rõ điều đó với required outcome của từng test trong bảng đề.

## 7. Hướng triển khai mặc định và đầu ra

Nếu workspace chưa có code, chọn **Python 3.10+, `cryptography`/Ed25519, `hashlib`/SHA-256, `pytest`, JSON chuẩn hóa và discrete-event simulator**. Máy này có Python 3.12, 3.13 và 3.14; dùng **3.12** (`py -3.12`) vì `cryptography` có sẵn wheel (đã kiểm tra bản 50.0.2). Dùng virtual environment, ghi phiên bản đã thực sự dùng vào README và chốt dependencies có thể cài lại. Nếu đã có implementation phù hợp, tiếp tục và sửa nó thay vì viết lại vô cớ.

Làm việc trong `Lab01/implementation/` để giữ nguyên PDF và hướng dẫn gốc. Cấu trúc gợi ý:

```text
Lab01/implementation/
├── src/                 # encoding, crypto, models, execution, network,
│                        # scheduler, consensus, node, simulator, CLI
├── tests/               # unit tests, T1–T8, runner, determinism checker
├── config/              # genesis, fixtures, scenario configs
├── logs/                # log + summary thực tế, có thể tái tạo
├── requirements.txt
├── README.md
├── REPORT.md            # nguồn báo cáo để chỉnh sửa
└── REPORT.pdf           # bản nộp, tối đa 10 trang
```

Giao diện CLI mục tiêu, đứng tại `Lab01/implementation/`:

```powershell
python -m src.main --config config/t1_normal.json --output logs/t1
python -m tests.run_all
python -m tests.check_determinism
```

Đây là giao diện đề xuất cần triển khai; README cuối cùng phải ghi đúng các lệnh đã kiểm chứng chạy được. Có thể gọi trực tiếp `.venv\Scripts\python.exe` trên Windows mà không cần thay execution policy.

## 8. Các mốc Claude cần thực hiện

- [x] **G1 — Đọc và chốt thiết kế:** đọc nguồn, kiểm tra code hiện tại, ghi schema/message domains, block identity, quorum, lock/unlock, proposer, timeout và giả định GST/Delta.
  - *14/11:* đã đọc đề 5 trang + slide 21 trang; thiết kế ghi ở mục 3–5 của `REPORT.tex` và docstring đầu mỗi file `src/`.
- [x] **G2 — Dữ liệu/crypto/execution:** canonical encoding, keys, chữ ký, ownership, chống replay, commitment và block validation; chạy unit tests tương ứng.
  - *14/11:* `src/encoding.py`, `crypto.py`, `models.py`, `execution.py`; unit test `test_crypto.py`, `test_execution.py`, `test_block_validation.py` đạt.
- [x] **G3 — Simulator/network:** event queue xác định, link delay/drop/duplicate/reorder, outbound limit, block/unblock và header/body handshake; kiểm tra các hành vi thực tế.
  - *14/11:* `src/scheduler.py`, `network.py`, `simulator.py`; `test_network.py` đạt; X1 có 183 tin xếp hàng, 3 block / 3 unblock.
- [x] **G4 — Consensus bình thường:** node độc lập, proposal, hai pha, quorum và finalize; T1 chạy được với 10 validator qua nhiều height.
  - *14/11:* `src/consensus.py`, `node.py`; T1 đạt 12/12 height, 0 timeout.
- [x] **G5 — Fault tolerance:** timeout, lock qua round, bằng chứng đổi lock, re-proposal, catch-up; chạy T2–T7 và sửa lỗi đến khi đạt yêu cầu.
  - *14/11:* `src/byzantine.py`; T2–T7 + X1–X3 đạt; quét 20 seed cho T5, T7, X3: 60/60 giữ safety và tới target; `test_locking.py` đạt.
- [x] **G6 — Tái lập:** T8 chạy hai process; kiểm tra log giống từng byte, cùng state hash; chạy toàn bộ unit tests và T1–T8 từ một entry point.
  - *14/11:* `python -m tests.run_all` → TỔNG KẾT: PASS (72 unit test; T8 10/10 scenario giống từng byte; 2 đột biến đều bị oracle bắt). `python -m pytest tests` → 102 passed.
  - *15/11 (rà soát lại):* state cuối lấy tại height chung (trước đó phụ thuộc thời điểm dừng); `send` ghi ngay khi gửi; cận Δ đo từ max(lúc gửi, GST); thêm `test_oracle.py`. Nay 83 unit test, `pytest tests` → 113 passed; quét 30 seed × 10 scenario: 0 vi phạm safety.
- [x] **G7 — Tài liệu/kết quả:** README đủ cài/chạy/test; lưu config, log, summary và bảng kết quả thực tế; soạn báo cáo và xuất PDF tối đa 10 trang.
  - *14/11:* `README.md`, `logs/RESULTS.md`, `REPORT.pdf` 5 trang. Nguồn báo cáo là **`REPORT.tex`** (không phải `.md`, vì máy không có pandoc); biên dịch bằng `xelatex REPORT.tex` hai lần. **Còn thiếu:** bảng thông tin nhóm trong báo cáo đang là placeholder màu đỏ.
- [ ] **G8 — Bộ bài nộp:** đặt đúng tên folder/ZIP, đủ file, loại dependencies/cache; giải nén vào thư mục kiểm tra riêng và chạy lại theo README.
  - *14/11:* quy trình đã kiểm chứng trên **bản nháp** `Lab01/submission/Lab01_BAN-NHAP-CHUA-CO-MSSV.zip` (1,4 MB, 91 file): giải nén sang thư mục khác, tạo venv mới, cài theo README, `tests.run_all` PASS, 10/10 `events.log` trùng từng byte với bản gốc. **Chưa xong:** chờ danh sách MSSV + họ tên. Khi có: điền bảng ở mục 1 của `REPORT.tex`, biên dịch lại, chạy `python Lab01/make_submission.py <MSSV1> <MSSV2> ...`, rồi xóa bản nháp.

Cập nhật checklist sau mỗi mốc bằng bằng chứng ngắn: file đã tạo, command đã chạy, kết quả, vấn đề còn lại. Nếu phiên làm việc bị ngắt, ghi mốc đang làm và bước tiếp theo ngay dưới checklist để phiên sau tiếp tục.

## 9. Báo cáo và đóng gói

Đề yêu cầu thư mục và ZIP tên `Lab01_ID1_ID2_ID3_ID4_ID5`, chứa `src/`, `tests/`, `logs/`, `config/`, `README.md`, `REPORT.pdf`. Đề ghi rõ **nộp sai quy cách là 0 điểm**, nên:

- ZIP có đúng một thư mục gốc `Lab01_<các MSSV>` rồi mới tới nội dung; không nén thẳng các file ở gốc ZIP.
- Số MSSV trong tên bằng số thành viên thật của nhóm (đề viết 5 chỗ làm mẫu); hỏi người dùng danh sách MSSV và thứ tự.
- Ngoài sáu mục đề liệt kê, chỉ thêm `requirements.txt` vì README cần nó để cài lại; nêu rõ điều này trong README. `REPORT.md` và file nguồn báo cáo khác **ở lại** `Lab01/implementation/`, không vào ZIP.

`REPORT.pdf` tối đa 10 trang, tiếng Việt hoặc tiếng Anh, có thông tin thành viên, cấu trúc project, mục đích/lựa chọn thiết kế, sơ đồ và luồng hệ thống, implementation notes về guards/gossip/consensus, bug thực tế và cách sửa, testing/results, mọi tài liệu/link/sách đã tham khảo. **Không chèn source code vào báo cáo.**

Chưa có tên thành viên/MSSV trong yêu cầu hiện tại. Dùng placeholder rõ ràng trong bản nháp; tiếp tục triển khai phần kỹ thuật. Trước khi chốt thông tin nhóm và tên bộ bài nộp, hỏi người dùng dữ liệu còn thiếu. Không bịa danh tính hoặc coi ZIP còn placeholder là bản nộp cuối đã hoàn tất.

Không đưa `.venv`, `__pycache__`, dependency đã tải hoặc file tạm vào ZIP. Không sửa/xóa tài liệu đầu vào. Không tự nộp lên hệ thống môn học, push hay publish khi chưa được yêu cầu.

## 10. Điều kiện kết thúc và cách báo lại

Chỉ đánh dấu goal hoàn tất khi implementation chạy được, unit tests và T1–T8 đạt yêu cầu bằng kết quả thật, README tái lập được, có log/config, PDF đúng giới hạn và bộ bài nộp đúng quy cách. Nếu thiếu thông tin nhóm hoặc công cụ xuất PDF, ghi rõ phần còn thiếu và hoàn thành mọi việc độc lập còn làm được; không báo hoàn tất giả.

Không hard-code chain/state kết quả, không cho simulator chọn block giúp node, không giảm quorum hoặc bỏ kiểm tra để test pass. Không viết số liệu/bug giả vào báo cáo. Ghi nguồn tham khảo đúng yêu cầu đề.

Khi bàn giao kết quả cho người dùng, nêu ngắn gọn:

1. Đã triển khai gì và các đường dẫn chính.
2. Lệnh cài, chạy demo và chạy toàn bộ test.
3. Kết quả unit tests/T1–T8 đã thực sự chạy, cùng log/summary liên quan.
4. Đường dẫn báo cáo và ZIP; thông tin còn thiếu hoặc giới hạn thực tế nếu có.

**Bắt đầu từ G1 và tiếp tục triển khai. Chỉ hỏi khi thiếu thông tin ảnh hưởng quyết định hoặc gặp trở ngại thật; không yêu cầu xác nhận lại cho các bước lập trình, sửa lỗi và kiểm thử thông thường trong phạm vi lab.**
