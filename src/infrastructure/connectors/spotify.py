"""Spotify service connector with domain model conversion.

This module provides a connector for the Spotify API using the spotipy library
(https://spotipy.readthedocs.io/) to handle authentication, rate limiting, and
conversion between Spotify objects and domain models.

Key components:
- SpotifyConnector: OAuth-authenticated client with playlist and track operations
- SpotifyMetricResolver: Resolver for Spotify-specific track metrics
- Conversion utilities: Transform Spotify API responses to domain models

The module supports:
- Fetching and creating playlists with detailed track information
- Searching tracks by ISRC or artist/title combinations
- Retrieving user's liked/saved tracks with pagination
- Resolving popularity metrics for ranking operations
"""

import asyncio
from datetime import UTC, datetime
import os
from typing import Any, ClassVar

import attrs
from attrs import define, field
import backoff
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from src.domain.entities import (
    Artist,
    ConnectorPlaylist,
    ConnectorPlaylistItem,
    ConnectorTrack,
    Playlist,
    Track,
)
from src.infrastructure.config import get_logger, resilient_operation
from src.infrastructure.connectors.base_connector import (
    BaseMetricResolver,
    register_metrics,
)
from src.infrastructure.connectors.protocols import ConnectorConfig

# Get contextual logger with service binding
logger = get_logger(__name__).bind(service="spotify")

load_dotenv()

os.environ["SPOTIPY_CLIENT_ID"] = os.getenv("SPOTIFY_CLIENT_ID", "")
os.environ["SPOTIPY_CLIENT_SECRET"] = os.getenv("SPOTIFY_CLIENT_SECRET", "")
os.environ["SPOTIPY_REDIRECT_URI"] = os.getenv("SPOTIFY_REDIRECT_URI", "")


