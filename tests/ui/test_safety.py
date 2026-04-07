"""Tests for claudewatch.ui.safety — crash-proof decorators and helpers."""

from unittest.mock import MagicMock

from claudewatch.ui.safety import get_represented_object, objc_callback, objc_callback_with_default


class TestObjcCallback:
    def test_passes_through_return_value(self) -> None:
        @objc_callback
        def fn() -> str:
            return "ok"

        assert fn() == "ok"

    def test_returns_none_on_exception(self) -> None:
        @objc_callback
        def fn() -> str:
            msg = "boom"
            raise ValueError(msg)

        assert fn() is None

    def test_logs_exception(self) -> None:
        @objc_callback
        def fn() -> None:
            msg = "boom"
            raise RuntimeError(msg)

        # Should not raise
        fn()


class TestObjcCallbackWithDefault:
    def test_returns_default_on_exception(self) -> None:
        @objc_callback_with_default(0)
        def fn() -> int:
            msg = "boom"
            raise ValueError(msg)

        assert fn() == 0

    def test_returns_empty_string_default(self) -> None:
        @objc_callback_with_default("")
        def fn() -> str:
            msg = "boom"
            raise ValueError(msg)

        assert fn() == ""

    def test_passes_through_on_success(self) -> None:
        @objc_callback_with_default(0)
        def fn() -> int:
            return 42

        assert fn() == 42


class TestGetRepresentedObject:
    def test_reads_from_represented_object(self) -> None:
        sender = MagicMock()
        sender.representedObject.return_value = "test_value"
        assert get_represented_object(sender) == "test_value"

    def test_falls_back_to_cell(self) -> None:
        sender = MagicMock()
        sender.representedObject.return_value = None
        sender.cell.return_value.representedObject.return_value = "cell_value"
        assert get_represented_object(sender) == "cell_value"

    def test_falls_back_to_identifier(self) -> None:
        sender = MagicMock()
        sender.representedObject.return_value = None
        sender.cell.return_value.representedObject.return_value = None
        sender.identifier.return_value = "security|config_alerts"
        assert get_represented_object(sender) == "security|config_alerts"

    def test_returns_empty_when_nothing_works(self) -> None:
        sender = MagicMock()
        sender.representedObject.side_effect = AttributeError
        sender.cell.side_effect = AttributeError
        sender.identifier.side_effect = AttributeError
        assert get_represented_object(sender) == ""

    def test_returns_empty_for_none_values(self) -> None:
        sender = MagicMock()
        sender.representedObject.return_value = None
        sender.cell.return_value.representedObject.return_value = None
        sender.identifier.return_value = None
        assert get_represented_object(sender) == ""
