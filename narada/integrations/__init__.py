"""Service connectors for external music platforms and APIs."""

# Import main connector classes for re-export
from narada.integrations.lastfm import (
    LastFmConnector,
    LastFmPlayCount,
    convert_lastfm_track_to_domain,
)
from narada.integrations.musicbrainz import MusicBrainzConnector
from narada.integrations.spotify import (
    SpotifyConnector,
    convert_spotify_playlist_to_domain,
    convert_spotify_track_to_domain,
)

# Define public API with explicit exports
__all__ = [
    "LastFmConnector",
    "LastFmPlayCount",
    "MusicBrainzConnector",
    "SpotifyConnector",
    "convert_lastfm_track_to_domain",
    "convert_spotify_playlist_to_domain",
    "convert_spotify_track_to_domain",
]
