"""Base service class with import constraint enforcement."""

import importlib


class ImportConstraint:
    """Enforces that service modules don't import forbidden types.

    Subclasses define __import_constraints__ as a tuple of fully-qualified
    class names (e.g. 'module.ClassName'). On first instantiation, the
    service's module namespace is checked — if any imported type is a
    subclass of a constrained type, ImportError is raised.
    """

    __import_constraints__: tuple[str, ...] = ()
    _has_checked: bool = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls._has_checked = False

    def __init__(self) -> None:
        cls = type(self)
        if not cls._has_checked:
            module = importlib.import_module(cls.__module__)
            for obj in module.__dict__.values():
                if isinstance(obj, type):
                    for fqdn in cls.__import_constraints__:
                        mod_name, class_name = fqdn.rsplit(".", 1)
                        try:
                            constraint_mod = importlib.import_module(mod_name)
                            constraint_cls = getattr(constraint_mod, class_name)
                            if issubclass(obj, constraint_cls):
                                raise ImportError(
                                    f"Service {cls.__module__}.{cls.__name__} "
                                    f"cannot import {obj.__module__}.{obj.__name__}"
                                )
                        except (ModuleNotFoundError, AttributeError):
                            pass
            cls._has_checked = True


class BaseService(ImportConstraint):
    """Base class for all services.

    Constraints enforced at instantiation:
        - Cannot import UI modules
        - View layer depends on services, never the reverse
    """

    __import_constraints__: tuple[str, ...] = ()
