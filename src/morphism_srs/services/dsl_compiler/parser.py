from __future__ import annotations

from dataclasses import dataclass, field
import re

from morphism_srs.services.dsl_compiler.lexer import DSLLexer


@dataclass
class DSLCardNode:
    step_order: int = 0
    title: str = ""
    uuid: str | None = None
    front: str = ""
    back: str = ""
    hint: str = ""
    line_num: int = 1


@dataclass
class DSLNoteNode:
    external_key: str
    title: str = ""
    uuid: str | None = None
    mode: str = "standard"
    tags: list[str] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    premise: str = ""
    retention: float | None = None
    pos: tuple[float, float] | None = None
    cards: list[DSLCardNode] = field(default_factory=list)
    line_num: int = 1


@dataclass
class DSLCourseAST:
    course_name: str = ""
    course_uuid: str | None = None
    folder_path: str = ""
    color_hex: str = "#89b4fa"
    description: str = ""
    notes: list[DSLNoteNode] = field(default_factory=list)


class DSLParser:
    """Parses .mdsl tokens into a DSLCourseAST."""

    QUOTED_RE = re.compile(r'^"(.*)"$|^\'(.*)\'$')

    MODE_ALIASES = {
        "standard": "standard",
        "serial": "serial",
        "serial_sequence": "serial",
        "serial_sequence_single": "serial",
        "cloze": "cloze",
    }

    @classmethod
    def _parse_folder_path(cls, folder_raw: str) -> str:
        """Parses folder paths with quotes outside slashes: "Pure Mathematics"/"Algebra"
        as well as legacy: "Pure Mathematics/Algebra" or unquoted paths."""
        quoted = re.findall(r'"([^"]*)"|\'([^\']*)\'' , folder_raw)
        if quoted:
            parts = [q[0] if q[0] else q[1] for q in quoted if (q[0] or q[1])]
            return "/".join(p.strip() for p in parts if p.strip())
        clean = folder_raw.strip().strip('"').strip("'")
        parts = [p.strip() for p in clean.replace("\\", "/").split("/") if p.strip()]
        return "/".join(parts)

    @classmethod
    def _parse_course_directive(cls, val: str) -> tuple[str, str | None, str | None]:
        """Parses COURSE "Name" [UUID {uuid}] [FOLDER "Part1"/"Part2"/...]"""
        raw = val.strip()
        folder_path: str | None = None
        m_folder = re.search(r'\bFOLDER\s+(.+)$', raw, re.IGNORECASE)
        if m_folder:
            folder_raw = m_folder.group(1).strip()
            raw = raw[:m_folder.start()].strip()
            folder_path = cls._parse_folder_path(folder_raw)

        course_uuid: str | None = None
        m_uuid = re.search(r'\bUUID\s+\{?([a-zA-Z0-9_\-]+)\}?\s*$', raw, re.IGNORECASE)
        if m_uuid:
            course_uuid = m_uuid.group(1).strip().lower()
            raw = raw[:m_uuid.start()].strip()

        course_name = cls._unquote(raw)
        return course_name, course_uuid, folder_path

    @classmethod
    def _unquote(cls, text: str) -> str:
        t = text.strip()
        m = cls.QUOTED_RE.match(t)
        if m:
            return m.group(1) if m.group(1) is not None else (m.group(2) or "")
        return t

    @staticmethod
    def _slugify(title: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", title.strip().lower()).strip("_")
        return slug or "note"

    @staticmethod
    def _parse_list(raw: str) -> list[str]:
        s = raw.strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        return [item.strip().strip('"').strip("'") for item in s.split(",") if item.strip()]

    def parse(self, source: str) -> DSLCourseAST:
        lexer = DSLLexer()
        tokens = lexer.tokenize(source)
        ast = DSLCourseAST()

        current_note: DSLNoteNode | None = None
        current_card: DSLCardNode | None = None
        active_field: str | None = None
        in_body = False
        explicit_links: list[tuple[str, str, int]] = []

        def _flush_card() -> None:
            nonlocal current_card
            if current_note is not None and current_card is not None:
                if current_card.front.strip() or current_card.back.strip() or current_card.title:
                    current_card.step_order = len(current_note.cards)
                    if not current_card.title:
                        current_card.title = f"Card {current_card.step_order + 1}"
                    current_note.cards.append(current_card)
            current_card = None

        for tok in tokens:
            if tok.kind == "LINK_EDGE":
                _flush_card()
                active_field = None
                explicit_links.append((tok.key, tok.value, tok.line_num))
                continue

            if tok.kind == "DIRECTIVE":
                _flush_card()
                in_body = False
                active_field = None
                if tok.key == "course":
                    c_name, c_uuid, c_folder = self._parse_course_directive(tok.value)
                    ast.course_name = c_name
                    if c_uuid:
                        ast.course_uuid = c_uuid
                    if c_folder:
                        ast.folder_path = c_folder
                    current_note = None
                elif tok.key == "folder":
                    ast.folder_path = self._parse_folder_path(tok.value)
                elif tok.key == "new_note":
                    m_uuid = re.search(r'^(.*?)\s+UUID\s+\{?([a-zA-Z0-9_\-]+)\}?\s*$', tok.value, re.IGNORECASE)
                    if m_uuid:
                        raw_title = m_uuid.group(1).strip()
                        note_uuid = m_uuid.group(2).strip().lower()
                    else:
                        raw_title = tok.value.strip()
                        note_uuid = None
                    note_title = self._unquote(raw_title) or f"Note {len(ast.notes) + 1}"
                    ext_key = note_title
                    current_note = DSLNoteNode(
                        external_key=ext_key,
                        title=note_title,
                        uuid=note_uuid,
                        line_num=tok.line_num,
                    )
                    ast.notes.append(current_note)
                elif tok.key == "note":
                    ext_key = self._unquote(tok.value) or f"note_{len(ast.notes) + 1}"
                    current_note = DSLNoteNode(
                        external_key=ext_key,
                        title=ext_key.replace("_", " ").title(),
                        line_num=tok.line_num,
                    )
                    ast.notes.append(current_note)
                continue

            if tok.kind == "BLOCK_DELIM":
                if not in_body:
                    in_body = True
                    active_field = None
                else:
                    _flush_card()
                    in_body = False
                    active_field = None
                continue

            if tok.kind == "STEP_HEADER" and current_note is not None:
                _flush_card()
                card_num = tok.key or str(len(current_note.cards) + 1)
                raw_val = tok.value or ""
                card_uuid = None
                m_uuid = re.search(r'^(.*?)\s+UUID\s+([a-zA-Z0-9_\-]+)\s*$', raw_val, re.IGNORECASE)
                if m_uuid:
                    raw_title = self._unquote(m_uuid.group(1).strip()) or f"Card {card_num}"
                    card_uuid = m_uuid.group(2).strip().lower()
                else:
                    raw_title = self._unquote(raw_val) if raw_val else f"Card {card_num}"

                current_card = DSLCardNode(
                    step_order=len(current_note.cards),
                    title=raw_title,
                    uuid=card_uuid,
                    line_num=tok.line_num,
                )
                active_field = None
                continue

            if tok.kind == "SECTION_MARKER" and current_note is not None:
                if current_card is None:
                    current_card = DSLCardNode(
                        step_order=len(current_note.cards),
                        title=f"Card {len(current_note.cards) + 1}",
                        line_num=tok.line_num,
                    )
                active_field = tok.key  # "front" or "back"
                continue

            if tok.kind == "PROPERTY":
                k = tok.key
                v = tok.value
                if current_note is None:
                    if k == "folder":
                        ast.folder_path = self._unquote(v)
                    elif k == "color":
                        ast.color_hex = self._unquote(v)
                    elif k == "description":
                        ast.description = self._unquote(v)
                    continue

                if k in {"q", "front"}:
                    if current_card is None:
                        current_card = DSLCardNode(
                            step_order=len(current_note.cards),
                            title=f"Card {len(current_note.cards) + 1}",
                            line_num=tok.line_num,
                        )
                    current_card.front = self._unquote(v)
                    active_field = "front"
                elif k in {"a", "back"}:
                    if current_card is None:
                        current_card = DSLCardNode(
                            step_order=len(current_note.cards),
                            title=f"Card {len(current_note.cards) + 1}",
                            line_num=tok.line_num,
                        )
                    current_card.back = self._unquote(v)
                    active_field = "back"
                elif not in_body:
                    if k == "uuid":
                        uuid_val = self._unquote(v).strip().lower()
                        if current_card is not None:
                            current_card.uuid = uuid_val
                        elif current_note is not None:
                            current_note.uuid = uuid_val
                    elif k == "title":
                        current_note.title = self._unquote(v)
                    elif k == "mode":
                        raw_mode = self._unquote(v).lower()
                        current_note.mode = self.MODE_ALIASES.get(raw_mode, raw_mode)
                    elif k == "tags":
                        current_note.tags = [t.lower().replace(" ", "_") for t in self._parse_list(v)]
                    elif k == "deps":
                        current_note.deps.extend(self._parse_list(v))
                    elif k == "retention":
                        try:
                            current_note.retention = float(v)
                        except ValueError:
                            pass
                    elif k == "pos":
                        coords = self._parse_list(v)
                        if len(coords) == 2:
                            try:
                                current_note.pos = (float(coords[0]), float(coords[1]))
                            except ValueError:
                                pass
                continue

            if tok.kind == "TEXT":
                if not tok.raw.strip() and active_field is None:
                    continue
                if current_card is not None and active_field in {"front", "back"}:
                    prev = getattr(current_card, active_field)
                    joined = f"{prev}\n{tok.raw}" if prev else tok.raw
                    setattr(current_card, active_field, joined.strip())

        _flush_card()

        # Resolve LINK "Parent" -> "Child" into Child.deps
        title_or_key_map: dict[str, DSLNoteNode] = {}
        for n in ast.notes:
            title_or_key_map[n.external_key] = n
            title_or_key_map[n.title] = n
            if n.uuid:
                title_or_key_map[n.uuid] = n

        for src_name, dst_name, _ in explicit_links:
            dst_note = title_or_key_map.get(dst_name)
            src_note = title_or_key_map.get(src_name)
            if dst_note is not None:
                dep_ref = src_note.external_key if src_note is not None else src_name
                if dep_ref not in dst_note.deps:
                    dst_note.deps.append(dep_ref)

        return ast
