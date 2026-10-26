from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import sqlite3

from morphism_srs.config import get_project_root
from morphism_srs.domain.enums import NoteReviewMode
from morphism_srs.domain.models import CardModel, CourseModel, EdgeModel, NoteModel, generate_uuid
from morphism_srs.services.dsl_compiler.parser import DSLCourseAST, DSLParser
from morphism_srs.services.dsl_compiler.validator import DSLDiagnostic, DSLValidator
from morphism_srs.services.layout_service import LayoutService
from morphism_srs.services.safe_html import sanitize_math_html
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.unit_of_work import UnitOfWork


@dataclass
class DSLCompilationResult:
    ast: DSLCourseAST
    diagnostics: list[DSLDiagnostic] = field(default_factory=list)
    course_id: int | None = None
    notes_created: int = 0
    notes_updated: int = 0
    edges_created: int = 0

    @property
    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)


class DSLCompiler:
    """Compiles .mdsl source into SQLite v2 courses, notes, cards, tags, and auto-laid-out DAG edges."""

    def __init__(self, conn: sqlite3.Connection, media_vault: MediaVault | None = None) -> None:
        self.conn = conn
        self.media_vault = media_vault
        self.parser = DSLParser()
        self.validator = DSLValidator()
        self.folder_repo = FolderRepository(conn)
        self.course_repo = CourseRepository(conn)
        self.note_repo = NoteRepository(conn)

    @staticmethod
    def _find_media_file(rel_path: str, source_dir: Path | None) -> Path | None:
        clean = rel_path.strip().replace("\\", "/")
        p_clean = Path(clean)
        candidates: list[Path] = []
        if source_dir:
            sd = Path(source_dir)
            candidates.extend([
                sd / clean,
                sd / "media" / p_clean.name,
                sd / p_clean.name,
            ])
        root = get_project_root()
        candidates.extend([
            root / "to_import" / "media" / p_clean.name,
            root / "to_import" / clean,
            root / clean,
        ])
        for c in candidates:
            if c.exists() and c.is_file():
                return c
        return None

    def _process_media_text(self, text: str, source_dir: Path | None, vault: MediaVault | None) -> str:
        if not text or not vault:
            return text

        def _sub_html_img(match: re.Match[str]) -> str:
            full_tag = match.group(0)
            src = match.group(1).strip()
            if src.startswith(("morphism://", "http://", "https://", "data:")):
                return full_tag
            found = self._find_media_file(src, source_dir)
            if found:
                _, stored_name = vault.store_file(found)
                return full_tag.replace(src, f"morphism://media/{stored_name}")
            return full_tag

        def _sub_md_img(match: re.Match[str]) -> str:
            alt = match.group(1)
            src = match.group(2).strip()
            if src.startswith(("morphism://", "http://", "https://", "data:")):
                return match.group(0)
            found = self._find_media_file(src, source_dir)
            if found:
                _, stored_name = vault.store_file(found)
                return f'<img src="morphism://media/{stored_name}" alt="{alt}" class="commutative-diagram">'
            return match.group(0)

        t1 = re.sub(r'<img\s+[^>]*?src=["\']([^"\']+)["\'][^>]*?>', _sub_html_img, text, flags=re.IGNORECASE)
        t2 = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _sub_md_img, t1)

        def _sub_image_bracket(m: re.Match[str]) -> str:
            path_cand = self._find_media_file(m.group(1), source_dir)
            if path_cand:
                _, stored_name = vault.store_file(path_cand)
                return f'<img src="morphism://media/{stored_name}" class="commutative-diagram">'
            return m.group(0)

        t3 = re.sub(
            r'\[IMAGE\s+["\']?([^"\'\]]+)["\']?\]',
            _sub_image_bracket,
            t2,
            flags=re.IGNORECASE,
        )
        return t3

    def check_only(self, source: str) -> DSLCompilationResult:
        ast = self.parser.parse(source)
        known_tags = {t.name for t in self.note_repo.list_all_tags(limit=5000)}
        diags = self.validator.validate(ast, known_tags=known_tags)
        return DSLCompilationResult(ast=ast, diagnostics=diags)

    def compile_and_commit(
        self,
        source: str,
        target_course_id: int | None = None,
        auto_layout: bool = True,
        source_dir: Path | str | None = None,
        media_vault: MediaVault | None = None,
    ) -> DSLCompilationResult:
        res = self.check_only(source)
        if res.has_errors:
            return res

        vault = media_vault or self.media_vault
        src_path = Path(source_dir) if source_dir else None

        ast = res.ast
        with UnitOfWork(self.conn):
            course: CourseModel | None = None
            if target_course_id is not None:
                course = self.course_repo.get_by_id(target_course_id)
            if course is None and ast.course_name:
                course = self.course_repo.get_by_name(ast.course_name)
            if course is None:
                folder_id = None
                if ast.folder_path:
                    parts = [p for p in ast.folder_path.replace("\\", "/").split("/") if p.strip()]
                    folder_id = self.folder_repo.ensure_folder_path(parts)
                course = self.course_repo.create(
                    CourseModel(
                        name=ast.course_name or "Compiled DSL Course",
                        folder_id=folder_id,
                        color_hex=ast.color_hex or "#89b4fa",
                        description=ast.description,
                    )
                )

            assert course.id is not None
            res.course_id = course.id

            key_to_note_id: dict[str, int] = {}
            unpositioned_ids: set[int] = set()

            for dsl_note in ast.notes:
                existing: NoteModel | None = None
                if dsl_note.uuid:
                    existing = self.note_repo.get_by_uuid(dsl_note.uuid, include_children=True)
                if existing is None:
                    existing = self.note_repo.get_by_external_key(course.id, dsl_note.external_key)

                mode_enum = NoteReviewMode(dsl_note.mode)
                premise_clean = sanitize_math_html(self._process_media_text(dsl_note.premise, src_path, vault))

                if existing is None:
                    cards = [
                        CardModel(
                            step_order=idx,
                            title=c.title,
                            front_html=sanitize_math_html(self._process_media_text(c.front, src_path, vault)),
                            back_html=sanitize_math_html(self._process_media_text(c.back, src_path, vault)),
                            hint_html=sanitize_math_html(self._process_media_text(c.hint, src_path, vault)),
                        )
                        for idx, c in enumerate(dsl_note.cards)
                    ]
                    px, py = dsl_note.pos if dsl_note.pos is not None else (0.0, 0.0)
                    note_uuid = dsl_note.uuid or generate_uuid()
                    created = self.note_repo.create(
                        NoteModel(
                            uuid=note_uuid,
                            course_id=course.id,
                            external_key=dsl_note.external_key,
                            title=dsl_note.title or dsl_note.external_key,
                            premise_html=premise_clean,
                            pos_x=px,
                            pos_y=py,
                            review_mode=mode_enum,
                            desired_retention=dsl_note.retention,
                            tags=dsl_note.tags,
                            cards=cards,
                        )
                    )
                    assert created.id is not None
                    key_to_note_id[dsl_note.external_key] = created.id
                    key_to_note_id[dsl_note.title] = created.id
                    if dsl_note.pos is None:
                        unpositioned_ids.add(created.id)
                    res.notes_created += 1
                else:
                    assert existing.id is not None
                    existing.title = dsl_note.title or existing.title
                    existing.premise_html = premise_clean
                    existing.review_mode = mode_enum
                    existing.desired_retention = dsl_note.retention
                    existing.tags = dsl_note.tags
                    if dsl_note.pos is not None:
                        existing.pos_x, existing.pos_y = dsl_note.pos

                    new_cards: list[CardModel] = []
                    for idx, dc in enumerate(dsl_note.cards):
                        f_c = sanitize_math_html(self._process_media_text(dc.front, src_path, vault))
                        b_c = sanitize_math_html(self._process_media_text(dc.back, src_path, vault))
                        h_c = sanitize_math_html(self._process_media_text(dc.hint, src_path, vault))
                        if idx < len(existing.cards):
                            ec = existing.cards[idx]
                            ec.step_order = idx
                            ec.title = dc.title
                            ec.front_html = f_c
                            ec.back_html = b_c
                            ec.hint_html = h_c
                            new_cards.append(ec)
                        else:
                            new_cards.append(
                                CardModel(
                                    note_id=existing.id,
                                    step_order=idx,
                                    title=dc.title,
                                    front_html=f_c,
                                    back_html=b_c,
                                    hint_html=h_c,
                                )
                            )
                    existing.cards = new_cards
                    self.note_repo.update(existing, sync_cards=True)
                    self.note_repo.inject_into_course(course.id, existing.id, existing.pos_x, existing.pos_y)
                    if dsl_note.pos is not None:
                        self.note_repo.update_position(existing.id, existing.pos_x, existing.pos_y, course_id=course.id)
                    elif existing.pos_x == 0.0 and existing.pos_y == 0.0:
                        unpositioned_ids.add(existing.id)
                    key_to_note_id[dsl_note.external_key] = existing.id
                    key_to_note_id[dsl_note.title] = existing.id
                    res.notes_updated += 1

            for dsl_note in ast.notes:
                dst_id = key_to_note_id.get(dsl_note.external_key) or key_to_note_id.get(dsl_note.title)
                if dst_id is None:
                    continue
                for dep_key in dsl_note.deps:
                    src_id = key_to_note_id.get(dep_key)
                    if src_id is None:
                        ext_existing = self.note_repo.get_by_external_key(course.id, dep_key)
                        if ext_existing and ext_existing.id is not None:
                            src_id = ext_existing.id
                    if src_id is not None and src_id != dst_id:
                        edge = self.note_repo.create_edge(
                            EdgeModel(course_id=course.id, source_note_id=src_id, target_note_id=dst_id)
                        )
                        if edge is not None:
                            res.edges_created += 1

            if auto_layout and unpositioned_ids:
                all_notes = self.note_repo.list_by_course(course.id, include_children=False)
                all_edges = self.note_repo.list_edges_by_course(course.id)
                computed = LayoutService.compute_layered_layout(
                    note_ids=[n.id for n in all_notes if n.id is not None],
                    edges=[(e.source_note_id, e.target_note_id) for e in all_edges],
                )
                filtered = {nid: xy for nid, xy in computed.items() if nid in unpositioned_ids}
                self.note_repo.update_positions_bulk(filtered, course_id=course.id)

        return res

    @staticmethod
    def decompile_course(
        course: CourseModel,
        notes: list[NoteModel],
        edges: list[EdgeModel],
        folder_path: str = "",
    ) -> str:
        """Decompiles a CourseModel and its notes/edges into the canonical .mdsl format."""
        lines: list[str] = [f'COURSE "{course.name}"']
        if folder_path:
            lines.append(f'FOLDER "{folder_path}"')
        lines.append("")

        id_to_title: dict[int, str] = {}
        for n in notes:
            if n.id is not None:
                id_to_title[n.id] = n.title

        for n in notes:
            lines.append(f'NEW NOTE "{n.title}" UUID {n.uuid}')
            lines.append(f"MODE {n.review_mode.value}")
            if n.tags:
                lines.append(f"TAGS {', '.join(n.tags)}")
            if n.desired_retention is not None:
                lines.append(f"RETENTION {n.desired_retention:.2f}")
            lines.append(f"POS {n.pos_x:.1f}, {n.pos_y:.1f}")
            lines.append("")
            for c_idx, c in enumerate(n.cards, start=1):
                c_title = c.title or f"Card {c_idx}"
                lines.append(f'CARD {c_idx} "{c_title}"')
                lines.append("FRONT")
                lines.append(c.front_html)
                lines.append("BACK")
                lines.append(c.back_html)
                lines.append("")

        if edges:
            lines.append("# Dependency Links")
            for e in edges:
                src_t = id_to_title.get(e.source_note_id)
                dst_t = id_to_title.get(e.target_note_id)
                if src_t and dst_t:
                    lines.append(f'LINK "{src_t}" -> "{dst_t}"')
            lines.append("")

        return "\n".join(lines)
