"""Track connector repository for mapping tracks to external services."""

from datetime import UTC, datetime
from typing import Any

from attrs import define
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from narada.config import get_logger
from narada.core.models import Artist, Track
from narada.database.db_models import DBConnectorTrack, DBTrackMapping
from narada.repositories.base_repo import BaseModelMapper, BaseRepository
from narada.repositories.repo_decorator import db_operation
from narada.repositories.track.core import TrackRepository
from narada.repositories.track.mapper import TrackMapper

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class ConnectorTrackMapper(BaseModelMapper[DBConnectorTrack, dict[str, Any]]):
    """Maps between DBConnectorTrack and dictionary representation."""

    @staticmethod
    async def to_domain(db_model: DBConnectorTrack) -> dict[str, Any]:
        """Convert DB connector track to dictionary."""
        if not db_model:
            return None

        return {
            "id": db_model.id,
            "connector_name": db_model.connector_name,
            "connector_track_id": db_model.connector_track_id,
            "title": db_model.title,
            "artists": db_model.artists,
            "album": db_model.album,
            "duration_ms": db_model.duration_ms,
            "release_date": db_model.release_date,
            "isrc": db_model.isrc,
            "raw_metadata": db_model.raw_metadata,
            "last_updated": db_model.last_updated,
        }

    @staticmethod
    def to_db(domain_model: dict[str, Any]) -> DBConnectorTrack:
        """Convert dictionary to DB connector track."""
        return DBConnectorTrack(
            connector_name=domain_model.get("connector_name"),
            connector_track_id=domain_model.get("connector_track_id"),
            title=domain_model.get("title"),
            artists=domain_model.get("artists"),
            album=domain_model.get("album"),
            duration_ms=domain_model.get("duration_ms"),
            release_date=domain_model.get("release_date"),
            isrc=domain_model.get("isrc"),
            raw_metadata=domain_model.get("raw_metadata"),
            last_updated=domain_model.get("last_updated", datetime.now(UTC)),
        )

    @staticmethod
    def get_default_relationships() -> list[str]:
        """Get default relationships to load for connector tracks.

        Note: ConnectorTrack only has 'mappings' relationship.
        """
        return ["mappings"]


@define(frozen=True, slots=True)
class TrackMappingMapper(BaseModelMapper[DBTrackMapping, dict[str, Any]]):
    """Maps between DBTrackMapping and dictionary representation."""

    @staticmethod
    async def to_domain(db_model: DBTrackMapping) -> dict[str, Any]:
        """Convert DB mapping to dictionary."""
        if not db_model:
            return None

        return {
            "id": db_model.id,
            "track_id": db_model.track_id,
            "connector_track_id": db_model.connector_track_id,
            "match_method": db_model.match_method,
            "confidence": db_model.confidence,
            "confidence_evidence": db_model.confidence_evidence,
        }

    @staticmethod
    def to_db(domain_model: dict[str, Any]) -> DBTrackMapping:
        """Convert dictionary to DB mapping."""
        return DBTrackMapping(
            track_id=domain_model.get("track_id"),
            connector_track_id=domain_model.get("connector_track_id"),
            match_method=domain_model.get("match_method"),
            confidence=domain_model.get("confidence"),
            confidence_evidence=domain_model.get("confidence_evidence"),
        )

    @staticmethod
    def get_default_relationships() -> list[str]:
        """Get default relationships to load for track mappings.

        Note: TrackMapping doesn't have a 'mappings' relationship.
        """
        return ["track", "connector_track"]


class ConnectorTrackRepository(BaseRepository[DBConnectorTrack, dict[str, Any]]):
    """Repository for connector track operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBConnectorTrack,
            mapper=ConnectorTrackMapper(),
        )


class TrackMappingRepository(BaseRepository[DBTrackMapping, dict[str, Any]]):
    """Repository for track mapping operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBTrackMapping,
            mapper=TrackMappingMapper(),
        )


