from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class DSLToken:
    kind: str  # DIRECTIVE | PROPERTY | STEP_HEADER | SECTION_MARKER | LINK_EDGE | BLOCK_DELIM | TEXT
    line_num: int
    raw: str
    key: str = ""
    value: str = ""
    extra: str = ""


class DSLLexer:
    """
    Line-oriented lexer for the .mdsl (Morphism Domain Specific Language) format.
    Supports the canonical v2 / Prototype 1 keywords:
      COURSE "Name"
      FOLDER "Path"
      NEW NOTE "Note Title"
      MODE standard | serial | cloze
      TAGS tag1, tag2
      RETENTION 0.90
      CARD 1 "Card Title"
      FRONT
      ...
      BACK
      ...
      LINK "Parent Note" -> "Child Note"  (or LINK "Parent Note" "Child Note")
    as well as @course / @note property blocks.
    """

    COURSE_KW_RE = re.compile(r'^\s*COURSE\s+(.+?)\s*$', re.IGNORECASE)
    FOLDER_KW_RE = re.compile(r'^\s*FOLDER\s+(.+?)\s*$', re.IGNORECASE)
    NEW_NOTE_RE = re.compile(r'^\s*NEW\s+NOTE\s+(.+?)\s*$', re.IGNORECASE)
    MODE_KW_RE = re.compile(r'^\s*MODE\s+(\S+)\s*$', re.IGNORECASE)
    TAGS_KW_RE = re.compile(r'^\s*TAGS\s+(.+?)\s*$', re.IGNORECASE)
    RETENTION_KW_RE = re.compile(r'^\s*RETENTION\s+([0-9.]+)\s*$', re.IGNORECASE)
    UUID_KW_RE = re.compile(r'^\s*UUID\s+(\S+)\s*$', re.IGNORECASE)
    POS_KW_RE = re.compile(r'^\s*POS\s+(.+?)\s*$', re.IGNORECASE)
    CARD_KW_RE = re.compile(r'^\s*CARD(?:\s+(\d+))?(?:\s+(.+?))?\s*$', re.IGNORECASE)
    SECTION_KW_RE = re.compile(r'^\s*(FRONT|BACK)\s*$', re.IGNORECASE)
    LINK_ARROW_RE = re.compile(
        r'^\s*LINK\s+"([^"]+)"\s*(?:->|→)?\s*"([^"]+)"\s*$', re.IGNORECASE
    )

    DIRECTIVE_RE = re.compile(r"^\s*@([a-zA-Z_]+)\s*(.*?)\s*$")
    PROPERTY_RE = re.compile(r"^\s*([a-zA-Z_]+)\s*:\s*(.*?)\s*$")
    STEP_RE = re.compile(r"^\s*\[step\s*(\d+)?(?:\s*:\s*(.*?))?\]\s*$", re.IGNORECASE)

    def tokenize(self, source: str) -> list[DSLToken]:
        tokens: list[DSLToken] = []
        lines = source.splitlines()
        in_block = False

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            if stripped == "---":
                in_block = not in_block
                tokens.append(DSLToken(kind="BLOCK_DELIM", line_num=idx, raw=line))
                continue

            # Canonical keyword grammar checks
            m_link = self.LINK_ARROW_RE.match(line)
            if m_link:
                tokens.append(
                    DSLToken(
                        kind="LINK_EDGE",
                        line_num=idx,
                        raw=line,
                        key=m_link.group(1).strip(),
                        value=m_link.group(2).strip(),
                    )
                )
                continue

            m_new_note = self.NEW_NOTE_RE.match(line)
            if m_new_note:
                in_block = False
                tokens.append(
                    DSLToken(
                        kind="DIRECTIVE",
                        line_num=idx,
                        raw=line,
                        key="new_note",
                        value=m_new_note.group(1).strip(),
                    )
                )
                continue

            m_course = self.COURSE_KW_RE.match(line)
            if m_course:
                tokens.append(
                    DSLToken(
                        kind="DIRECTIVE",
                        line_num=idx,
                        raw=line,
                        key="course",
                        value=m_course.group(1).strip(),
                    )
                )
                continue

            m_folder = self.FOLDER_KW_RE.match(line)
            if m_folder:
                tokens.append(
                    DSLToken(
                        kind="DIRECTIVE",
                        line_num=idx,
                        raw=line,
                        key="folder",
                        value=m_folder.group(1).strip(),
                    )
                )
                continue

            m_mode = self.MODE_KW_RE.match(line)
            if m_mode:
                tokens.append(
                    DSLToken(
                        kind="PROPERTY",
                        line_num=idx,
                        raw=line,
                        key="mode",
                        value=m_mode.group(1).strip(),
                    )
                )
                continue

            m_tags = self.TAGS_KW_RE.match(line)
            if m_tags:
                tokens.append(
                    DSLToken(
                        kind="PROPERTY",
                        line_num=idx,
                        raw=line,
                        key="tags",
                        value=m_tags.group(1).strip(),
                    )
                )
                continue

            m_ret = self.RETENTION_KW_RE.match(line)
            if m_ret:
                tokens.append(
                    DSLToken(
                        kind="PROPERTY",
                        line_num=idx,
                        raw=line,
                        key="retention",
                        value=m_ret.group(1).strip(),
                    )
                )
                continue

            m_uuid = self.UUID_KW_RE.match(line)
            if m_uuid:
                tokens.append(
                    DSLToken(
                        kind="PROPERTY",
                        line_num=idx,
                        raw=line,
                        key="uuid",
                        value=m_uuid.group(1).strip(),
                    )
                )
                continue

            m_pos = self.POS_KW_RE.match(line)
            if m_pos:
                tokens.append(
                    DSLToken(
                        kind="PROPERTY",
                        line_num=idx,
                        raw=line,
                        key="pos",
                        value=m_pos.group(1).strip(),
                    )
                )
                continue

            m_card = self.CARD_KW_RE.match(line)
            if m_card and (m_card.group(1) or m_card.group(2)):
                tokens.append(
                    DSLToken(
                        kind="STEP_HEADER",
                        line_num=idx,
                        raw=line,
                        key=m_card.group(1) or "",
                        value=m_card.group(2) or "",
                    )
                )
                continue

            m_sec = self.SECTION_KW_RE.match(line)
            if m_sec:
                tokens.append(
                    DSLToken(
                        kind="SECTION_MARKER",
                        line_num=idx,
                        raw=line,
                        key=m_sec.group(1).lower(),
                    )
                )
                continue

            if not in_block:
                m_dir = self.DIRECTIVE_RE.match(line)
                if m_dir:
                    tokens.append(
                        DSLToken(
                            kind="DIRECTIVE",
                            line_num=idx,
                            raw=line,
                            key=m_dir.group(1).lower(),
                            value=m_dir.group(2),
                        )
                    )
                    continue

                m_prop = self.PROPERTY_RE.match(line)
                if m_prop and m_prop.group(1).lower() in {
                    "title",
                    "mode",
                    "tags",
                    "deps",
                    "retention",
                    "uuid",
                    "pos",
                    "folder",
                    "color",
                    "description",
                    "q",
                    "a",
                }:
                    tokens.append(
                        DSLToken(
                            kind="PROPERTY",
                            line_num=idx,
                            raw=line,
                            key=m_prop.group(1).lower(),
                            value=m_prop.group(2),
                        )
                    )
                    continue

            m_step = self.STEP_RE.match(line)
            if m_step:
                tokens.append(
                    DSLToken(
                        kind="STEP_HEADER",
                        line_num=idx,
                        raw=line,
                        key=m_step.group(1) or "",
                        value=m_step.group(2) or "",
                    )
                )
                continue

            m_qa = self.PROPERTY_RE.match(line)
            if m_qa and m_qa.group(1).lower() in {"q", "a", "front", "back"}:
                tokens.append(
                    DSLToken(
                        kind="PROPERTY",
                        line_num=idx,
                        raw=line,
                        key=m_qa.group(1).lower(),
                        value=m_qa.group(2),
                    )
                )
                continue

            tokens.append(DSLToken(kind="TEXT", line_num=idx, raw=line))

        return tokens
