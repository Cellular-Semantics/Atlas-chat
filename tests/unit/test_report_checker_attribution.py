"""check_attribution: every blockquote quote carries an attribution line.

Reference failure: the April 2026 Neuroendocrine report — 15 verifiable quotes,
zero attributions — passed quote validation because only content was checked.
"""

from __future__ import annotations

import pytest
from atlas_chat.validation.report_checker import check_attribution

pytestmark = pytest.mark.unit

ATTRIBUTED = """# Report

## Markers
> "CD5L, APOE, VCAM"
>
> — Gopee et al. (2024)

Prose continues.
"""

UNATTRIBUTED = """# Report

> "CD5L, APOE, VCAM"

Prose continues.
"""

TWO_QUOTES_ONE_ATTRIBUTION = """# Report

> "first quote"
> "second quote"
>
> — Gopee et al. (2024)
"""

MULTI_BLOCK = """# Report

> "attributed quote"
>
> — Suo et al. (2022)

Some prose.

> "orphan quote"

More prose.
"""


def test_attributed_quote_passes() -> None:
    assert check_attribution(ATTRIBUTED) == []


def test_unattributed_quote_fails() -> None:
    errors = check_attribution(UNATTRIBUTED)
    assert len(errors) == 1
    assert "no attribution" in errors[0]
    assert "CD5L" in errors[0]


def test_back_to_back_quotes_first_unattributed() -> None:
    # The first quote's obligation is not met by the attribution that follows
    # the second — a new quote starts a new obligation.
    errors = check_attribution(TWO_QUOTES_ONE_ATTRIBUTION)
    assert len(errors) == 1
    assert "first quote" in errors[0]


def test_mixed_blocks_flags_only_the_orphan() -> None:
    errors = check_attribution(MULTI_BLOCK)
    assert len(errors) == 1
    assert "orphan quote" in errors[0]


def test_no_quotes_no_errors() -> None:
    assert check_attribution("# Report\n\nJust prose, no quotes.\n") == []


def test_hyphen_dash_variants_accepted() -> None:
    for dash in ("—", "–", "--", "-"):
        md = f'> "q"\n>\n> {dash} Author et al. (2020)\n'
        assert check_attribution(md) == [], f"dash variant {dash!r} rejected"
