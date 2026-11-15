# Kết quả kiểm thử (sinh tự động bởi `python -m tests.run_all`)

- Unit tests: **PASS** — `83 passed in 0.54s`

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
| t1_normal | 1215785 | giống (`e9584d0fb6776b6e…`) | `2451cf1761f390d3…` |
| t2_duplicate_reorder | 1629398 | giống (`bc474654d57bab82…`) | `4c98559b4eee4ead…` |
| t3_invalid_signature_domain | 1105617 | giống (`26a1bf3dac7ad0c8…`) | `436bc271db28bbf2…` |
| t4_replay_transaction | 1837377 | giống (`d131c679a8965a33…`) | `1f1805a8c0403be6…` |
| t5_drop_delay_before_gst | 1410293 | giống (`5864d28edabc2fc0…`) | `4c98559b4eee4ead…` |
| t6_silent_proposer | 1087213 | giống (`777af02f54e769cf…`) | `4c98559b4eee4ead…` |
| t7_byzantine_equivocation | 1545703 | giống (`b49298d00243404f…`) | `4c98559b4eee4ead…` |
| x1_rate_limit_block | 1539615 | giống (`86974c94115fca9a…`) | `a890275cc335b326…` |
| x2_invalid_block_proposer | 1313942 | giống (`01619be168762b3d…`) | `a890275cc335b326…` |
| x3_withheld_commit | 1111368 | giống (`9af77077c7c7bcfd…`) | `a890275cc335b326…` |

## Độ nhạy của bộ test (cố tình làm hỏng node đúng)

| Đột biến | Scenario | Phép kiểm phải trượt | Bị bắt | Bản gốc |
|---|---|---|---|---|
| quorum 2f thay vì 2f+1 | t7_byzantine_equivocation | no_conflicting_finalization | 3/3 seed | đạt |
| bỏ luật lock khi prevote | x3_withheld_commit | no_conflicting_finalization | 3/3 seed | đạt |
