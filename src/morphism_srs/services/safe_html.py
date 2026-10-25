from __future__ import annotations

import re

MATH_BLOCK_RE = re.compile(
    r"""
    (
        \$\$.*?\$\$                      # $$ display math $$
        |
        \\\[.*?\\\]                      # \[ display math \]
        |
        \\\(.*?\\\)                      # \( inline math \)
        |
        (?<!\\)\$(?!\$)(?:\\.|[^$\\])+\$ # $ inline math $
    )
    """,
    re.DOTALL | re.VERBOSE,
)


def sanitize_math_html(raw: str) -> str:
    r"""
    Converts mathematical comparison operators `<` and `>` into LaTeX commands `\lt ` and `\gt `
    EXCLUSIVELY inside mathematical environments ($...$, $$...$$, \(...\), \[...\]).
    Everything outside math mode (including standard and non-standard HTML tags, attributes,
    and plain text) is preserved 100% intact without modification.
    """
    if not raw:
        return ""

    def _sanitize_math_block(match: re.Match[str]) -> str:
        s = match.group(0)
        s = re.sub(r"(?<!\\)<=", r"\\le ", s)
        s = re.sub(r"(?<!\\)>=", r"\\ge ", s)
        s = re.sub(r"(?<!\\)<", r"\\lt ", s)
        s = re.sub(r"(?<!\\)>", r"\\gt ", s)
        return s

    return MATH_BLOCK_RE.sub(_sanitize_math_block, raw)