class TrackConnectorRepository:
    """Repository for track connector operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session."""
        self.session = session
        self.track_mapper = TrackMapper()
        self.connector_repo = ConnectorTrackRepository(session)
        self.mapping_repo = TrackMappingRepository(session)
        self.track_repo = TrackRepository(session)

    @db_operation("find_track_by_connector")
    async def find_track_by_connector(
        self, connector: str, connector_id: str
    ) -> Track | None:
        """Find a track by connector name and ID."""
        # Find the connector track first
        connector_track = await self.connector_repo.find_one_by({
            "connector_name": connector,
            "connector_track_id": connector_id,
        })

        if not connector_track:
            return None

        # Find mapping using the connector track ID
        mapping = await self.mapping_repo.find_one_by({
            "connector_track_id": connector_track["id"],
        })

        if not mapping:
            return None

        # Get the track using the track_id from the mapping
        return await self.track_repo.get_by_id(mapping["track_id"])

    @db_operation("map_track_to_connector")
    async def map_track_to_connector(
        self,
        track: Track,
        connector: str,
        connector_id: str,
        match_method: str,
        confidence: int,
        metadata: dict | None = None,
        confidence_evidence: dict | None = None,
    ) -> Track:
        """Map an existing track to a connector."""
        if track.id is None:
            raise ValueError("Cannot map track with no ID")

        # DEBUG: Log what metadata we're getting
        logger.debug(
            f"Mapping track {track.id} to {connector}:{connector_id}",
            metadata_param=metadata is not None,
            connector_metadata=track.connector_metadata.get(connector, {})
            if hasattr(track, "connector_metadata")
            else None,
        )

        # Ensure the track exists in the database
        try:
            await self.track_repo.get_by_id(track.id)
        except ValueError as err:
            raise ValueError(f"Track with ID {track.id} not found") from err

        # Create or get the connector track
        connector_track = await self.connector_repo.find_one_by({
            "connector_name": connector,
            "connector_track_id": connector_id,
        })

        if not connector_track:
            metadata_to_save = metadata or {}

            connector_track = await self.connector_repo.create({
                "connector_name": connector,
                "connector_track_id": connector_id,
                "title": track.title,
                "artists": {"names": [a.name for a in track.artists]}
                if track.artists
                else None,
                "album": track.album,
                "duration_ms": track.duration_ms,
                "release_date": track.release_date,
                "isrc": track.isrc,
                "raw_metadata": metadata_to_save,  # Always save metadata here
                "last_updated": datetime.now(UTC),
            })

            # Simple log to confirm metadata was stored
            logger.debug(
                "Created connector track with raw_metadata fields",
                metadata_keys=list(metadata_to_save.keys()) if metadata_to_save else [],
                has_metadata=bool(metadata_to_save),
            )

        # Create or update the mapping
        await self.mapping_repo.upsert(
            lookup_attrs={
                "track_id": track.id,
                "connector_track_id": connector_track["id"],
            },
            create_attrs={
                "match_method": match_method,
                "confidence": confidence,
                "confidence_evidence": confidence_evidence,
            },
        )

        # Return updated track with connector ID
        updated_track = track.with_connector_track_id(connector, connector_id)
        if metadata:
            updated_track = updated_track.with_connector_metadata(connector, metadata)

        # Process metrics within the same transaction
        if track.id is not None and metadata:
            # Import the in-transaction metrics processor
            from narada.repositories.track.metrics import process_metrics_for_track
            
            # Get track ID for type checking
            track_id = track.id
            
            # Process metrics within this transaction using the same session
            # This avoids creating a new transaction that could cause locks
            try:
                # Create metadata in the format expected by process_metrics_for_track
                track_metadata = {track_id: metadata}
                await process_metrics_for_track(self.session, track_id, connector, track_metadata)
                logger.debug(f"Processed metrics for track {track_id} in existing transaction")
            except Exception as e:
                # Log but allow the operation to continue
                logger.warning(
                    f"Non-critical error processing metrics for track {track_id}: {e}",
                    connector=connector,
                    exc_info=True,
                )

        return updated_track

    @db_operation("ingest_external_track")
    async def ingest_external_track(
        self,
        connector: str,
        connector_id: str,
        metadata: dict | None,
        title: str,
        artists: list[str],
        album: str | None = None,
        duration_ms: int | None = None,
        release_date: datetime | None = None,
        isrc: str | None = None,
    ) -> Track:
        """Ingest track data from external source.
        
        This method follows a data-first approach:
        1. First saves connector_track with raw metadata
        2. Then creates/finds core track
        3. Finally handles mappings and metrics
        
        Uses explicit repository operations to avoid async issues.
        """
        # Step 1: Find or create connector track
        connector_track = await self.connector_repo.find_one_by({
            "connector_name": connector,
            "connector_track_id": connector_id,
        })
        
        artists_dict = {"names": artists} if artists else {"names": []}
        
        if not connector_track:
            # Create new connector track 
            connector_track = await self.connector_repo.create({
                "connector_name": connector,
                "connector_track_id": connector_id,
                "title": title,
                "artists": artists_dict,
                "album": album,
                "duration_ms": duration_ms,
                "release_date": release_date,
                "isrc": isrc,
                "raw_metadata": metadata or {},
                "last_updated": datetime.now(UTC),
            })
            
            logger.debug(
                f"Created connector track for {connector}:{connector_id}",
                connector_track_id=connector_track["id"],
                metadata_keys=list(metadata.keys()) if metadata else [],
            )
        else:
            # Update existing connector track
            await self.connector_repo.update(
                connector_track["id"], 
                {
                    "title": title,
                    "artists": artists_dict,
                    "album": album,
                    "duration_ms": duration_ms,
                    "release_date": release_date,
                    "isrc": isrc,
                    "raw_metadata": metadata or {},
                    "last_updated": datetime.now(UTC),
                }
            )
        
        # Step 2: Check if there's a mapping to an existing track
        mapping = await self.mapping_repo.find_one_by({
            "connector_track_id": connector_track["id"],
            "is_deleted": False,
        })
        
        track = None
        if mapping:
            # Track exists, retrieve it
            track = await self.track_repo.get_by_id(mapping["track_id"])
            logger.debug(
                f"Found existing track {mapping['track_id']} for {connector}:{connector_id}"
            )
        else:
            # Create a new track from the connector data
            track_obj = Track(
                title=title,
                artists=[Artist(name=name) for name in artists],
                album=album,
                duration_ms=duration_ms,
                release_date=release_date,
                isrc=isrc,
            )
            
            # Add connector ID and metadata
            track_obj = track_obj.with_connector_track_id(connector, connector_id)
            if metadata:
                track_obj = track_obj.with_connector_metadata(connector, metadata)
            
            # Save to database
            track = await self.track_repo.save_track(track_obj)
            
            # Create the mapping
            if track and track.id is not None:
                await self.mapping_repo.create({
                    "track_id": track.id,
                    "connector_track_id": connector_track["id"],
                    "match_method": "direct",
                    "confidence": 100,
                })
                logger.debug(
                    f"Created new track {track.id} for {connector}:{connector_id}"
                )
        
        # Step 3: Process metrics within the same transaction as the rest of the data
        if track and track.id is not None and metadata:
            # Import the in-transaction metrics processor
            from narada.repositories.track.metrics import process_metrics_for_track
            
            # Get track ID for type checking
            track_id = track.id
            
            # Process metrics within this transaction using the same session
            # This avoids creating a new transaction and prevents database locks
            try:
                # Create metadata in the format expected by process_metrics_for_track
                track_metadata = {track_id: metadata}
                await process_metrics_for_track(self.session, track_id, connector, track_metadata)
                logger.debug(f"Processed metrics for track {track_id} in existing transaction")
            except Exception as e:
                # Log but allow the operation to continue
                logger.warning(
                    f"Non-critical error processing metrics for track {track_id}: {e}",
                    connector=connector,
                    exc_info=True,
                )
        
        return track

    @db_operation("create_track_from_connector_data")
    async def create_track_from_connector_data(
        self, track: Track, connector: str
    ) -> Track:
        """Create a track directly from connector data."""
        if not track.title or not track.artists:
            raise ValueError("Track must have title and artists")

        if connector not in track.connector_track_ids:
            raise ValueError(f"Track doesn't have an ID for connector {connector}")

        # Use the new ingest method for consistency
        connector_id = track.connector_track_ids[connector]
        metadata = (
            track.connector_metadata.get(connector, {})
            if hasattr(track, "connector_metadata")
            else {}
        )

        return await self.ingest_external_track(
            connector=connector,
            connector_id=connector_id,
            metadata=metadata,
            title=track.title,
            artists=[a.name for a in track.artists] if track.artists else [],
            album=track.album,
            duration_ms=track.duration_ms,
            release_date=track.release_date,
            isrc=track.isrc,
        )

    @db_operation("get_connector_mappings")
    async def get_connector_mappings(
        self,
        track_ids: list[int],
        connector: str | None = None,
    ) -> dict[int, dict[str, str]]:
        """Get mappings between tracks and external connectors."""
        if not track_ids:
            return {}

        # Build efficient join between mappings and connector tracks
        stmt = (
            select(
                self.mapping_repo.model_class.track_id,
                self.connector_repo.model_class.connector_name,
                self.connector_repo.model_class.connector_track_id,
            )
            .join(
                self.connector_repo.model_class,
                self.mapping_repo.model_class.connector_track_id
                == self.connector_repo.model_class.id,
            )
            .where(
                self.mapping_repo.model_class.track_id.in_(track_ids),
                self.mapping_repo.model_class.is_deleted == False,  # noqa: E712
                self.connector_repo.model_class.is_deleted == False,  # noqa: E712
            )
        )

        if connector:
            stmt = stmt.where(
                self.connector_repo.model_class.connector_name == connector
            )

        # Execute and build response
        result = await self.session.execute(stmt)

        mappings_dict = {}
        for track_id, conn_name, conn_id in result:
            mappings_dict.setdefault(track_id, {})[conn_name] = conn_id

        return mappings_dict

    @db_operation("get_connector_metadata")
    async def get_connector_metadata(
        self,
        track_ids: list[int],
        connector: str,
        metadata_field: str | None = None,
    ) -> dict[int, dict[str, Any] | Any]:
        """Get connector metadata for tracks."""
        if not track_ids:
            return {}

        # Build efficient join query
        stmt = (
            select(
                self.mapping_repo.model_class.track_id,
                self.connector_repo.model_class.raw_metadata,
            )
            .join(
                self.connector_repo.model_class,
                self.mapping_repo.model_class.connector_track_id
                == self.connector_repo.model_class.id,
            )
            .where(
                self.mapping_repo.model_class.track_id.in_(track_ids),
                self.connector_repo.model_class.connector_name == connector,
                self.mapping_repo.model_class.is_deleted == False,  # noqa: E712
                self.connector_repo.model_class.is_deleted == False,  # noqa: E712
            )
        )

        # Execute and build response
        result = await self.session.execute(stmt)

        # Return either the specific field or all metadata
        if metadata_field:
            return {
                track_id: metadata.get(metadata_field)
                for track_id, metadata in result
                if metadata and metadata_field in metadata
            }
        else:
            return {track_id: metadata for track_id, metadata in result if metadata}

    @db_operation("save_mapping_confidence")
    async def save_mapping_confidence(
        self,
        track_id: int,
        connector: str,
        connector_id: str,
        confidence: int,
        match_method: str | None = None,
        confidence_evidence: dict | None = None,
    ) -> bool:
        """Save confidence information to the track mapping."""
        # Find the connector track first
        connector_track = await self.connector_repo.find_one_by({
            "connector_name": connector,
            "connector_track_id": connector_id,
        })

        if not connector_track:
            return False

        # Check if connector_track ID is valid
        connector_track_id = connector_track.get("id")
        if connector_track_id is None:
            return False

        # Find the mapping
        mapping = await self.mapping_repo.find_one_by({
            "track_id": track_id,
            "connector_track_id": connector_track_id,
        })

        if not mapping:
            return False

        # Build a properly typed dictionary for the update
        # This explicit dict[str, Any] helps Pylance understand the value types
        update_data: dict[str, Any] = {
            "confidence": confidence,
        }

        if match_method:
            update_data["match_method"] = match_method

        if confidence_evidence:
            update_data["confidence_evidence"] = confidence_evidence

        # Update the mapping using the ID and update method
        try:
            mapping_id = mapping.get("id")
            if mapping_id is None:
                return False

            await self.mapping_repo.update(mapping_id, update_data)
            return True
        except ValueError:
            return False

    @db_operation("get_mapping_info")
    async def get_mapping_info(
        self, track_id: int, connector: str, connector_id: str
    ) -> dict:
        """Get mapping information including confidence and method."""
        # Find connector track
        connector_track = await self.connector_repo.find_one_by({
            "connector_name": connector,
            "connector_track_id": connector_id,
        })

        if not connector_track:
            return {}

        # Find mapping
        mapping = await self.mapping_repo.find_one_by({
            "track_id": track_id,
            "connector_track_id": connector_track["id"],
        })

        if not mapping:
            return {}

        return {
            "confidence": mapping["confidence"],
            "match_method": mapping["match_method"],
            "confidence_evidence": mapping["confidence_evidence"],
        }