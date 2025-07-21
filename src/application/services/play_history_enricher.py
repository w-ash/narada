"""Play history enrichment service for tracklist metadata.

This application service orchestrates play history data aggregation and attachment
to tracklist metadata, following Clean Architecture separation of concerns.
"""

from datetime import UTC, datetime, timedelta

from src.config import get_logger
from src.domain.entities.track import TrackList
from src.infrastructure.persistence.repositories.track import TrackRepositories

logger = get_logger(__name__)


class PlayHistoryEnricher:
    """Application service for enriching tracklists with play history metadata.

    This service focuses solely on orchestration and data formatting,
    delegating actual data retrieval to repository layer.
    """

    def __init__(self, track_repos: TrackRepositories) -> None:
        """Initialize with repository container.

        Args:
            track_repos: Repository container for database operations.
        """
        self.play_repo = track_repos.plays

    async def enrich_with_play_history(
        self,
        tracklist: TrackList,
        metrics: list[str] | None = None,
        period_days: int | None = None,
    ) -> TrackList:
        """Enrich tracklist with play history metadata.

        Args:
            tracklist: Tracklist to enrich with play data
            metrics: List of metrics to include ["total_plays", "last_played_dates", "period_plays"]
            period_days: Number of days back for period-based metrics

        Returns:
            Tracklist with play history metadata attached
        """
        if metrics is None:
            metrics = ["total_plays", "last_played_dates"]

        logger.info(f"Enriching {len(tracklist.tracks)} tracks with play history")

        if not tracklist.tracks:
            logger.info("No tracks to enrich")
            return tracklist

        # Extract valid track IDs
        valid_tracks = [t for t in tracklist.tracks if t.id is not None]
        if not valid_tracks:
            logger.warning(
                "No tracks have database IDs - unable to enrich play history"
            )
            return tracklist

        track_ids = [t.id for t in valid_tracks if t.id is not None]

        # Calculate period boundaries if needed
        period_start, period_end = None, None
        if "period_plays" in metrics and period_days:
            period_end = datetime.now(UTC)
            period_start = period_end - timedelta(days=period_days)

        # Get aggregated play data from repository
        play_metrics = await self.play_repo.get_play_aggregations(
            track_ids=track_ids,
            metrics=metrics,
            period_start=period_start,
            period_end=period_end,
        )

        if not play_metrics:
            logger.info("No play data found for tracks")
            return tracklist

        # Merge with existing metrics
        current_metrics = tracklist.metadata.get("metrics", {})
        combined_metrics = {**current_metrics, **play_metrics}

        logger.info(f"Enriched with {len(play_metrics)} play metric types")
        return tracklist.with_metadata("metrics", combined_metrics)
