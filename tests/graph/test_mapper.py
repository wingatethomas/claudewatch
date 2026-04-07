"""Tests for EditMapper — linking edit actions to symbols."""

import os

import pytest

from claudewatch.backend.graph.models import GraphStore
from claudewatch.backend.graph.repository import CodeETL, EditMapper


@pytest.fixture
def store(tmp_path: str) -> GraphStore:
    return GraphStore(os.path.join(tmp_path, "graph.kuzu"))


@pytest.fixture
def mapper(store: GraphStore) -> EditMapper:
    return EditMapper(store.conn)


@pytest.fixture
def indexed_project(store: GraphStore, tmp_path: str) -> str:
    """Create a project with indexed symbols."""
    project_dir = os.path.join(tmp_path, "project")
    os.makedirs(project_dir)
    main_py = os.path.join(project_dir, "main.py")
    with open(main_py, "w") as f:
        f.write("""def greet(name):
    return f"Hello, {name}"

def farewell(name):
    return f"Goodbye, {name}"
""")
    # Create file node and index
    store.conn.execute(
        "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
        {"path": main_py, "proj": project_dir},
    )
    etl = CodeETL(store.conn)
    etl.index_file(main_py, project_dir)
    return main_py


class TestEditMapper:
    def test_maps_edit_to_symbol(self, mapper: EditMapper, store: GraphStore, indexed_project: str) -> None:
        # Create an edit action targeting the greet function
        store.conn.execute(
            "CREATE (a:Action {id: 'edit-1', kind: 'edit', session_id: 's1', "
            "file_path: $fp, timestamp: '2026-01-01', old_text: '', "
            "new_text: 'return f\"Hello, {name}\"', pattern: '', command: '', description: ''})",
            {"fp": indexed_project},
        )
        count = mapper.map_all()
        assert count == 1

        # Verify MODIFIES edge was created
        result = store.conn.execute("MATCH (a:Action {id: 'edit-1'})-[:MODIFIES]->(sym:Symbol) RETURN sym.name")
        assert result.has_next()
        assert result.get_next()[0] == "greet"

    def test_skips_already_mapped(self, mapper: EditMapper, store: GraphStore, indexed_project: str) -> None:
        store.conn.execute(
            "CREATE (a:Action {id: 'edit-2', kind: 'edit', session_id: 's1', "
            "file_path: $fp, timestamp: '2026-01-01', old_text: '', "
            "new_text: 'return f\"Goodbye, {name}\"', pattern: '', command: '', description: ''})",
            {"fp": indexed_project},
        )
        count1 = mapper.map_all()
        assert count1 == 1
        count2 = mapper.map_all()
        assert count2 == 0  # already mapped

    def test_handles_no_match(self, mapper: EditMapper, store: GraphStore, indexed_project: str) -> None:
        store.conn.execute(
            "CREATE (a:Action {id: 'edit-3', kind: 'edit', session_id: 's1', "
            "file_path: $fp, timestamp: '2026-01-01', old_text: '', "
            "new_text: 'completely unique text not in file', pattern: '', command: '', description: ''})",
            {"fp": indexed_project},
        )
        count = mapper.map_all()
        assert count == 0

    def test_prefers_innermost_symbol(self, mapper: EditMapper, store: GraphStore, tmp_path: str) -> None:
        # Create a file with nested symbols
        project_dir = os.path.join(tmp_path, "nested_proj")
        os.makedirs(project_dir)
        nested_py = os.path.join(project_dir, "nested.py")
        with open(nested_py, "w") as f:
            f.write("""class MyClass:
    def inner_method(self):
        return "inside"
""")
        store.conn.execute(
            "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
            {"path": nested_py, "proj": project_dir},
        )
        etl = CodeETL(store.conn)
        etl.index_file(nested_py, project_dir)

        store.conn.execute(
            "CREATE (a:Action {id: 'edit-4', kind: 'edit', session_id: 's1', "
            "file_path: $fp, timestamp: '2026-01-01', old_text: '', "
            "new_text: 'return \"inside\"', pattern: '', command: '', description: ''})",
            {"fp": nested_py},
        )
        count = mapper.map_all()
        assert count == 1

        result = store.conn.execute(
            "MATCH (a:Action {id: 'edit-4'})-[:MODIFIES]->(sym:Symbol) RETURN sym.name, sym.kind"
        )
        assert result.has_next()
        row = result.get_next()
        # Should map to inner_method (innermost), not MyClass
        assert row[0] == "inner_method"

    def test_no_edits_returns_zero(self, mapper: EditMapper) -> None:
        assert mapper.map_all() == 0
