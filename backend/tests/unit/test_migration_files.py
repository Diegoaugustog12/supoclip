"""The migration runner splits files on every semicolon (src/database.py).

A semicolon inside a comment or string therefore cuts a statement in two and the
backend fails to start. Keep each fragment a whole statement.
"""
from pathlib import Path

import pytest

MIGRATIONS = sorted((Path(__file__).parents[2] / "src" / "migrations" / "sql").glob("*.sql"))
KEYWORDS = ("CREATE", "ALTER", "INSERT", "UPDATE", "DELETE", "DROP", "DO", "WITH", "COMMENT", "GRANT", "SELECT", "REVOKE")


def _statements(path: Path):
    for fragment in path.read_text(encoding="utf-8").split(";"):
        lines = [line for line in fragment.splitlines() if line.strip() and not line.strip().startswith("--")]
        if lines:
            yield "\n".join(lines).strip()


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_every_fragment_between_semicolons_is_a_statement(path):
    for statement in _statements(path):
        assert statement.upper().startswith(KEYWORDS), (
            f"{path.name}: fragment starts with {statement[:50]!r}. Is there a ';' in a comment or string?"
        )
