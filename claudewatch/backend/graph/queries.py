"""Graph queries — Cypher queries returning typed dataclasses."""

from __future__ import annotations

import logging

import kuzu

from claudewatch.backend.graph.models import (
    ActionStep,
    BehaviorResult,
    FileHistoryResult,
    HotspotResult,
    ImpactResult,
    PRImpactResult,
    ProjectGraphResult,
    RelatedSessionResult,
    WorkflowPattern,
)

log = logging.getLogger("claudewatch")


class GraphQueries:
    """All graph read queries via Cypher."""

    def __init__(self, conn: kuzu.Connection) -> None:
        self._conn = conn

    def cascading_impact(self, action_id: str, _depth: int = 3) -> ImpactResult:
        """What are the downstream effects of this edit?"""
        result = self._safe_execute(
            "MATCH (a:Action {kind: 'edit', id: $id})-[:MODIFIES]->(fn:Symbol) "
            "OPTIONAL MATCH (fn)<-[:CALLS*1..3]-(caller:Symbol) "
            "RETURN fn.name AS changed, collect(DISTINCT caller.qualified_name) AS impacted",
            {"id": action_id},
        )
        if not result or not result.has_next():
            return ImpactResult(changed="", impacted=[])
        row = result.get_next()
        return ImpactResult(
            changed=row[0] or "",
            impacted=[x for x in (row[1] or []) if x],
        )

    def intent_chain(self, session_id: str) -> list[ActionStep]:
        """Trace the full action sequence for a session."""
        result = self._safe_execute(
            "MATCH (s:Session {id: $id})-[:PERFORMS]->(a:Action) "
            "RETURN a.kind, a.file_path, a.timestamp "
            "ORDER BY a.timestamp",
            {"id": session_id},
        )
        if not result:
            return []
        steps = []
        while result.has_next():
            row = result.get_next()
            steps.append(
                ActionStep(
                    kind=row[0] or "",
                    file_path=row[1] or "",
                    timestamp=row[2] or "",
                )
            )
        return steps

    def function_hotspots(self, project: str, limit: int = 20) -> list[HotspotResult]:
        """Which functions are being edited most?"""
        result = self._safe_execute(
            "MATCH (a:Action {kind: 'edit'})-[:MODIFIES]->(fn:Symbol) "
            "MATCH (fn)<-[:DEFINES]-(f:File)-[:HAS_FILE]-(p:Project {path: $proj}) "
            "RETURN fn.qualified_name, f.path, count(a) AS edits "
            "ORDER BY edits DESC LIMIT $lim",
            {"proj": project, "lim": limit},
        )
        if not result:
            return []
        hotspots = []
        while result.has_next():
            row = result.get_next()
            hotspots.append(
                HotspotResult(
                    qualified_name=row[0] or "",
                    file_path=row[1] or "",
                    edits=row[2],
                )
            )
        return hotspots

    def related_sessions(self, session_id: str) -> list[RelatedSessionResult]:
        """What other sessions touched the same code?"""
        result = self._safe_execute(
            "MATCH (s1:Session {id: $id})-[:PERFORMS]->(a1:Action)-[:MODIFIES]->(fn:Symbol)"
            "<-[:MODIFIES]-(a2:Action)<-[:PERFORMS]-(s2:Session) "
            "WHERE s1 <> s2 "
            "RETURN s2.id, s2.branch, collect(DISTINCT fn.name) AS shared",
            {"id": session_id},
        )
        if not result:
            return []
        sessions = []
        while result.has_next():
            row = result.get_next()
            sessions.append(
                RelatedSessionResult(
                    session_id=row[0] or "",
                    branch=row[1] or "",
                    shared_symbols=[x for x in (row[2] or []) if x],
                )
            )
        return sessions

    def agent_behavior(self, agent_type: str) -> list[BehaviorResult]:
        """How do different agent types use tools?"""
        result = self._safe_execute(
            "MATCH (s:Session)-[:SPAWNS]->(ag:Agent {agent_type: $type}) "
            "MATCH (s)-[:PERFORMS]->(a:Action) "
            "RETURN a.kind, count(*) AS frequency ORDER BY frequency DESC",
            {"type": agent_type},
        )
        if not result:
            return []
        behaviors = []
        while result.has_next():
            row = result.get_next()
            behaviors.append(BehaviorResult(kind=row[0] or "", frequency=row[1]))
        return behaviors

    def project_graph(self, project: str) -> ProjectGraphResult:
        """Counts of graph entities for a project."""
        files = self._count(
            "MATCH (p:Project {path: $proj})-[:HAS_FILE]->(f:File) RETURN count(f)",
            {"proj": project},
        )
        symbols = self._count(
            "MATCH (p:Project {path: $proj})-[:HAS_FILE]->(f:File)-[:DEFINES]->(s:Symbol) RETURN count(s)",
            {"proj": project},
        )
        sessions = self._count(
            "MATCH (s:Session)-[:IN_PROJECT]->(p:Project {path: $proj}) RETURN count(s)",
            {"proj": project},
        )
        actions = self._count(
            "MATCH (s:Session)-[:IN_PROJECT]->(p:Project {path: $proj}), (s)-[:PERFORMS]->(a:Action) RETURN count(a)",
            {"proj": project},
        )
        return ProjectGraphResult(files=files, symbols=symbols, sessions=sessions, actions=actions)

    def pr_blast_radius(self, pr_number: int) -> PRImpactResult:
        """What does this PR actually touch?"""
        result = self._safe_execute(
            "MATCH (s:Session)-[:REFERENCES]->(pr:PR {number: $num}) "
            "MATCH (s)-[:PERFORMS]->(a:Action {kind: 'edit'})-[:MODIFIES]->(fn:Symbol) "
            "OPTIONAL MATCH (fn)<-[:CALLS*0..2]-(dep:Symbol) "
            "RETURN fn.name AS changed, collect(DISTINCT dep.qualified_name) AS deps",
            {"num": pr_number},
        )
        if not result:
            return PRImpactResult()
        changed = []
        dependents = set()
        while result.has_next():
            row = result.get_next()
            if row[0]:
                changed.append(row[0])
            for d in row[1] or []:
                if d:
                    dependents.add(d)
        return PRImpactResult(changed=changed, dependents=list(dependents))

    def workflow_patterns(self, project: str, limit: int = 10) -> list[WorkflowPattern]:
        """What's the typical action sequence?"""
        result = self._safe_execute(
            "MATCH (a1:Action)-[:NEXT]->(a2:Action) "
            "MATCH (s:Session)-[:PERFORMS]->(a1) "
            "MATCH (s)-[:IN_PROJECT]->(p:Project {path: $proj}) "
            "RETURN a1.kind AS first, a2.kind AS then, count(*) AS frequency "
            "ORDER BY frequency DESC LIMIT $lim",
            {"proj": project, "lim": limit},
        )
        if not result:
            return []
        patterns = []
        while result.has_next():
            row = result.get_next()
            patterns.append(
                WorkflowPattern(
                    first=row[0] or "",
                    then=row[1] or "",
                    frequency=row[2],
                )
            )
        return patterns

    def file_history(self, file_path: str) -> list[FileHistoryResult]:
        """All actions targeting a specific file."""
        result = self._safe_execute(
            "MATCH (a:Action)-[:TARGETS]->(f:File {path: $fp}) "
            "MATCH (s:Session)-[:PERFORMS]->(a) "
            "RETURN s.id, a.kind, a.timestamp ORDER BY a.timestamp",
            {"fp": file_path},
        )
        if not result:
            return []
        history = []
        while result.has_next():
            row = result.get_next()
            history.append(
                FileHistoryResult(
                    session_id=row[0] or "",
                    action_kind=row[1] or "",
                    timestamp=row[2] or "",
                )
            )
        return history

    def sessions_for_symbol(self, symbol_name: str) -> list[str]:
        """Which sessions modified a given symbol?"""
        result = self._safe_execute(
            "MATCH (s:Session)-[:PERFORMS]->(a:Action)-[:MODIFIES]->(sym:Symbol {name: $name}) RETURN DISTINCT s.id",
            {"name": symbol_name},
        )
        if not result:
            return []
        sessions = []
        while result.has_next():
            sessions.append(result.get_next()[0])
        return sessions

    def _count(self, query: str, params: dict[str, object]) -> int:
        result = self._safe_execute(query, params)
        if not result or not result.has_next():
            return 0
        return result.get_next()[0] or 0

    def _safe_execute(self, query: str, params: dict[str, object] | None = None) -> kuzu.QueryResult | None:
        try:
            return self._conn.execute(query, params or {})
        except RuntimeError:
            log.debug("graph query failed: %s", query[:80])
            return None
