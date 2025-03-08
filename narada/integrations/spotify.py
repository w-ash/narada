"""Spotify service connector with domain model conversion."""

import asyncio
from datetime import UTC, datetime
import os
from typing import Any

import backoff
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from sqlalchemy import select

from narada.config import get_logger, resilient_operation
from narada.core.models import Artist, Playlist, Track
from narada.core.protocols import register_metric_resolver
from narada.database.database import get_session
from narada.database.dbmodels import DBTrackMapping

# Get contextual logger with service binding
logger = get_logger(__name__).bind(service="spotify")

load_dotenv()

os.environ["SPOTIPY_CLIENT_ID"] = os.getenv("SPOTIFY_CLIENT_ID", "")
os.environ["SPOTIPY_CLIENT_SECRET"] = os.getenv("SPOTIFY_CLIENT_SECRET", "")
os.environ["SPOTIPY_REDIRECT_URI"] = os.getenv("SPOTIFY_REDIRECT_URI", "")


class SpotifyConnector:
    """Thin wrapper around spotipy with domain model conversion.

    Handles OAuth flow and provides methods to:
    - Fetch playlists with track details
    - Create new playlists from domain models
    - Update existing playlists

    All methods handle rate limiting via backoff decorator.
    """

    def __init__(self) -> None:
        """Initialize Spotify client with OAuth configuration."""
        logger.debug("Initializing Spotify connector")
        self.client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                scope=[
                    "playlist-modify-public",
                    "playlist-modify-private",
                    "playlist-read-private",
                    "playlist-read-collaborative",
                ],
                open_browser=True,
                cache_handler=spotipy.CacheFileHandler(cache_path=".spotify_cache"),
            ),
        )

    @resilient_operation("get_spotify_playlist")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def get_spotify_playlist(self, spotify_playlist_id: str) -> Playlist:
        """Fetch a Spotify playlist asynchronously with full pagination."""
        # Get initial playlist data
        raw_playlist = await asyncio.to_thread(
            self.client.playlist,
            spotify_playlist_id,
            market="US",
            # Remove the additional_types parameter or use an empty list
        )

        if not isinstance(raw_playlist, dict):
            raise ValueError(f"Invalid playlist response for ID {spotify_playlist_id}")

        # Handle pagination to get all tracks
        tracks = raw_playlist["tracks"]
        all_items = tracks["items"]

        # Paginate until we get all tracks
        while tracks["next"]:
            tracks = await asyncio.to_thread(self.client.next, tracks)
            if tracks is not None and "items" in tracks:
                all_items.extend(tracks["items"])
            else:
                logger.warning("Received invalid tracks data during pagination")
                break

        # Replace the items with our complete list
        raw_playlist["tracks"]["items"] = all_items

        return convert_spotify_playlist_to_domain(raw_playlist)

    # Add these methods to SpotifyConnector

    @resilient_operation("create_spotify_playlist")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def create_playlist(
        self,
        name: str,
        tracks: list[Track],
        description: str | None = None,
    ) -> str:
        """Create a new Spotify playlist with tracks.

        Args:
            name: Playlist name
            tracks: List of tracks to add
            description: Optional playlist description

        Returns:
            Spotify playlist ID
        """
        try:
            # Extract Spotify track URIs
            spotify_track_uris = [
                f"spotify:track:{t.connector_track_ids['spotify']}"
                for t in tracks
                if "spotify" in t.connector_track_ids
            ]

            # Create empty playlist
            logger.info(
                f"Creating Spotify playlist: {name} with {len(spotify_track_uris)} tracks",
            )
            playlist = await asyncio.to_thread(
                self.client.user_playlist_create,
                user=(self.client.me() or {}).get("id", ""),
                name=name,
                public=False,
                description=description or "",
            )

            # Add tracks in batches (Spotify API limits)
            if spotify_track_uris:
                for i in range(0, len(spotify_track_uris), 50):
                    batch = spotify_track_uris[i : i + 50]
                    await asyncio.to_thread(
                        self.client.playlist_add_items,
                        playlist_id=playlist["id"] if playlist else "",
                        items=batch,
                    )
                    await asyncio.sleep(0.5)  # Small delay to prevent rate limiting

            if playlist is not None:
                return playlist["id"]
            else:
                raise ValueError("Failed to create playlist, received None")
        except spotipy.SpotifyException as e:
            logger.error(f"Spotify API error: {e}")
            raise

    @resilient_operation("update_spotify_playlist")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def update_playlist(
        self,
        playlist_id: str,
        playlist: Playlist,
        replace: bool = True,
    ) -> None:
        """Update an existing Spotify playlist.

        Args:
            playlist_id: Spotify ID of the playlist to update
            playlist: Domain playlist with the tracks to use
            replace: If True, replace all tracks; if False, append
        """
        # Extract Spotify track URIs from domain playlist
        spotify_track_uris = [
            f"spotify:track:{t.connector_track_ids['spotify']}"
            for t in playlist.tracks
            if "spotify" in t.connector_track_ids
        ]

        logger.info(
            f"{'Replacing' if replace else 'Appending to'} playlist {playlist_id} "
            f"with {len(spotify_track_uris)} tracks",
        )

        try:
            if replace:
                # Replace entire playlist contents
                await asyncio.to_thread(
                    self.client.playlist_replace_items,
                    playlist_id=playlist_id,
                    items=spotify_track_uris[:100] if spotify_track_uris else [],
                )

                # If we have more than 100 tracks, add them in batches
                remaining_tracks = (
                    spotify_track_uris[100:] if len(spotify_track_uris) > 100 else []
                )
            else:
                # When appending, start with all tracks
                remaining_tracks = spotify_track_uris

            # Add remaining tracks in batches of 50
            for i in range(0, len(remaining_tracks), 50):
                batch = remaining_tracks[i : i + 50]
                await asyncio.to_thread(
                    self.client.playlist_add_items,
                    playlist_id=playlist_id,
                    items=batch,
                )
                await asyncio.sleep(0.5)  # Small delay to prevent rate limiting

        except spotipy.SpotifyException as e:
            logger.error(f"Spotify API error: {e}")
            raise


