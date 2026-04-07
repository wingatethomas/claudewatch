"""Tests for CodeETL — AST parsing into graph nodes."""

import os

import pytest

from claudewatch.backend.graph.models import GraphStore
from claudewatch.backend.graph.repository import CodeETL


@pytest.fixture
def store(tmp_path: str) -> GraphStore:
    return GraphStore(os.path.join(tmp_path, "graph.kuzu"))


@pytest.fixture
def etl(store: GraphStore) -> CodeETL:
    return CodeETL(store.conn)


@pytest.fixture
def sample_project(tmp_path: str) -> str:
    project_dir = os.path.join(tmp_path, "myproject")
    os.makedirs(project_dir)

    # Create a Python file with functions and classes
    with open(os.path.join(project_dir, "main.py"), "w") as f:
        f.write("""
def greet(name):
    return f"Hello, {name}"

def farewell(name):
    msg = greet(name)
    return f"Goodbye after {msg}"

class UserService:
    def get_user(self, user_id):
        return {"id": user_id}

    def delete_user(self, user_id):
        user = self.get_user(user_id)
        return user
""")

    # Create a second file that imports from main
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write("""
from main import greet

def run():
    print(greet("world"))
""")

    return project_dir


class TestCodeETL:
    def test_index_file_creates_symbols(self, etl: CodeETL, store: GraphStore, sample_project: str) -> None:
        main_py = os.path.join(sample_project, "main.py")
        # First create the file node
        store.conn.execute(
            "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
            {"path": main_py, "proj": sample_project},
        )
        count = etl.index_file(main_py, sample_project)
        assert count >= 4  # greet, farewell, UserService, get_user, delete_user

    def test_functions_have_signatures(self, etl: CodeETL, store: GraphStore, sample_project: str) -> None:
        main_py = os.path.join(sample_project, "main.py")
        store.conn.execute(
            "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
            {"path": main_py, "proj": sample_project},
        )
        etl.index_file(main_py, sample_project)
        result = store.conn.execute(
            "MATCH (sym:Symbol {kind: 'function'}) WHERE sym.name = 'greet' RETURN sym.signature"
        )
        assert result.has_next()
        sig = result.get_next()[0]
        assert "name" in sig

    def test_class_node_created(self, etl: CodeETL, store: GraphStore, sample_project: str) -> None:
        main_py = os.path.join(sample_project, "main.py")
        store.conn.execute(
            "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
            {"path": main_py, "proj": sample_project},
        )
        etl.index_file(main_py, sample_project)
        result = store.conn.execute("MATCH (sym:Symbol {kind: 'class'}) RETURN sym.name")
        assert result.has_next()
        assert result.get_next()[0] == "UserService"

    def test_defines_edges(self, etl: CodeETL, store: GraphStore, sample_project: str) -> None:
        main_py = os.path.join(sample_project, "main.py")
        store.conn.execute(
            "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
            {"path": main_py, "proj": sample_project},
        )
        etl.index_file(main_py, sample_project)
        result = store.conn.execute("MATCH (f:File)-[:DEFINES]->(sym:Symbol) RETURN count(sym)")
        assert result.get_next()[0] >= 4

    def test_calls_edges(self, etl: CodeETL, store: GraphStore, sample_project: str) -> None:
        main_py = os.path.join(sample_project, "main.py")
        store.conn.execute(
            "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
            {"path": main_py, "proj": sample_project},
        )
        etl.index_file(main_py, sample_project)
        # farewell calls greet
        result = store.conn.execute(
            "MATCH (caller:Symbol)-[:CALLS]->(callee:Symbol) "
            "WHERE caller.name = 'farewell' AND callee.name = 'greet' "
            "RETURN count(*)"
        )
        assert result.get_next()[0] >= 1

    def test_index_project(self, etl: CodeETL, store: GraphStore, sample_project: str) -> None:
        # Pre-create file nodes
        for fname in ["main.py", "app.py"]:
            fpath = os.path.join(sample_project, fname)
            store.conn.execute(
                "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
                {"path": fpath, "proj": sample_project},
            )
        total = etl.index_project(sample_project)
        assert total >= 5  # greet, farewell, UserService, get_user, delete_user, run

    def test_skips_non_python(self, etl: CodeETL, tmp_path: str) -> None:
        js_file = os.path.join(tmp_path, "index.js")
        with open(js_file, "w") as f:
            f.write("console.log('hello')")
        assert etl.index_file(js_file, str(tmp_path)) == 0

    def test_hash_based_skip(self, etl: CodeETL, store: GraphStore, sample_project: str) -> None:
        main_py = os.path.join(sample_project, "main.py")
        store.conn.execute(
            "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
            {"path": main_py, "proj": sample_project},
        )
        count1 = etl.index_file(main_py, sample_project)
        assert count1 > 0
        count2 = etl.index_file(main_py, sample_project)
        assert count2 == 0  # hash unchanged, skip

    def test_handles_syntax_error(self, etl: CodeETL, store: GraphStore, tmp_path: str) -> None:
        bad_py = os.path.join(tmp_path, "bad.py")
        with open(bad_py, "w") as f:
            f.write("def broken(:\n  pass")
        store.conn.execute(
            "CREATE (f:File {path: $path, project: $proj, language: 'python', hash: '', lines: 0})",
            {"path": bad_py, "proj": str(tmp_path)},
        )
        assert etl.index_file(bad_py, str(tmp_path)) == 0
