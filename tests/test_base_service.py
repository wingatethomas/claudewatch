"""Tests for BaseService import constraint enforcement."""

import sys
import types

import pytest

from claudewatch.backend.core.base_service import BaseService


class TestBaseService:
    def test_instantiation(self):
        svc = BaseService()
        assert svc is not None

    def test_subclass_instantiation(self):
        class MyService(BaseService):
            pass

        svc = MyService()
        assert isinstance(svc, BaseService)

    def test_constraint_violation_raises(self):
        """A service that imports a constrained type should fail."""

        # Create a fake base and child in a fake module
        fake_base_mod = types.ModuleType("test_forbidden_base")

        class ForbiddenBase:
            pass

        ForbiddenBase.__module__ = "test_forbidden_base"
        fake_base_mod.ForbiddenBase = ForbiddenBase  # type: ignore[attr-defined]
        sys.modules["test_forbidden_base"] = fake_base_mod

        class ForbiddenChild(ForbiddenBase):
            pass

        ForbiddenChild.__module__ = "test_service_mod"

        fake_svc_mod = types.ModuleType("test_service_mod")
        fake_svc_mod.ForbiddenChild = ForbiddenChild  # type: ignore[attr-defined]
        sys.modules["test_service_mod"] = fake_svc_mod

        try:

            class ConstrainedService(BaseService):
                __import_constraints__ = ("test_forbidden_base.ForbiddenBase",)

            ConstrainedService.__module__ = "test_service_mod"
            ConstrainedService._has_checked = False

            with pytest.raises(ImportError, match="cannot import"):
                ConstrainedService()
        finally:
            del sys.modules["test_forbidden_base"]
            del sys.modules["test_service_mod"]

    def test_no_violation_passes(self):
        """A service with constraints that aren't violated should work fine."""

        class SafeService(BaseService):
            __import_constraints__ = ("nonexistent.module.Fake",)

        svc = SafeService()
        assert svc is not None
