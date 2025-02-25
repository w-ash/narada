"""Spotify service connector with domain model conversion."""

import asyncio
import os
from datetime import datetime
from typing import Any

import backoff
import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

from narada.config import get_logger, resilient_operation
from narada.core.models import Artist, Playlist, Track

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
                scope=["playlist-modify-public", "playlist-modify-private"],
                open_browser=True,
                cache_handler=spotipy.CacheFileHandler(cache_path=".spotify_cache"),
            )
        )

    @resilient_operation("get_spotify_playlist")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def get_spotify_playlist(self, spotify_playlist_id: str) -> Playlist:
        """Fetch a Spotify playlist asynchronously with full pagination."""
        # Get initial playlist data
        raw_playlist = await asyncio.to_thread(
            self.client.playlist, spotify_playlist_id
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

    @resilient_operation("create_spotify_playlist")
    @backoff.on_exception(backoff.expo, spotipy.SpotifyException, max_tries=3)
    async def create_spotify_playlist(
        self, domain_playlist: Playlist, user_id: str | None = None
    ) -> str:
        """Create a new Spotify playlist asynchronously."""
        try:
            if not user_id:
                current_user = await asyncio.to_thread(self.client.current_user)
                if not current_user:
                    raise ValueError("Failed to get current user from Spotify")
                user_id = current_user["id"]

            result = await asyncio.to_thread(
                self.client.user_playlist_create,
                user=user_id,
                name=domain_playlist.name,
                description=domain_playlist.description or "",
            )

            if not result or "id" not in result:
                raise ValueError("Invalid response from playlist creation")

            playlist_id = result["id"]

            if domain_playlist.tracks:
                spotify_track_uris = [
                    f"spotify:track:{t.connector_track_ids['spotify']}"
                    for t in domain_playlist.tracks
                    if "spotify" in t.connector_track_ids
                ]
                if spotify_track_uris:
                    # Add tracks in batches of 100 (Spotify API limit)
                    for i in range(0, len(spotify_track_uris), 100):
                        batch = spotify_track_uris[i : i + 100]
                        await asyncio.to_thread(
                            self.client.playlist_add_items, playlist_id, batch
                        )

            return playlist_id

        except (KeyError, TypeError) as e:
            raise ValueError("Invalid response structure from Spotify API") from e
            raise ValueError("Invalid response structure from Spotify API") from e


def convert_spotify_track_to_domain(spotify_track: dict[str, Any]) -> Track:
    """Convert Spotify track data to domain model.

    Args:
        spotify_track: Raw track data from Spotify API

    Returns:
        Domain Track model with all available metadata
    """
    artists = [Artist(name=artist["name"]) for artist in spotify_track["artists"]]

    try:
        release_date = (
            datetime.strptime(spotify_track["album"]["release_date"], "%Y-%m-%d")
            if "release_date" in spotify_track["album"]
            else None
        )
    except ValueError:
        release_date = None

    track = Track(
        title=spotify_track["name"],
        artists=artists,
        album=spotify_track["album"]["name"],
        duration_ms=spotify_track["duration_ms"],
        release_date=release_date,
        isrc=spotify_track.get("external_ids", {}).get("isrc"),
    )

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
