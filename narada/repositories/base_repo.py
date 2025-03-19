"""Repository layer for database operations with SQLAlchemy 2.0 best practices."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar, cast

from attrs import define

from sqlalchemy import Select, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql import ColumnElement

from narada.config import get_logger

# Import needed for relationship chains in eager loading
from narada.database.db_models import DBPlaylistTrack, DBTrack, NaradaDBBase
from narada.repositories.repo_decorator import db_operation

# Common utility functions for repository operations
async def safe_fetch_relationship(db_model: Any, rel_name: str) -> list[Any]:
    """Helper to safely load relationships with fallback to async loading."""
    try:
        items = getattr(db_model, rel_name, [])

        if (
            not items
            and hasattr(db_model, rel_name)
            and hasattr(db_model, "awaitable_attrs")
        ):
            items = await getattr(db_model.awaitable_attrs, rel_name)

        return items
    except (AttributeError, TypeError):
        if hasattr(db_model, "awaitable_attrs") and hasattr(
            db_model.awaitable_attrs,
            rel_name,
        ):
            return await getattr(db_model.awaitable_attrs, rel_name)
        return []

logger = get_logger(__name__)

# Type variables with proper constraints
TDBModel = TypeVar("TDBModel", bound=NaradaDBBase)
TDomainModel = TypeVar("TDomainModel")


class ModelMapper[TDBModel: NaradaDBBase, TDomainModel](Protocol):
    """Protocol for bidirectional mapping between models."""

    @staticmethod
    async def to_domain(db_model: TDBModel) -> TDomainModel:
        """Convert database model to domain model."""
        ...

    @staticmethod
    def to_db(domain_model: TDomainModel) -> TDBModel:
        """Convert domain model to database model."""
        ...
        
        
@define(frozen=True, slots=True)
class BaseModelMapper[TDBModel: NaradaDBBase, TDomainModel]:
    """Base implementation of ModelMapper with common functionality.
    
    This provides a foundation for building domain-specific mappers
    with consistent behavior and reduced boilerplate.
    
    Usage:
        @define(frozen=True, slots=True)
        class UserMapper(BaseModelMapper[DBUser, User]):
            @staticmethod
            async def to_domain(db_model: DBUser) -> User:
                if not db_model:
                    return None
                return User(...)
                
            @staticmethod
            def to_db(domain_model: User) -> DBUser:
                return DBUser(...)
    """
    
    @staticmethod
    async def to_domain(db_model: TDBModel) -> TDomainModel:
        """Default implementation returns None for None input."""
        if not db_model:
            return None
        raise NotImplementedError("Subclasses must implement to_domain")
        
    @staticmethod
    def to_db(domain_model: TDomainModel) -> TDBModel:
        """Default implementation raises NotImplementedError."""
        raise NotImplementedError("Subclasses must implement to_db")


class BaseRepository[TDBModel: NaradaDBBase, TDomainModel]:
    """Base repository for database operations with SQLAlchemy 2.0 best practices."""

    def __init__(
        self,
        session: AsyncSession,
        model_class: type[TDBModel],
        mapper: ModelMapper[TDBModel, TDomainModel],
    ) -> None:
        """Initialize repository with session and model mappings."""
        self.session = session
        self.model_class = model_class
        self.mapper = mapper
        logger.debug(
            f"Initialized {self.__class__.__name__} for {model_class.__name__}",
        )

    # -------------------------------------------------------------------------
    # SELECT STATEMENT BUILDERS
    # -------------------------------------------------------------------------

    def select(self, *columns: Any) -> Select[tuple[Any, ...]]:
        """Create select statement for active records."""
        stmt = select(*columns) if columns else select(self.model_class)
        return stmt.where(self.model_class.is_deleted == False)  # noqa: E712

    def select_by_id(self, id_: int) -> Select[tuple[TDBModel]]:
        """Create select statement for a record by ID."""
        return self.select().where(self.model_class.id == id_)

    def with_relationship(
        self,
        stmt: Select[tuple[TDBModel]],
        *relationships: str | InstrumentedAttribute,
    ) -> Select[tuple[TDBModel]]:
        """Add relationship loading options to select statement."""
        options = []
        for rel in relationships:
            if isinstance(rel, str):
                options.append(selectinload(getattr(self.model_class, rel)))
            else:
                options.append(selectinload(rel))
        return stmt.options(*options)

    # -------------------------------------------------------------------------
    # DIRECT DATABASE OPERATIONS (non-decorated helpers)
    # -------------------------------------------------------------------------

    async def _execute_query(
        self,
        stmt: Select[tuple[TDBModel]],
    ) -> list[TDBModel]:
        """Execute a query and return all results directly."""
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def _execute_query_one(
        self,
        stmt: Select[tuple[TDBModel]],
    ) -> TDBModel | None:
        """Execute a query and return the first result directly."""
        result = await self.session.scalars(stmt)
        return result.first()

    async def _flush_and_refresh(
        self,
        entity: TDBModel,
        load_relationships: bool = True,
    ) -> TDBModel:
        """Flush changes and refresh entity with relationships."""
        await self.session.flush()

        if load_relationships:
            # Get relevant relationships for this model
            relationships = [
                rel
                for rel in ["mappings", "tracks", "playlist_tracks"]
                if hasattr(self.model_class, rel)
            ]

            # Refresh with relationship loading if needed
            if relationships:
                await self.session.refresh(entity, attribute_names=relationships)
            else:
                await self.session.refresh(entity)
        else:
            await self.session.refresh(entity)

        return entity

    # -------------------------------------------------------------------------
    # DECORATED DATABASE OPERATIONS
    # -------------------------------------------------------------------------

    @db_operation("execute_select_one")
    async def execute_select_one(
        self,
        stmt: Select[tuple[TDBModel]],
    ) -> TDBModel | None:
        """Execute select and return first result."""
        try:
            return await self._execute_query_one(stmt)
        except Exception as e:
            if "concurrent operations are not permitted" in str(e):
                # Handle concurrent session access
                logger.warning("Detected concurrent session access, retrying operation")
                await asyncio.sleep(0.1)
                return await self._execute_query_one(stmt)
            raise

    @db_operation("execute_select_many")
    async def execute_select_many(
        self,
        stmt: Select[tuple[TDBModel]],
    ) -> list[TDBModel]:
        """Execute select and return all results."""
        try:
            return await self._execute_query(stmt)
        except Exception as e:
            if "concurrent operations are not permitted" in str(e):
                logger.warning("Detected concurrent session access, retrying operation")
                await asyncio.sleep(0.1)
                return await self._execute_query(stmt)
            raise

    # -------------------------------------------------------------------------
    # CORE CRUD OPERATIONS
    # -------------------------------------------------------------------------

    @db_operation("get_by_id")
    async def get_by_id(
        self,
        id_: int,
        load_relationships: list[str] | None = None,
    ) -> TDomainModel:
        """Get entity by ID with optional relationship loading."""
        # Direct implementation to avoid Pylance issues
        stmt = self.select_by_id(id_)

        if load_relationships:
            stmt = self.with_relationship(stmt, *load_relationships)

        # Execute the query directly to avoid nested decorator calls
        result = await self.session.scalars(stmt)
        db_entity = result.first()

        if not db_entity:
            raise ValueError(f"Entity with ID {id_} not found")

        # Convert to domain model
        domain_entity = await self.mapper.to_domain(db_entity)
        return domain_entity

    @db_operation("find_by")
    async def find_by(
        self,
        conditions: dict[str, Any] | list[ColumnElement],
        load_relationships: list[str] | None = None,
        limit: int | None = None,
    ) -> list[TDomainModel]:
        """Find entities matching conditions."""
        # Build the query
        stmt = self.select()

        # Apply conditions
        match conditions:
            case dict():
                for field, value in conditions.items():
                    stmt = stmt.where(getattr(self.model_class, field) == value)
            case list():
                for condition in conditions:
                    stmt = stmt.where(condition)

        # Apply relationship loading
        if load_relationships:
            stmt = self.with_relationship(stmt, *load_relationships)

        # Apply limit
        if limit is not None:
            stmt = stmt.limit(limit)

        # Execute query directly to avoid nested decorator calls
        result = await self.session.scalars(stmt)
        db_entities = list(result.all())

        # Convert to domain models
        domain_entities = []
        for entity in db_entities:
            domain_entity = await self.mapper.to_domain(entity)
            domain_entities.append(domain_entity)

        return domain_entities

    @db_operation("find_one_by")
    async def find_one_by(
        self,
        conditions: dict[str, Any] | list[ColumnElement],
        load_relationships: list[str] | None = None,
    ) -> TDomainModel | None:
        """Find a single entity matching conditions or None if not found."""
        # Build the query
        stmt = self.select()

        # Apply conditions
        match conditions:
            case dict():
                for field, value in conditions.items():
                    stmt = stmt.where(getattr(self.model_class, field) == value)
            case list():
                for condition in conditions:
                    stmt = stmt.where(condition)

        # Apply relationship loading
        if load_relationships:
            stmt = self.with_relationship(stmt, *load_relationships)

        # Limit to one result
        stmt = stmt.limit(1)

        # Execute query directly to avoid nested decorator calls
        result = await self.session.scalars(stmt)
        db_entity = result.first()

        # Return None if no matching entity
        if not db_entity:
            return None

        # Convert to domain model
        domain_entity = await self.mapper.to_domain(db_entity)
        return domain_entity

    @db_operation("create")
    async def create(self, entity: TDomainModel) -> TDomainModel:
        """Create new entity."""
        # Convert domain to DB model
        db_entity = self.mapper.to_db(entity)

        # Add to session
        self.session.add(db_entity)

        # Flush and refresh to ensure ID is populated with proper typing
        db_entity = await self._flush_and_refresh(db_entity)

        # Verify ID was generated
        if db_entity.id is None:
            logger.error(f"Failed to generate ID for entity: {entity}")
            raise ValueError("Failed to create entity: No ID was generated")

        # Convert back to domain with ID
        domain_entity = await self.mapper.to_domain(db_entity)
        return domain_entity

    @db_operation("update")
    async def update(
        self,
        id_: int,
        updates: dict[str, Any] | TDomainModel,
    ) -> TDomainModel:
        """Update entity using appropriate method based on input type."""
        # Handle dictionary updates
        if isinstance(updates, dict):
            # Add timestamp if not provided
            values = {**updates}
            if "updated_at" not in values:
                values["updated_at"] = datetime.now(UTC)

            # First perform the update operation
            stmt = (
                update(self.model_class)
                .where(
                    self.model_class.id == id_,
                    self.model_class.is_deleted == False,  # noqa: E712
                )
                .values(**values)
            )
            result = await self.session.execute(stmt)

            if result.rowcount == 0:
                raise ValueError(f"Entity with ID {id_} not found or already deleted")

        # Handle domain model updates
        else:
            # Get the existing entity directly
            stmt = self.select_by_id(id_)
            result = await self.session.scalars(stmt)
            existing = result.first()

            if not existing:
                raise ValueError(f"Entity with ID {id_} not found")

            # Get DB representation of the update
            update_db = self.mapper.to_db(updates)

            # Copy non-null fields from update to existing
            for key in [
                k for k in dir(update_db) if not k.startswith("_") and k != "id"
            ]:
                if hasattr(update_db, key) and hasattr(existing, key):
                    value = getattr(update_db, key)
                    if value is not None:  # Only update non-null values
                        setattr(existing, key, value)

            # Update timestamp
            existing.updated_at = datetime.now(UTC)

            # Flag modified fields that use JSON types, which SQLAlchemy might not detect
            flag_modified_attributes = ["connector_metadata", "metadata", "artists"]
            for attr_name in flag_modified_attributes:
                if hasattr(existing, attr_name):
                    flag_modified(existing, attr_name)

            # Flush changes
            await self._flush_and_refresh(existing)

        # For both update types, fetch the full entity with eager loaded relationships
        stmt = self.select_by_id(id_)

        # Add eager loading for common relationship patterns
        if hasattr(self.model_class, "tracks"):
            # For playlists, deeply load all relationships to prevent lazy loading issues
            stmt = stmt.options(
                selectinload(self.model_class.mappings),  # type: ignore
                selectinload(self.model_class.tracks)  # type: ignore
                .selectinload(DBPlaylistTrack.track)
                .selectinload(DBTrack.mappings),
            )
        elif hasattr(self.model_class, "mappings"):
            # For other entities with mappings
            stmt = stmt.options(selectinload(self.model_class.mappings))  # type: ignore

        # Fetch the updated entity directly
        result = await self.session.scalars(stmt)
        db_entity = result.first()

        if not db_entity:
            raise ValueError(f"Entity with ID {id_} not found or already deleted")

        # Convert to domain model
        domain_entity = await self.mapper.to_domain(db_entity)
        return domain_entity

    @db_operation("soft_delete")
    async def soft_delete(self, id_: int) -> int:
        """Soft delete entity by setting is_deleted=True. Returns affected rows."""
        stmt = (
            update(self.model_class)
            .where(
                self.model_class.id == id_,
                self.model_class.is_deleted == False,  # noqa: E712
            )
            .values(
                is_deleted=True,
                deleted_at=datetime.now(UTC),
            )
        )
        result = await self.session.execute(stmt)

        if result.rowcount == 0:
            raise ValueError(f"Entity with ID {id_} not found or already deleted")

        return result.rowcount

    @db_operation("hard_delete")
    async def hard_delete(self, id_: int) -> int:
        """Hard delete entity from database. Returns affected rows."""
        stmt = (
            delete(self.model_class)
            .where(self.model_class.id == id_)
            .returning(self.model_class.id)
        )
        result = await self.session.execute(stmt)
        deleted_ids = result.scalars().all()

        if not deleted_ids:
            raise ValueError(f"Entity with ID {id_} not found")

        return len(deleted_ids)

    # -------------------------------------------------------------------------
    # BATCH OPERATIONS
    # -------------------------------------------------------------------------

    @db_operation("bulk_create")
    async def bulk_create(self, entities: list[TDomainModel]) -> list[TDomainModel]:
        """Bulk create entities using ORM approach."""
        if not entities:
            return []

        # ORM approach for consistency
        db_entities: list[TDBModel] = []
        for entity in entities:
            db_entity = self.mapper.to_db(entity)
            db_entities.append(db_entity)

        # Add all entities to session
        self.session.add_all(db_entities)
        await self.session.flush()

        # Refresh entities to ensure IDs are populated
        for db_entity in db_entities:
            await self._flush_and_refresh(db_entity)

        # Convert back to domain models with IDs
        domain_entities = []
        for e in db_entities:
            domain_entity = await self.mapper.to_domain(e)
            domain_entities.append(domain_entity)

        return domain_entities

    @db_operation("bulk_update")
    async def bulk_update(self, updates: dict[int, dict[str, Any]]) -> int:
        """Bulk update multiple entities. Returns number of updated rows."""
        if not updates:
            return 0

        # Process updates in batches
        total_updated = 0
        now = datetime.now(UTC)

        for entity_id, values in updates.items():
            # Add updated_at timestamp
            if "updated_at" not in values:
                values["updated_at"] = now

            # Run update for this entity
            stmt = (
                update(self.model_class)
                .where(
                    self.model_class.id == entity_id,
                    self.model_class.is_deleted == False,  # noqa: E712
                )
                .values(**values)
                .execution_options(synchronize_session=False)  # Optimize for bulk ops
            )
            result = await self.session.execute(stmt)
            total_updated += result.rowcount

        return total_updated

    @db_operation("bulk_delete")
    async def bulk_delete(self, ids: list[int], hard_delete: bool = False) -> int:
        """Bulk delete multiple entities. Returns number of affected rows."""
        if not ids:
            return 0

        if hard_delete:
            # Use Core DELETE with RETURNING
            stmt = (
                delete(self.model_class)
                .where(self.model_class.id.in_(ids))
                .returning(self.model_class.id)
                .execution_options(synchronize_session=False)
            )
            result = await self.session.execute(stmt)
            deleted_ids = result.scalars().all()
            return len(deleted_ids)
        else:
            # Use Core UPDATE for soft delete
            stmt = (
                update(self.model_class)
                .where(
                    self.model_class.id.in_(ids),
                    self.model_class.is_deleted == False,  # noqa: E712
                )
                .values(
                    is_deleted=True,
                    deleted_at=datetime.now(UTC),
                )
                .returning(self.model_class.id)
                .execution_options(synchronize_session=False)
            )
            result = await self.session.execute(stmt)
            updated_ids = result.scalars().all()
            return len(updated_ids)

    # -------------------------------------------------------------------------
    # TRANSACTION MANAGEMENT
    # -------------------------------------------------------------------------

    @db_operation("transaction")
    async def execute_transaction[T](
        self,
        operation: Callable[[], T | Awaitable[T]],
    ) -> T:
        """Execute operation within a transaction. Returns operation result."""
        # Start a savepoint (nested transaction)
        async with self.session.begin_nested():
            if asyncio.iscoroutinefunction(operation):
                # If it's an async function, await it directly
                return await operation()

            # For non-async functions, we need to handle both regular and awaitable returns
            result = operation()  # Don't explicitly type this variable

            # Use is_coroutine instead of is_awaitable for better Pylance compatibility
            if asyncio.iscoroutine(result):
                return await result

            # If it's not a coroutine, it must be T directly
            return cast("T", result)

    # -------------------------------------------------------------------------
    # GET OR CREATE PATTERN
    # -------------------------------------------------------------------------

    @db_operation("get_or_create")
    async def get_or_create(
        self,
        lookup_attrs: dict[str, Any],
        _create_attrs: dict[str, Any] | None = None,
    ) -> tuple[TDomainModel, bool]:
        """Find an entity by attributes or create it if it doesn't exist.

        This method provides a base implementation that should be overridden
        by concrete repository classes with entity-specific creation logic.

        Args:
            lookup_attrs: Dictionary of attribute name/value pairs to search for
            create_attrs: Additional attributes to use when creating (if needed)

        Returns:
            tuple: (entity, created) where:
                - entity: The found or created domain entity
                - created: True if entity was created, False if found
        """
        # Build query directly
        stmt = self.select()

        # Apply lookup conditions
        for field, value in lookup_attrs.items():
            if hasattr(self.model_class, field):
                stmt = stmt.where(getattr(self.model_class, field) == value)

        stmt = stmt.limit(1)

        # Execute query directly
        result = await self.session.scalars(stmt)
        db_entity = result.first()

        if db_entity:
            domain_entity = await self.mapper.to_domain(db_entity)
            return domain_entity, False

        # Concrete repositories should override this method with entity-specific
        # creation logic. This implementation just shows the common pattern.
        raise NotImplementedError(
            f"get_or_create not implemented for {self.model_class.__name__}. "
            "Repository implementations must override this method.",
        )