@define(slots=True)
class SpotifyConnector:
    """Thin wrapper around spotipy with domain model conversion.

    Handles OAuth flow and provides methods to:
    - Fetch playlists with track details
    - Create new playlists from domain models
    - Update existing playlists

    All methods handle rate limiting via backoff decorator.
    """

    client: spotipy.Spotify = field(init=False, repr=False)

    def __attrs_post_init__(self) -> None:
        """Initialize Spotify client with OAuth configuration."""
        logger.debug("Initializing Spotify connector")
        self.client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                scope=[
                    "playlist-modify-public",
                    "playlist-modify-private",
                    "playlist-read-private",
                    "playlist-read-collaborative",
                    "user-library-read",
                ],
                open_browser=True,
                cache_handler=spotipy.CacheFileHandler(cache_path=".spotify_cache"),
            ),
        )

    @resilient_operation("get_spotify_tracks_by_ids")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def get_tracks_by_ids(
        self, track_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch multiple tracks from Spotify in bulk (up to 50 per request).

        Args:
            track_ids: List of Spotify track IDs

        Returns:
            Dictionary mapping track IDs to their data
        """
        if not track_ids:
            return {}

        results = {}
        # Process in batches of 50 (Spotify API limit)
        for i in range(0, len(track_ids), 50):
            batch = track_ids[i : i + 50]
            logger.debug(f"Fetching batch of {len(batch)} tracks from Spotify")

            tracks_response = await asyncio.to_thread(
                self.client.tracks, batch, market="US"
            )

            if tracks_response and "tracks" in tracks_response:
                for j, track in enumerate(tracks_response["tracks"]):
                    if track and "id" in track:
                        # Use the original requested ID as the key, not the canonical ID
                        # This handles cases where Spotify relinks tracks to new IDs
                        requested_id = batch[j]
                        results[requested_id] = track

        logger.info(f"Retrieved {len(results)}/{len(track_ids)} tracks in bulk")
        return results

    @resilient_operation("search_spotify_by_isrc")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def search_by_isrc(self, isrc: str) -> dict[str, Any] | None:
        """Search for a track using ISRC identifier.

        Args:
            isrc: The ISRC code to search for

        Returns:
            Track data if found, None otherwise
        """
        logger.debug(f"Searching Spotify for ISRC: {isrc}")
        results = await asyncio.to_thread(
            self.client.search,
            f"isrc:{isrc}",
            type="track",
            limit=1,
            market="US",
        )

        tracks = results.get("tracks", {}).get("items", []) if results else []
        return tracks[0] if tracks else None

    @resilient_operation("search_spotify_track")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def search_track(self, artist: str, title: str) -> dict[str, Any] | None:
        """Search for a track by artist and title.

        Args:
            artist: Artist name
            title: Track title

        Returns:
            Track data if found, None otherwise
        """
        query = f"artist:{artist} track:{title}"
        logger.debug(f"Searching Spotify with query: {query}")
        results = await asyncio.to_thread(
            self.client.search,
            query,
            type="track",
            limit=1,
            market="US",
        )

        tracks = results.get("tracks", {}).get("items", []) if results else []
        return tracks[0] if tracks else None

    @resilient_operation("get_spotify_playlist")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def get_spotify_playlist(self, playlist_id: str) -> ConnectorPlaylist:
        """Fetch a Spotify playlist with its tracks.

        Args:
            playlist_id: Spotify playlist ID to fetch

        Returns:
            ConnectorPlaylist containing playlist metadata and track items
        """
        # Get initial playlist data
        raw_playlist = await asyncio.to_thread(
            self.client.playlist,
            playlist_id,
            market="US",
        )

        if not isinstance(raw_playlist, dict):
            raise ValueError(f"Invalid playlist response for ID {playlist_id}")

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

        # Convert basic playlist metadata
        connector_playlist = convert_spotify_playlist_to_connector(raw_playlist)

        # Process each track item with its metadata
        playlist_items = []
        for idx, item in enumerate(all_items):
            if item.get("track") is not None:
                track = item["track"]
                # Get the added_at timestamp
                added_at = item.get("added_at")

                # Create ConnectorPlaylistItem with track ID and metadata
                playlist_item = ConnectorPlaylistItem(
                    connector_track_id=track["id"],
                    position=idx,
                    added_at=added_at,
                    added_by_id=item.get("added_by", {}).get("id"),
                    extras={
                        "is_local": item.get("is_local", False),
                        "track_name": track.get(
                            "name"
                        ),  # Include minimal track info for reference
                        "artist_names": [a["name"] for a in track.get("artists", [])],
                        # Store the added_at in extras too for easy access
                        "added_at": added_at,
                    },
                )
                playlist_items.append(playlist_item)

        # Use evolve to add items to the playlist
        connector_playlist = attrs.evolve(connector_playlist, items=playlist_items)

        return connector_playlist

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

    @resilient_operation("get_liked_tracks")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def get_liked_tracks(
        self,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[ConnectorTrack], str | None]:
        """Fetch user's saved/liked tracks from Spotify with pagination.

        Args:
            limit: Number of tracks to fetch per page (max 50)
            cursor: Pagination cursor from previous calls

        Returns:
            Tuple of (list of ConnectorTrack models, next cursor or None if done)
        """
        logger.info(
            f"Fetching liked tracks from Spotify, limit={limit}, cursor={cursor}"
        )

        try:
            # Convert cursor to offset if provided
            offset = 0
            if cursor:
                try:
                    offset = int(cursor)
                except ValueError:
                    logger.warning(f"Invalid cursor format: {cursor}, using offset=0")

            # Get saved tracks from Spotify API
            saved_tracks = await asyncio.to_thread(
                self.client.current_user_saved_tracks,
                limit=min(limit, 50),  # Spotify's max limit is 50
                offset=offset,
                market="US",
            )

            if not saved_tracks or "items" not in saved_tracks:
                logger.warning("No saved tracks found or invalid response format")
                return [], None

            # Extract actual track objects from the response
            # The API returns items with {added_at, track} structure
            connector_tracks = []

            for item in saved_tracks["items"]:
                if not item or "track" not in item:
                    continue

                spotify_track = item["track"]
                # Save the added_at timestamp in the track metadata
                added_at = item.get("added_at")

                # Create connector track
                connector_track = convert_spotify_track_to_connector(spotify_track)

                if added_at:
                    # Add liked timestamp to connector metadata
                    try:
                        # Spotify timestamp format: "2023-09-21T15:48:56Z"
                        liked_at = datetime.fromisoformat(
                            added_at.replace("Z", "+00:00")
                        )

                        # Update raw metadata with liked information
                        connector_track.raw_metadata["liked_at"] = liked_at.isoformat()
                        connector_track.raw_metadata["is_liked"] = True

                    except ValueError:
                        logger.warning(
                            f"Could not parse added_at timestamp: {added_at}"
                        )

                connector_tracks.append(connector_track)

            # Determine next cursor
            next_cursor = None
            if saved_tracks.get("next") and saved_tracks["items"]:
                next_cursor = str(offset + len(saved_tracks["items"]))

            return connector_tracks, next_cursor

        except spotipy.SpotifyException as e:
            logger.error(f"Error fetching liked tracks: {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error fetching liked tracks: {e}")
            raise


def convert_spotify_track_to_connector(spotify_track: dict[str, Any]) -> ConnectorTrack:
    """Convert Spotify track data to ConnectorTrack domain model."""
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

    # Prepare raw metadata with essential information
    raw_metadata = {
        "popularity": spotify_track.get("popularity", 0),
        "album_id": spotify_track["album"].get("id"),
        "explicit": spotify_track.get("explicit", False),
    }

    return ConnectorTrack(
        connector_name="spotify",
        connector_track_id=spotify_track["id"],
        title=spotify_track["name"],
        artists=artists,
        album=spotify_track["album"]["name"],
        duration_ms=spotify_track["duration_ms"],
        release_date=release_date,
        isrc=spotify_track.get("external_ids", {}).get("isrc"),
        raw_metadata=raw_metadata,
        last_updated=datetime.now(UTC),
    )


# Removed convert_spotify_track_to_domain in favor of repository layer mapping


def convert_spotify_playlist_to_connector(
    spotify_playlist: dict[str, Any],
) -> ConnectorPlaylist:
    """Convert Spotify playlist data to ConnectorPlaylist domain model.

    Args:
        spotify_playlist: Raw playlist data from Spotify API

    Returns:
        ConnectorPlaylist model representing the external service playlist
    """
    # Extract owner information
    owner = spotify_playlist.get("owner", {}).get(
        "display_name"
    ) or spotify_playlist.get("owner", {}).get("id")

    owner_id = spotify_playlist.get("owner", {}).get("id")
    collaborative = spotify_playlist.get("collaborative", False)

    # Prepare raw metadata with essential information
    raw_metadata = {
        "snapshot_id": spotify_playlist.get("snapshot_id"),
        "tracks_href": spotify_playlist.get("tracks", {}).get("href"),
        "images": spotify_playlist.get("images", []),
        "total_tracks": spotify_playlist.get("tracks", {}).get("total", 0),
    }

    return ConnectorPlaylist(
        connector_name="spotify",
        connector_playlist_id=spotify_playlist["id"],
        name=spotify_playlist["name"],
        description=spotify_playlist.get("description"),
        owner=owner,
        owner_id=owner_id,
        is_public=spotify_playlist.get("public", False),
        collaborative=collaborative,
        follower_count=spotify_playlist.get("followers", {}).get("total"),
        raw_metadata=raw_metadata,
        last_updated=datetime.now(UTC),
    )


def get_connector_config() -> ConnectorConfig:
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
        "metrics": SpotifyMetricResolver.FIELD_MAP,
    }


@define(frozen=True, slots=True)
class SpotifyMetricResolver(BaseMetricResolver):
    """Resolves Spotify metrics from persistence layer."""

    # Map metric names to connector metadata fields
    FIELD_MAP: ClassVar[dict[str, str]] = {
        "spotify_popularity": "popularity",
        "explicit_flag": "explicit",
    }

    # Connector name for database operations
    CONNECTOR: ClassVar[str] = "spotify"


# Register all metric resolvers at once
register_metrics(SpotifyMetricResolver(), SpotifyMetricResolver.FIELD_MAP)
