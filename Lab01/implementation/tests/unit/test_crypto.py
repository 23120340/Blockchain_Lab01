"""Chữ ký, domain separation và canonical encoding."""
import pytest

from src.crypto import fixture_keypair, hash_obj, sign, verify
from src.encoding import canonical, decode
from src.models import (NIL, PREVOTE, PRECOMMIT, VOTE_FIELDS, block_hash, check_certificate,
                        check_vote, header_domain, make_header, make_tx, make_vote, payload,
                        tx_domain, tx_id, tx_root, vote_domain)

CHAIN = "unit-chain"
KP = fixture_keypair(CHAIN, "v0")
PUBS = {f"v{i}": fixture_keypair(CHAIN, f"v{i}").pub_hex for i in range(4)}


def test_canonical_encoding_ignores_key_order():
    assert canonical({"b": 1, "a": [1, "x"]}) == canonical({"a": [1, "x"], "b": 1})
    assert canonical({"a": 1}) == b'{"a":1}'
    assert decode(canonical({"k": "tiếng Việt"})) == {"k": "tiếng Việt"}


def test_canonical_encoding_rejects_ambiguous_types():
    with pytest.raises(TypeError):
        canonical({"x": 1.5})
    with pytest.raises(TypeError):
        canonical({1: "x"})


def test_signature_roundtrip_and_tamper():
    body = {"a": 1, "b": "x"}
    sig = sign(KP, "TX:" + CHAIN, body)
    assert verify(KP.pub_hex, "TX:" + CHAIN, body, sig)
    assert not verify(KP.pub_hex, "TX:" + CHAIN, {"a": 2, "b": "x"}, sig)
    assert not verify(PUBS["v1"], "TX:" + CHAIN, body, sig)
    assert not verify(KP.pub_hex, "TX:" + CHAIN, body, "zz")


def test_signature_does_not_cross_domains_or_chains():
    body = {"a": 1}
    sig = sign(KP, tx_domain(CHAIN), body)
    assert not verify(KP.pub_hex, vote_domain(CHAIN), body, sig)
    assert not verify(KP.pub_hex, header_domain(CHAIN), body, sig)
    assert not verify(KP.pub_hex, tx_domain("other-chain"), body, sig)


def test_key_fixtures_are_reproducible():
    assert fixture_keypair(CHAIN, "alice").pub_hex == fixture_keypair(CHAIN, "alice").pub_hex
    assert fixture_keypair(CHAIN, "alice").pub_hex != fixture_keypair(CHAIN, "bob").pub_hex


def test_vote_accepts_valid_and_rejects_with_reason():
    vote = make_vote(KP, CHAIN, 3, 1, PREVOTE, "ab" * 32, "v0")
    assert check_vote(vote, CHAIN, PUBS) is None
    assert check_vote({**vote, "sig": "00" * 64}, CHAIN, PUBS) == "bad_signature"
    assert check_vote({**vote, "domain": tx_domain(CHAIN)}, CHAIN, PUBS) == "wrong_domain"
    assert check_vote(make_vote(KP, "other", 3, 1, PREVOTE, NIL, "v0"), CHAIN, PUBS) == "wrong_chain"
    stranger = fixture_keypair(CHAIN, "mallory")
    assert check_vote(make_vote(stranger, CHAIN, 3, 1, PREVOTE, NIL, "mallory"),
                      CHAIN, PUBS) == "unknown_validator"
    # Mạo danh: tên v1 nhưng chữ ký của v0.
    assert check_vote(make_vote(KP, CHAIN, 3, 1, PREVOTE, NIL, "v1"), CHAIN, PUBS) == "bad_signature"
    assert check_vote({**vote, "phase": "COMMIT"}, CHAIN, PUBS) == "malformed"
    assert check_vote({**vote, "height": True}, CHAIN, PUBS) == "malformed"


@pytest.mark.parametrize("field,value", [("height", 4), ("round", 2), ("phase", PRECOMMIT),
                                         ("block_hash", "cd" * 32), ("validator", "v1")])
def test_vote_signature_binds_every_context_field(field, value):
    vote = make_vote(KP, CHAIN, 3, 1, PREVOTE, "ab" * 32, "v0")
    assert check_vote({**vote, field: value}, CHAIN, PUBS) == "bad_signature"


def test_vote_signed_under_tx_domain_is_not_a_vote():
    vote = make_vote(KP, CHAIN, 3, 1, PREVOTE, NIL, "v0")
    cross = {**vote, "sig": sign(KP, tx_domain(CHAIN), payload(vote, VOTE_FIELDS))}
    assert check_vote(cross, CHAIN, PUBS) == "bad_signature"


def test_block_identity_binds_transactions_and_order():
    alice = fixture_keypair(CHAIN, "alice")
    t1 = make_tx(alice, CHAIN, "alice", 0, "alice/a", "1")
    t2 = make_tx(alice, CHAIN, "alice", 1, "alice/b", "2")
    assert tx_root([t1, t2]) != tx_root([t2, t1])
    assert tx_id(t1) != tx_id({**t1, "value": "9"})
    h1 = make_header(KP, CHAIN, 1, "p", [t1, t2], "s", "v0")
    h2 = make_header(KP, CHAIN, 1, "p", [t2, t1], "s", "v0")
    assert block_hash(h1) != block_hash(h2)
    assert block_hash(h1) == block_hash(make_header(KP, CHAIN, 1, "p", [t1, t2], "s", "v0"))
    assert hash_obj({"a": 1, "b": 2}) == hash_obj({"b": 2, "a": 1})


def test_certificate_needs_distinct_validators_same_context():
    keys = {v: fixture_keypair(CHAIN, v) for v in PUBS}
    h = "ab" * 32
    good = [make_vote(keys[v], CHAIN, 1, 0, PRECOMMIT, h, v) for v in ("v0", "v1", "v2")]
    assert check_certificate(good, PRECOMMIT, 1, 0, h, CHAIN, PUBS, 3)
    assert not check_certificate(good[:2], PRECOMMIT, 1, 0, h, CHAIN, PUBS, 3)
    assert not check_certificate(good[:2] + good[:1], PRECOMMIT, 1, 0, h, CHAIN, PUBS, 3)
    mixed_round = good[:2] + [make_vote(keys["v2"], CHAIN, 1, 1, PRECOMMIT, h, "v2")]
    assert not check_certificate(mixed_round, PRECOMMIT, 1, 0, h, CHAIN, PUBS, 3)
    mixed_phase = good[:2] + [make_vote(keys["v2"], CHAIN, 1, 0, PREVOTE, h, "v2")]
    assert not check_certificate(mixed_phase, PRECOMMIT, 1, 0, h, CHAIN, PUBS, 3)
    assert not check_certificate(good, PRECOMMIT, 2, 0, h, CHAIN, PUBS, 3)
