"""Graph data models — nodes, edges, enums, and DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from claudewatch.backend.core.dto import BaseDTO


class NodeKind(Enum):
    SESSION = "session"
    AGENT = "agent"


class EdgeKind(Enum):
    SPAWNS = "spawns"


# ---------------------------------------------------------------------------
# Scanner DTOs — returned by SubagentScanner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScannedAgentDTO(BaseDTO):
    """Raw agent info extracted from disk by SubagentScanner."""

    agent_id: str
    agent_type: str
    description: str
    parent_uuid: str
    session_id: str
    jsonl_path: str
    last_active: float  # mtime of JSONL file


@dataclass(frozen=True)
class WorktreeProjectDTO(BaseDTO):
    """A worktree project directory detected by SubagentScanner."""

    proj_key: str
    branch: str


# ---------------------------------------------------------------------------
# Graph DTOs — returned by AgentGraphService
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionNodeDTO(BaseDTO):
    """A session node in the graph."""

    session_id: str
    proj_key: str
    kind: NodeKind = NodeKind.SESSION


@dataclass(frozen=True)
class AgentNodeDTO(BaseDTO):
    """An agent node in the graph."""

    agent_id: str
    agent_type: str
    description: str
    parent_uuid: str
    session_id: str
    last_active: float
    kind: NodeKind = NodeKind.AGENT


@dataclass(frozen=True)
class GraphEdgeDTO(BaseDTO):
    """An edge in the graph."""

    source: str
    target: str
    kind: EdgeKind


@dataclass
class SessionGraph:
    """Graph of a single session and its agents."""

    session_node: SessionNodeDTO
    agent_nodes: list[AgentNodeDTO] = field(default_factory=list)
    edges: list[GraphEdgeDTO] = field(default_factory=list)

    @property
    def agent_count(self) -> int:
        return len(self.agent_nodes)

    def children_of(self, node_id: str) -> list[AgentNodeDTO]:
        """Get direct children of a node."""
        child_ids = {e.target for e in self.edges if e.source == node_id and e.kind == EdgeKind.SPAWNS}
        return [a for a in self.agent_nodes if a.agent_id in child_ids]

    def parent_of(self, agent_id: str) -> SessionNodeDTO | AgentNodeDTO | None:
        """Get parent of an agent node."""
        for edge in self.edges:
            if edge.target == agent_id and edge.kind == EdgeKind.SPAWNS:
                if edge.source == self.session_node.session_id:
                    return self.session_node
                for agent in self.agent_nodes:
                    if agent.agent_id == edge.source:
                        return agent
        return None


@dataclass
class ProjectGraph:
    """Graph of all sessions and agents for a project."""

    proj_key: str
    session_graphs: list[SessionGraph] = field(default_factory=list)
    worktree_branches: list[str] = field(default_factory=list)

    @property
    def session_nodes(self) -> list[SessionNodeDTO]:
        return [sg.session_node for sg in self.session_graphs]

    @property
    def worktree_count(self) -> int:
        return len(self.worktree_branches)
