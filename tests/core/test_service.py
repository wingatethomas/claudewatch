"""Tests for BaseService."""

from claudewatch.backend.core.service import BaseService


class TestBaseService:
    def test_can_instantiate(self):
        svc = BaseService()
        assert isinstance(svc, BaseService)

    def test_subclass_inherits(self):
        class MyService(BaseService):
            pass

        svc = MyService()
        assert isinstance(svc, BaseService)
