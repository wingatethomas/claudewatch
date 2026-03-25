"""Tests for scripts/audit_imports.py."""

import textwrap
from pathlib import Path
from unittest.mock import patch

from scripts.audit_imports import (
    _classify,
    _extract_imports,
    _is_violation,
    _module_name,
    build_graph,
    compute_fan_in,
    compute_fan_out,
    find_cycles,
    find_violations,
    main,
    max_import_depth,
)


class TestClassify:
    def test_core_module(self):
        assert _classify("claudewatch.backend.core.models") == "core"

    def test_core_services_process(self):
        assert _classify("claudewatch.backend.core.process.service") == "core/services"

    def test_core_services_session_log(self):
        assert _classify("claudewatch.backend.core.session_log.service") == "core/services"

    def test_domain_detection(self):
        assert _classify("claudewatch.backend.detection.service") == "domain"

    def test_domain_summary(self):
        assert _classify("claudewatch.backend.summary.service") == "domain"

    def test_ui(self):
        assert _classify("claudewatch.ui.menubar") == "ui"

    def test_other(self):
        assert _classify("claudewatch.__main__") == "other"

    def test_bare_package(self):
        assert _classify("claudewatch") == "other"


class TestIsViolation:
    def test_core_importing_domain_is_violation(self):
        assert _is_violation("core", "domain") is True

    def test_core_importing_ui_is_violation(self):
        assert _is_violation("core", "ui") is True

    def test_domain_importing_core_is_ok(self):
        assert _is_violation("domain", "core") is False

    def test_domain_importing_ui_is_violation(self):
        assert _is_violation("domain", "ui") is True



class TestExtractImports:
    def test_extracts_from_import(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(
            textwrap.dedent("""\
                from claudewatch.backend.core.models import ClaudeSession
                import os
            """)
        )
        result = _extract_imports(f)
        assert result == ["claudewatch.backend.core.models"]

    def test_extracts_import_statement(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("import claudewatch.backend.core.helpers\n")
        result = _extract_imports(f)
        assert result == ["claudewatch.backend.core.helpers"]

    def test_ignores_non_internal(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("import os\nfrom pathlib import Path\n")
        result = _extract_imports(f)
        assert result == []

    def test_handles_syntax_error(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n")
        result = _extract_imports(f)
        assert result == []


class TestModuleName:
    def test_regular_module(self, tmp_path):
        # Simulate repo root structure
        pkg = tmp_path / "claudewatch" / "backend" / "core"
        pkg.mkdir(parents=True)
        f = pkg / "models.py"
        f.touch()
        with patch("scripts.audit_imports.REPO_ROOT", tmp_path):
            assert _module_name(f) == "claudewatch.backend.core.models"

    def test_init_file(self, tmp_path):
        pkg = tmp_path / "claudewatch" / "backend"
        pkg.mkdir(parents=True)
        f = pkg / "__init__.py"
        f.touch()
        with patch("scripts.audit_imports.REPO_ROOT", tmp_path):
            assert _module_name(f) == "claudewatch.backend"


class TestBuildGraph:
    def test_builds_graph(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        a = pkg / "a.py"
        a.write_text("from claudewatch.backend.core.models import X\n")
        b = pkg / "b.py"
        b.write_text("")
        with patch("scripts.audit_imports.REPO_ROOT", tmp_path):
            graph = build_graph(pkg)
        assert len(graph) == 2


class TestFindViolations:
    def test_detects_core_to_domain_violation(self):
        graph = {
            "claudewatch.backend.core.models": ["claudewatch.backend.detection.service"],
        }
        violations = find_violations(graph)
        assert len(violations) == 1
        assert violations[0]["from_layer"] == "core"
        assert violations[0]["to_layer"] == "domain"

    def test_no_violation_for_allowed_import(self):
        graph = {
            "claudewatch.backend.detection.service": ["claudewatch.backend.core.models"],
        }
        violations = find_violations(graph)
        assert len(violations) == 0


class TestMetrics:
    def test_fan_out(self):
        graph = {"a": ["b", "c", "b"], "b": ["c"], "c": []}
        fan_out = compute_fan_out(graph)
        assert fan_out["a"] == 2  # deduplicated
        assert fan_out["c"] == 0

    def test_fan_in(self):
        graph = {"a": ["b", "c"], "b": ["c"], "c": []}
        fan_in = compute_fan_in(graph)
        assert fan_in["c"] == 2
        assert fan_in["b"] == 1

    def test_no_cycles(self):
        graph = {"a": ["b"], "b": ["c"], "c": []}
        cycles = find_cycles(graph)
        assert cycles == []

    def test_detects_cycle(self):
        graph = {"a": ["b"], "b": ["a"]}
        cycles = find_cycles(graph)
        assert len(cycles) > 0

    def test_max_depth(self):
        graph = {"a": ["b"], "b": ["c"], "c": []}
        assert max_import_depth(graph) == 2

    def test_max_depth_no_edges(self):
        graph = {"a": [], "b": []}
        assert max_import_depth(graph) == 0


class TestMain:
    def test_check_mode_clean(self):
        with (
            patch("scripts.audit_imports.PACKAGE_ROOT", Path("/nonexistent")),
            patch("scripts.audit_imports.build_graph", return_value={}),
        ):
            result = main(["--check"])
        assert result == 0

    def test_check_mode_with_violations(self):
        fake_graph = {
            "claudewatch.backend.core.models": ["claudewatch.backend.detection.service"],
        }
        with patch("scripts.audit_imports.build_graph", return_value=fake_graph):
            result = main(["--check"])
        assert result == 1

    def test_graph_mode(self, capsys):
        fake_graph = {
            "claudewatch.backend.core.models": ["claudewatch.backend.core.helpers"],
        }
        with patch("scripts.audit_imports.build_graph", return_value=fake_graph):
            result = main(["--graph"])
        assert result == 0
        out = capsys.readouterr().out
        assert "Dependency Graph" in out
