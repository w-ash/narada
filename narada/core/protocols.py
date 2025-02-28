"""Protocol definitions for type checking."""

from typing import Any, ClassVar, Protocol

from sqlalchemy.orm import Mapped


class ModelClass(Protocol):
    """Protocol for database model classes."""

    # Instance attributes
    id: Mapped[int]
    is_deleted: Mapped[bool]

    # Class attribute - this is what SQLAlchemy expects
    __mapper__: ClassVar[Any]


class MappingTable(Protocol):
    """Protocol for mapping tables."""

    connector_name: Mapped[str]
    connector_id: Mapped[str]
