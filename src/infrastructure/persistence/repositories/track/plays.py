"""Track repository for play operations."""

from attrs import define
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import TrackPlay
from src.infrastructure.config import get_logger
from src.infrastructure.persistence.database.db_models import DBTrackPlay
from src.infrastructure.persistence.repositories.base_repo import (
    BaseModelMapper,
    BaseRepository,
)
from src.infrastructure.persistence.repositories.repo_decorator import db_operation

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class TrackPlayMapper(BaseModelMapper[DBTrackPlay, TrackPlay]):
    """Maps between DBTrackPlay and TrackPlay domain models."""

    @staticmethod
    def get_default_relationships() -> list[str]:
        """Return relationships to eagerly load for track plays."""
        return []  # Don't eagerly load track by default for performance

    @staticmethod
    async def to_domain(db_model: DBTrackPlay) -> TrackPlay:
        """Convert database play to domain model."""
        if not db_model:
            return None

        return TrackPlay(
            track_id=db_model.track_id,
            service=db_model.service,
            played_at=db_model.played_at,
            ms_played=db_model.ms_played,
            context=db_model.context,
            id=db_model.id,
            import_timestamp=db_model.import_timestamp,
            import_source=db_model.import_source,
            import_batch_id=db_model.import_batch_id,
        )

    @staticmethod
    def to_db(domain_model: TrackPlay) -> DBTrackPlay:
        """Convert domain play to database model."""
        return DBTrackPlay(
            track_id=domain_model.track_id,
            service=domain_model.service,
            played_at=domain_model.played_at,
            ms_played=domain_model.ms_played,
            context=domain_model.context,
            import_timestamp=domain_model.import_timestamp,
            import_source=domain_model.import_source,
            import_batch_id=domain_model.import_batch_id,
        )


class TrackPlayRepository(BaseRepository[DBTrackPlay, TrackPlay]):
    """Repository for track play operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBTrackPlay,
            mapper=TrackPlayMapper(),
        )

    @db_operation("bulk_insert_plays")
    async def bulk_insert_plays(self, plays: list[TrackPlay]) -> int:
        """Bulk insert track plays efficiently."""
        if not plays:
            return 0

        play_data = [
            {
                "track_id": play.track_id,
                "service": play.service,
                "played_at": play.played_at,
                "ms_played": play.ms_played,
                "context": play.context,
                "import_timestamp": play.import_timestamp,
                "import_source": play.import_source,
                "import_batch_id": play.import_batch_id,
            }
            for play in plays
        ]

        result = await self.bulk_upsert(
            play_data,
            lookup_keys=["track_id", "service", "played_at", "ms_played"],
            return_models=False,
        )

        # Return count of inserted records
        return len(play_data) if isinstance(result, list) else result

    @db_operation("get_plays_by_batch")
    async def get_plays_by_batch(self, import_batch_id: str) -> list[TrackPlay]:
        """Get all plays from a specific import batch."""
        return await self.find_by([
            self.model_class.import_batch_id == import_batch_id,
            self.model_class.is_deleted == False,  # noqa: E712
        ])
