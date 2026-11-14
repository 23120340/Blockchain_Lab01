"""Bộ test phải TRƯỢT khi giao thức bị làm hỏng."""
from tests.mutations import run_mutations


def test_oracle_catches_broken_protocol():
    rows = run_mutations(seeds=(1, 2))
    assert rows and all(r["pass"] for r in rows), rows