def convert_spotify_track_to_domain(spotify_track: dict[str, Any]) -> Track:
    """Convert Spotify track data to domain model."""
    artists = [Artist(name=artist["name"]) for artist in spotify_track["artists"]]

    # Parse release date based on precision
    release_date = None
    if "album" in spotify_track and "release_date" in spotify_track["album"]:
        date_str = spotify_track["album"]["release_date"]
        precision = spotify_track["album"].get("release_date_precision", "day")

        try:
            if precision == "year":
                release_date = datetime.strptime(date_str, "%Y").replace(tzinfo=UTC)
            elif precision == "month":
                release_date = datetime.strptime(date_str, "%Y-%m").replace(tzinfo=UTC)
            else:  # day precision
                release_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=UTC,
                )
        except ValueError as e:
            logger.warning(f"Failed to parse release date '{date_str}': {e}")

    track = Track(
        title=spotify_track["name"],
        artists=artists,
        album=spotify_track["album"]["name"],
        duration_ms=spotify_track["duration_ms"],
        release_date=release_date,
        isrc=spotify_track.get("external_ids", {}).get("isrc"),
    )

    # Store Spotify-specific metadata
    track = track.with_connector_metadata(
        "spotify",
        {
            "popularity": spotify_track.get("popularity", 0),
            "album_id": spotify_track["album"].get("id"),
            "explicit": spotify_track.get("explicit", False),
        },
    )

    # Store connector ID
    return track.with_connector_track_id("spotify", spotify_track["id"])


def convert_spotify_playlist_to_domain(spotify_playlist: dict[str, Any]) -> Playlist:
    """Convert Spotify playlist data to domain model.

    Args:
        spotify_playlist: Raw playlist data from Spotify API

    Returns:
        Domain Playlist model with all tracks converted
    """
    domain_tracks = [
        convert_spotify_track_to_domain(item["track"])
        for item in spotify_playlist["tracks"]["items"]
        if item["track"] is not None  # Handle potentially null tracks
    ]

    playlist = Playlist(
        name=spotify_playlist["name"],
        description=spotify_playlist.get("description"),
        tracks=domain_tracks,
    )

    return playlist.with_connector_track_id("spotify", spotify_playlist["id"])


def get_connector_config():
    """Spotify connector configuration."""
    return {
        "extractors": {
            # Smart extractors that handle both object types
            "popularity": lambda obj: obj.get_connector_attribute(
                "spotify",
                "popularity",
                0,
            )
            if hasattr(obj, "get_connector_attribute")
            else obj.get("popularity", 0),
        },
        "dependencies": ["auth"],
        "factory": lambda _params: SpotifyConnector(),
        "metrics": {"popularity": "popularity"},
    }


class SpotifyMetricResolver:
    """Resolves Spotify metrics from persistence layer."""

    async def resolve(self, track_ids: list[int], metric_name: str) -> dict[str, Any]:
        """Fetch stored Spotify metadata from the database.

        Args:
            track_ids: List of internal track IDs
            metric_name: Metric to resolve (used to determine field name)

        Returns:
            Dictionary mapping track_id strings to metric values
        """
        if not track_ids:
            return {}

        # Map metric names to connector metadata fields
        field_map = {
            "spotify_popularity": "popularity",
            "explicit_flag": "explicit",
        }

        # Get the connector field name
        field = field_map.get(metric_name)
        if not field:
            return {}

        # Fetch metadata efficiently with a single query
        async with get_session() as session:
            stmt = select(
                DBTrackMapping.track_id,
                DBTrackMapping.connector_metadata,
            ).where(
                DBTrackMapping.connector_name == "spotify",
                DBTrackMapping.track_id.in_(track_ids),
                DBTrackMapping.is_deleted == False,  # noqa: E712
            )

            results = await session.execute(stmt)

            # Extract field from connector metadata
            return {
                str(track_id): metadata.get(field, 0)
                for track_id, metadata in results
                if metadata and field in metadata
            }


# Register at module initialization time
register_metric_resolver("spotify_popularity", SpotifyMetricResolver())
