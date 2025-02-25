# Narada

## Music Metadata Integration Platform

Narada is a powerful music metadata hub that integrates Spotify, Last.fm, and MusicBrainz to enable advanced playlist management and listening history synchronization.

Named after the divine sage Narada in Hindu tradition, who traverses different worlds carrying knowledge and information between realms - just as this tool bridges different music platforms.

## Core Capabilities

- **Cross-Service Entity Resolution**: Map tracks across Spotify, Last.fm, and MusicBrainz
- **Playlist Transformation Engine**: Sort, filter, and combine playlists based on customizable criteria
- **Listening History Integration**: Sync likes, scrobbles, and metadata across services
- **Personal Music Data Ownership**: Maintain a local database of your music interactions and preferences

## Key Features

- **Spotify Likes to Last.fm Loves**: Automatically sync your liked tracks to Last.fm
- **Play Count Sorting**: Sort Spotify playlists by your personal listening history
- **Smart Discovery Playlists**: Create filtered playlists based on complex criteria (release date, play count, etc.)
- **Backup and Portability**: Export playlists for cross-service migration

## Architecture

Narada is built with a domain-driven design approach, emphasizing:

- Clean separation between core domain and external services
- Event-sourced playlist management for complete history
- Efficient entity resolution with cached metadata mappings
- Functional composition for playlist transformations

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/narada.git
cd narada

# Install dependencies with Poetry
poetry install

# Set up environment variables
cp .env.example .env
# Edit .env with your API credentials
```

## Configuration

Create a `.env` file with your API credentials:

```
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
LASTFM_API_KEY=your_api_key
LASTFM_API_SECRET=your_api_secret
LASTFM_USERNAME=your_username
```

## Usage

### Sync Spotify Likes to Last.fm

```bash
narada sync-likes
```

### Sort a Playlist by Play Count

```bash
narada sort-playlist --playlist "Your Playlist Name" --by playcount
```

### Create a Fresh Releases Playlist

```bash
narada create-discovery --sources "Playlist1,Playlist2" --max-age 6 --exclude "Not These"
```

## Development

Narada uses Poetry for dependency management and SQLite for local storage:

```bash
# Run tests
poetry run pytest

# Initialize database
poetry run narada init-db
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.