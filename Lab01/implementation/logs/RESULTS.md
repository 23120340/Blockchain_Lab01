# Kết quả kiểm thử (sinh tự động bởi `python -m tests.run_all`)

- Unit tests: **PASS** — `72 passed in 0.40s`

| Test | Kịch bản | Kết quả bắt buộc | Kết quả | Height | Thời gian mô phỏng | Bằng chứng trong log |
|---|---|---|---|---|---|---|
| T1 | Chạy bình thường, không lỗi | Mọi node đúng finalize cùng chain và state hash | **PASS** | 12/12 | 1463 ms | finalize=120, timeout=0, drop=0 |
| T2 | Thông điệp bị nhân đôi/đảo thứ tự | Không đếm phiếu lặp, không finalize xung đột | **PASS** | 12/12 | 1413 ms | duplicate=887, ignore:duplicate_vote=355, equivocation=0 |
| T3 | Chữ ký sai / sai domain | Thông điệp bị từ chối, có log lý do | **PASS** | 10/10 | 1239 ms | reject:bad_signature=296, reject:wrong_domain=95, reject:wrong_chain=96, reject:unknown_validator=93 |
| T4 | Transaction bị phát lại / gửi lặp | Áp dụng tối đa một lần | **PASS** | 14/14 | 2126 ms | reject:stale_nonce=44, ignore:duplicate_tx=42, block_invalid:invalid_tx:replayed_nonce=9 |
| T5 | Mất/trễ tin trước synchrony | Safety giữ; không double finalization ở cùng height | **PASS** | 10/10 | 3992 ms | drop=551, delay:slow_link=763, finalize_pre_gst=38, commit_cert=18 |
| T6 | Proposer im lặng/crash | Timeout kích hoạt đổi round, chain tiếp tục | **PASS** | 12/12 | 2680 ms | crash=2, timeout:propose=25, round_start_after_round0=25 |
| T7 | f validator Byzantine equivocate | Không finalize xung đột | **PASS** | 12/12 | 2454 ms | byz_equivocate_proposal=5, byz_equivocate_vote=79, equivocation=248 |
| X1 | (bổ sung) Giới hạn gửi và chặn peer quá tải | Tin xếp hàng chứ không mất; peer gửi dồn bị chặn rồi mở lại | **PASS** | 10/10 | 1670 ms | delay:rate_limit=183, block=3, unblock=3, drop:peer_blocked=919 |
| X2 | (bổ sung) Proposer đề xuất block sai | Block bị bác, state không đổi, chain tiếp tục | **PASS** | 12/12 | 2134 ms | byz_invalid_block=3, block_invalid:state_hash_mismatch=18, block_invalid:invalid_tx:not_owner=9 |
| X3 | (bổ sung) Byzantine giấu commit để phá lock | Node đã lock không đổi phiếu; không finalize xung đột | **PASS** | 9/9 | 2223 ms | byz_withhold_commit=9, commit_cert=18, lock=93, round_start_after_round0=27 |
| T8 | Chạy lại cùng seed/config hai lần | Log giống từng byte, cùng state hash | **PASS** | — | — | 10/10 scenario giống từng byte |

## Quét seed (safety phải đúng với mọi lịch mạng)

| Scenario | Số seed | Safety đạt | Tới target | Finalize trước GST (tổng) | Equivocation bị phát hiện (tổng) |
|---|---|---|---|---|---|
| t5_drop_delay_before_gst | 20 | 20/20 | 20/20 | 515 | 0 |
| t7_byzantine_equivocation | 20 | 20/20 | 20/20 | 0 | 5696 |
| x3_withheld_commit | 20 | 20/20 | 20/20 | 0 | 1572 |

## T8 — so sánh hai process

| Scenario | Bytes log | sha256(log) lần 1 = lần 2 | State hash cuối |
|---|---|---|---|
| t1_normal | 1248114 | giống (`87f50a2addc3999f…`) | `2451cf1761f390d3…` |
| t2_duplicate_reorder | 1807888 | giống (`4e0e6f89c047a503…`) | `4c98559b4eee4ead…` |
| t3_invalid_signature_domain | 1137090 | giống (`c4a8b3ce93eff31b…`) | `436bc271db28bbf2…` |
| t4_replay_transaction | 1893323 | giống (`58e208df765e1ff4…`) | `1f1805a8c0403be6…` |
| t5_drop_delay_before_gst | 1379790 | giống (`87634ee99794294a…`) | `4c98559b4eee4ead…` |
| t6_silent_proposer | 1118893 | giống (`28f55cd9a6c4359b…`) | `4c98559b4eee4ead…` |
| t7_byzantine_equivocation | 1587922 | giống (`8f6ee63056b20414…`) | `4c98559b4eee4ead…` |
| x1_rate_limit_block | 1586293 | giống (`ecda69db3e243081…`) | `a890275cc335b326…` |
| x2_invalid_block_proposer | 1350959 | giống (`532dde4f7f2c2c8f…`) | `a890275cc335b326…` |
| x3_withheld_commit | 1141830 | giống (`659f8a67906875e1…`) | `a890275cc335b326…` |

## Độ nhạy của bộ test (cố tình làm hỏng node đúng)

| Đột biến | Scenario | Phép kiểm phải trượt | Bị bắt | Bản gốc |
|---|---|---|---|---|
| quorum 2f thay vì 2f+1 | t7_byzantine_equivocation | no_conflicting_finalization | 3/3 seed | đạt |
| bỏ luật lock khi prevote | x3_withheld_commit | no_conflicting_finalization | 3/3 seed | đạt |
