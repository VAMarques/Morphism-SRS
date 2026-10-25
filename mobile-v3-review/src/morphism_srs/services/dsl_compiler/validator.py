from __future__ import annotations

from dataclasses import dataclass

from morphism_srs.services.dsl_compiler.parser import DSLCourseAST


@dataclass
class DSLDiagnostic:
    severity: str  # "error" | "warning"
    line_num: int
    message: str


class DSLValidator:
    """Validates a DSLCourseAST for duplicate keys, valid modes, non-empty cards, and DAG cycles."""

    VALID_MODES = {"standard", "serial", "cloze"}

    def validate(self, ast: DSLCourseAST, known_tags: set[str] | None = None) -> list[DSLDiagnostic]:
        diagnostics: list[DSLDiagnostic] = []
        seen_keys: dict[str, int] = {}

        for note in ast.notes:
            if note.external_key in seen_keys:
                diagnostics.append(
                    DSLDiagnostic(
                        severity="error",
                        line_num=note.line_num,
                        message=f"Duplicate @note key '{note.external_key}' (first defined at line {seen_keys[note.external_key]}).",
                    )
                )
            else:
                seen_keys[note.external_key] = note.line_num

            if note.mode not in self.VALID_MODES:
                diagnostics.append(
                    DSLDiagnostic(
                        severity="error",
                        line_num=note.line_num,
                        message=f"Invalid review mode '{note.mode}' in note '{note.external_key}'. Must be standard, serial, or cloze.",
                    )
                )

            if not note.cards:
                diagnostics.append(
                    DSLDiagnostic(
                        severity="error",
                        line_num=note.line_num,
                        message=f"Note '{note.external_key}' has no cards.",
                    )
                )
            else:
                for c in note.cards:
                    if not c.front.strip() and not c.back.strip():
                        diagnostics.append(
                            DSLDiagnostic(
                                severity="warning",
                                line_num=c.line_num,
                                message=f"Card step {c.step_order + 1} in note '{note.external_key}' has empty FRONT and BACK.",
                            )
                        )

            if known_tags is not None:
                for t in note.tags:
                    if t not in known_tags:
                        diagnostics.append(
                            DSLDiagnostic(
                                severity="warning",
                                line_num=note.line_num,
                                message=f"Custom tag '{t}' is not in tags_default.csv (it will be created automatically).",
                            )
                        )

        adj: dict[str, list[str]] = {n.external_key: [] for n in ast.notes}
        note_lines: dict[str, int] = {n.external_key: n.line_num for n in ast.notes}

        for note in ast.notes:
            for dep in note.deps:
                if dep == note.external_key:
                    diagnostics.append(
                        DSLDiagnostic(
                            severity="error",
                            line_num=note.line_num,
                            message=f"Self-dependency on note '{note.external_key}' is not allowed.",
                        )
                    )
                elif dep not in adj:
                    diagnostics.append(
                        DSLDiagnostic(
                            severity="warning",
                            line_num=note.line_num,
                            message=f"Dependency '{dep}' referenced by '{note.external_key}' is not defined in this DSL file.",
                        )
                    )
                else:
                    adj[dep].append(note.external_key)

        visited: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done

        def _dfs(u: str) -> bool:
            visited[u] = 1
            for v in adj.get(u, []):
                state = visited.get(v, 0)
                if state == 1:
                    diagnostics.append(
                        DSLDiagnostic(
                            severity="error",
                            line_num=note_lines.get(v, 1),
                            message=f"Dependency cycle detected involving '{u}' -> '{v}'.",
                        )
                    )
                    return True
                if state == 0 and _dfs(v):
                    return True
            visited[u] = 2
            return False

        for k in adj:
            if visited.get(k, 0) == 0:
                _dfs(k)

        return diagnostics
