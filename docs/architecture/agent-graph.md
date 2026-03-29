# Agent Relationship Graph

## Problem

Claude Code spawns child agents (subagents, worktree agents) that run as independent processes. ClaudeWatch currently treats every Claude process as a flat, independent session. We need a **graph-based model** that captures relationships between sessions, agents, projects, files, and tools — enabling nested display, cross-session correlation, and deep observability.

## On-Disk Structure

### Session JSONL

Claude Code writes session transcripts to:

```
~/.claude/projects/<proj_key>/<session_id>.jsonl
```

Where `proj_key` encodes the CWD: `/Users/dev/myapp` becomes `-Users-dev-myapp`.

### Subagent Files

When a parent session spawns an agent via the `Agent` tool, the child writes to:

```
~/.claude/projects/<proj_key>/<session_id>/subagents/agent-<agent_id>.jsonl
~/.claude/projects/<proj_key>/<session_id>/subagents/agent-<agent_id>.meta.json
```

The meta file contains:

```json
{
  "agentType": "Explore|general-purpose|claude-code-guide|...",
  "description": "Human-readable task description"
}
```

### Worktree Sessions

Worktree agents create new project directories:

```
~/.claude/projects/-<path>--claude-worktrees-<branch>/<session_id>/
```

These are fully independent session directories with their own `subagents/` trees.

### Transient Session Metadata

While a session is running, Claude writes:

```
~/.claude/sessions/<pid>.json
```

```json
{
  "pid": 86220,
  "sessionId": "f3b24f13-...",
  "cwd": "/Users/dev/myapp",
  "startedAt": 1774720140419,
  "kind": "interactive",
  "entrypoint": "cli"
}
```

Cleaned up on session exit.

### Parent-Child Linking

**In parent JSONL** — Agent tool_use entry:

```json
{
  "message": {
    "role": "assistant",
    "content": [{
      "type": "tool_use",
      "id": "toolu_013PV...",
      "name": "Agent",
      "input": {
        "description": "Analyze auth overlap",
        "subagent_type": "Explore",
        "prompt": "..."
      }
    }]
  },
  "uuid": "de5fb658-...",
  "sessionId": "35d20adc-..."
}
```

**In child JSONL** — entries reference parent:

```json
{
  "parentUuid": "de5fb658-...",
  "sessionId": "35d20adc-...",
  "message": { ... }
}
```

Key: `sessionId` is **shared** between parent and all children. `parentUuid` links to the specific parent message that spawned the child.

## Graph Model

### Node Types

```
Session     — a Claude Code process (interactive or background)
Agent       — a subagent spawned by a session (may itself spawn agents)
Project     — a working directory (CWD) where sessions run
```

### Edge Types

```
Session  --spawns-->    Agent       (parent spawned child)
Agent    --spawns-->    Agent       (agent spawned sub-agent, recursive)
Session  --works_on-->  Project     (session's CWD maps to project)
Agent    --works_on-->  Project     (worktree agents work on different project)
```

### Data Model

```python
@dataclass
class GraphNode:
    id: str                    # session_id, agent_id, or proj_key
    kind: NodeKind             # SESSION | AGENT | PROJECT
    label: str                 # display name
    metadata: dict             # kind-specific data

@dataclass
class GraphEdge:
    source: str                # node id
    target: str                # node id
    kind: EdgeKind             # SPAWNS | WORKS_ON
    metadata: dict             # timing, tool_use_id, etc.

@dataclass
class SessionGraph:
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]

    def children(self, node_id: str) -> list[GraphNode]: ...
    def parent(self, node_id: str) -> GraphNode | None: ...
    def agents_for_session(self, session_id: str) -> list[GraphNode]: ...
    def sessions_for_project(self, proj_key: str) -> list[GraphNode]: ...
    def depth(self, node_id: str) -> int: ...  # 0=session, 1=direct child, 2=grandchild
```

### Building the Graph

1. **Session discovery** (existing detection) gives us running Session nodes
2. **Subagent scan**: for each session, list `<session_id>/subagents/agent-*.jsonl`
3. **Meta enrichment**: read `.meta.json` for agent type + description
4. **Activity detection**: check mtime of each agent JSONL for active/idle
5. **Recursive**: agents can themselves have subagent entries (Agent tool_use in agent JSONL)
6. **Project linking**: CWD from session, worktree path from agent directory name

### Why Not PPID?

Process tree inspection breaks for:
- Worktree agents (detached process trees)
- Agents that outlive their parent
- tmux/screen sessions that reparent to init

JSONL is the source of truth — it's persistent, structured, and captures the full spawn tree regardless of process lifecycle.

## Query Patterns

The graph enables these observability queries:

| Query | Method |
|-------|--------|
| All agents for a session | `graph.children(session_id)` recursively |
| Full spawn tree depth | `graph.depth(agent_id)` |
| Which projects have active agents | Filter nodes by kind=PROJECT, check edges |
| Agent type distribution | Count nodes by `metadata["agent_type"]` |
| Cross-session file overlap | Intersect `files_touched` across session metrics |
| Most active project | Count sessions + agents per project |
| Worktree agent detection | Check project path for `--claude-worktrees-` |

## Integration Points

- **DetectionService**: After finding PIDs, calls GraphService to enrich with child agents
- **MetricsService**: Already parses `agent_spawns` — graph adds the topology
- **Menu display**: Nested agents under parent sessions
- **Insights pane**: Agent topology visualization, project-level aggregation
- **Future**: Real-time agent tree in Activity window
