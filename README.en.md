<div align="center">

# Aliasarr

### Next-Generation Autonomous PVR Suite for TV Series, Movies, and Anime

**Specialized media management system with native support for multilingual aliases, split-cours (+offset), hardlinks, lossless movie merging, movie collections, and diverse tracker ecosystems.**

---

[![Release: v3.4.0](https://img.shields.io/badge/Release-v3.4.0-6838f7?style=for-the-badge&logo=github&logoColor=white)](https://github.com/lQwestl/aliasarr/releases/tag/v3.4.0)
[![Docker](https://img.shields.io/badge/Docker-ghcr.io%2Flqwestl%2Faliasarr-00F0FF?style=for-the-badge&logo=docker&logoColor=black)](https://github.com/lQwestl/aliasarr/pkgs/container/aliasarr)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-3b82f6?style=for-the-badge)](http://www.gnu.org/licenses/gpl.html)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-10b981?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-059669?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![UI: Vanguard Luxe](https://img.shields.io/badge/Design-Vanguard%20Luxe%20%2F%20Neo--Glass-a855f7?style=for-the-badge)](https://github.com/lQwestl/aliasarr)
[![i18n: RU | EN](https://img.shields.io/badge/i18n-RU%20%7C%20EN-e11d48?style=for-the-badge)](README.md)

<p align="center">
  <a href="README.md">Русский</a> | <b>English</b>
</p>

</div>

---

## Table of Contents

1. [About the Project & Concept](#about-the-project--concept)
2. [Interactive UI Showcase](#interactive-ui-showcase)
3. [Key Advantages & Killer Features](#key-advantages--killer-features)
   - [Scoped Aliases & Offset (+Number Shifting)](#1-scoped-aliases--offset-number-shifting)
   - [Lossless Movie Merger (Multi-Part Releases)](#2-lossless-movie-merger-multi-part-releases)
   - [Movie Editions & TMDb Franchises (Sagas)](#3-movie-editions--tmdb-franchises-sagas)
   - [Diverse Tracker Ecosystem & Naming Quirks](#4-diverse-tracker-ecosystem--naming-quirks)
   - [Hardlinks & Selective Seeding](#5-hardlinks--selective-seeding)
   - [3-Level Upgrade Hierarchy & Downgrade Protection](#6-3-level-upgrade-hierarchy--downgrade-protection)
   - [Companion Files (Subtitles, Audio) & Fonts](#7-companion-files-subtitles-audio--fonts)
4. [Feature Comparison Matrix: Aliasarr vs Sonarr vs Radarr](#feature-comparison-matrix-aliasarr-vs-sonarr-vs-radarr)
5. [Quickstart (Docker & Docker Compose)](#quickstart-docker--docker-compose)
6. [Environment Variables and Volume Structure](#environment-variables-and-volume-structure)
7. [System Architecture](#system-architecture)
8. [Security, RBAC, and Audit](#security-rbac-and-audit)
9. [REST API and Automation](#rest-api-and-automation)
10. [Documentation and Guides](#documentation-and-guides)
11. [License](#license)

---

## About the Project & Concept

Popular PVR tools (Sonarr and Radarr) were originally built around the Western release scene with rigid standards for English title matching and flat season numbering. When dealing with international, bilingual, and anime trackers, users inevitably hit fundamental limitations:
- **Inability to discover releases by localized, Japanese (Kanji/Romaji), or alternative titles**;
- **Split-cours and multi-part seasons (Part 1, Part 2, Cour 1, Cour 2)**: tracker releases often number files starting from episode 01 for each part, while TheTVDB / TMDB catalog them as a continuous single season. Without offset shifting, importing the second part overwrites the first batch of episodes;
- **Non-standard release structures**: patterns such as *«01-08 of 12»*, *«Seasons 1-3»*, Roman numerals (*«Season II»*), and local voiceover studios (*LostFilm*, *HDRezka*, *Red Head Sound*, *AniLibria*, etc.);
- **Multi-disc movie releases (CD1/CD2)**: require manual merging or separate file naming before import;
- **Workflow fragmentation**: separate instances for series (Sonarr) and movies (Radarr), requiring double the maintenance, resources, and configuration.

**Aliasarr** solves all of these challenges out of the box, uniting management for **movies, TV series, and anime in a single lightweight service** with a lightning-fast **Vanguard Luxe / Neo-Glass** web UI that requires no Node.js build pipelines.

---

## Interactive UI Showcase

Aliasarr's interface is crafted with modern Neo-Glass and Vanguard Luxe design principles: translucent glass panels, responsive layout, micro-interactions, rich themes, and thoughtful ergonomics.

### 1. Main Dashboard & Media Monitoring
Comprehensive analytics across your entire library (TV shows, movies, anime), monitor statuses, disk usage, partition health, an interactive upcoming calendar graph, recent grabs, and active indexer health checks.

<div align="center">
  <img src="docs/screenshots/01_dashboard.jpg" alt="Aliasarr Dashboard" width="100%">
  <p><i>Main dashboard for library monitoring, system health, and active indexers</i></p>
</div>

---

### 2. Media Library: Display Modes for Every Workflow
Aliasarr supports three distinct library viewing modes:

#### A. Poster Grid (Neo-Glass Posters Grid)
Rich posters featuring floating glass completion badges (e.g. `12 / 12`), micro-progress bars, quality profile badges, and an alphabetical quick-jump bar.
<div align="center">
  <img src="docs/screenshots/02_library_grid.jpg" alt="Media Library — Poster Grid" width="100%">
  <p><i>Neo-Glass poster grid with floating badges and filtering</i></p>
</div>

#### B. Card Style Customization
A real-time modal allows switching between visual styles: **Neo-Glass (Floating Badges — Flagship)**, **Cinematic Luxe (Gradient overlay)**, and **Classic (Standard bottom progress bar)**.
<div align="center">
  <img src="docs/screenshots/03_card_styles_modal.jpg" alt="Card Style Customization" width="75%">
  <p><i>Card style selection modal for fine-tuning library visuals</i></p>
</div>

#### C. Table View
A compact and dense view designed for rapid bulk library auditing: exact ratings, studios/networks, season counts, episode progress, air statuses, and immediate actions.
<div align="center">
  <img src="docs/screenshots/04_library_table.jpg" alt="Media Library — Table View" width="100%">
  <p><i>Dense table mode for swift navigation and large collection management</i></p>
</div>

#### D. Overview View
Expanded hero cards featuring full synopses, genres, premiere dates, and next episode air dates.
<div align="center">
  <img src="docs/screenshots/05_library_overview.jpg" alt="Media Library — Overview View" width="100%">
  <p><i>Detailed overview mode displaying expanded descriptions and metadata</i></p>
</div>

---

### 3. Movie Collections & Franchises (TMDb Movie Sagas)
A dedicated experience for cinema enthusiasts: automatic grouping of movies into official sagas and franchises (*«Avatar»*, *«Dune»*, *«Star Wars»*, *«Marvel Cinematic Universe»*, etc.).
The saga card organizes titles chronologically by premiere date, complete with a **1-click «Add Missing Movies»** action.

<div align="center">
  <img src="docs/screenshots/06_collections_franchises.jpg" alt="Movie Collections and Franchises" width="100%">
  <p><i>Movie collections and sagas catalog with completion tracking</i></p>
</div>

<div align="center">
  <img src="docs/screenshots/07_collection_modal.jpg" alt="Interactive Franchise Modal" width="75%">
  <p><i>Franchise modal displaying chronological release order and bulk library addition</i></p>
</div>

---

### 4. Smart Blocklist with Detailed Rejection Reasons
Automatic isolation of corrupt releases, fakes, and releases missing intended audio tracks. Every blocked item preserves the exact reason: *«Release does not contain wanted episodes»*, *«No seeders»*, *«Missing requested audio»*, *«Poor video/audio quality»*, *«Import failed»*.
<div align="center">
  <img src="docs/screenshots/08_blocklist.jpg" alt="Release Blocklist" width="100%">
  <p><i>Blocklist manager with rejection reason filtering and manual unblocking</i></p>
</div>

---

### 5. Activity & Download Queue
Real-time progress monitoring across all connected download clients (Transmission, qBittorrent, etc.): client instance name, download/upload rates, remaining seeding time under tracker rules, exact progress, and manual controls.
<div align="center">
  <img src="docs/screenshots/09_activity_queue.jpg" alt="Activity and Download Queue" width="100%">
  <p><i>Interactive download queue with transfer rate telemetry and seeding timers</i></p>
</div>

---

### 6. Premieres & Releases Calendar
Interactive calendar with monthly and weekly viewports. Color-coded status markers (*Unaired*, *Airing*, *Downloading*, *Downloaded*, *Missing*), premiere and finale flags, and **iCalendar (`.ics`) export** for live synchronization with Apple, Google, and mobile calendar apps.
<div align="center">
  <img src="docs/screenshots/10_calendar.jpg" alt="Aliasarr Releases Calendar" width="100%">
  <p><i>Interactive episode air date and movie release calendar with iCal export</i></p>
</div>

---

### 7. Release Lifecycle History
Transparent audit for every processed release: visual pipeline stages **Search $\to$ Grab $\to$ Decision $\to$ Download $\to$ Import** indicating the trigger (automated search / manual grab) and origin indexer.
<div align="center">
  <img src="docs/screenshots/11_history.jpg" alt="Release History Log" width="100%">
  <p><i>Step-by-step history log recording every cycle of release processing</i></p>
</div>

---

### 8. Settings Center & Visual Customization
Granular control over API keys, integrations, UI language (RU/EN), color palettes (*Neon Midnight*, *Obsidian*, *Dracula*, *Light*), scrollbar behavior (autohide), and switching between **Classic Neo-Glass** and **Vanguard Luxe** design aesthetics.
<div align="center">
  <img src="docs/screenshots/12_settings.jpg" alt="System and UI Settings" width="100%">
  <p><i>Settings control panel for system configuration, API access, and theme customizers</i></p>
</div>

---

### 9. Security: Administrative Audit Logs
Chronological audit trail of all administrative and background operations: metadata synchronization, episode removals, settings changes, authentication events with user origin (`admin` / `scheduler`), timestamps, and client IP addresses.
<div align="center">
  <img src="docs/screenshots/13_audit_logs.jpg" alt="Audit Activity Logs" width="100%">
  <p><i>Detailed audit logs ensuring transparency and administrative security</i></p>
</div>

---

### 10. Backups, Rotation, and Instant Rollback
Generate full and configuration snapshots as ZIP + SQLite dumps. Automated scheduling, flexible retention policy (keeping last N snapshots), and the **Safety Rollback Snapshot** mechanism — automatically saving a fallback point immediately before applying any backup.
<div align="center">
  <img src="docs/screenshots/14_backups.jpg" alt="Backup and Restore Center" width="100%">
  <p><i>Backup management hub for scheduling, retention policies, and database restoration</i></p>
</div>

---

### 11. Fully-Featured REST API (Swagger / OpenAPI 3.1)
Built-in interactive Swagger UI documentation (`/docs`), covering every endpoint for managing titles, seasons, episodes, aliases, split-cours, indexers, and download clients.
<div align="center">
  <img src="docs/screenshots/15_api_swagger.jpg" alt="Swagger OpenAPI Documentation" width="100%">
  <p><i>Interactive Swagger / OpenAPI 3.1 console for external integrations and scripting</i></p>
</div>

---

## Key Advantages & Killer Features

### 1. Scoped Aliases & Offset (+Number Shifting)
Many popular anime and television series are cataloged on TheTVDB / TMDB as a **single season with continuous numbering** (e.g., 24–26 episodes in Season 1). Release groups on trackers, however, routinely package them as split-cours:
- **Part 1**: `Space Dandy TV-1 [01-13]`
- **Part 2**: `Space Dandy TV-2 [01-13]` or `Space Dandy 2nd Season [01-13]`

The **Scoped Aliases & Offset** feature links a search alias to a specific season/episode range and applies a mathematical offset formula:

$$\text{Episode Number in Library} = \text{Episode Number in Torrent} + \text{Offset}$$

$$\text{Offset} = \text{Starting Episode Number in Card} - \text{Starting Episode Number in Release}$$

| Title & Part | Episodes in Card | Numbering on Tracker | Card Season | Range (From–To) | Offset | Resulting Match |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Space Dandy (Part 1)** | 1–13 | 01–13 | `1` | `1 – 13` | **0** | File `01.mkv` $+ 0 \to$ **S01E01** |
| **Space Dandy (Part 2)** | 14–26 | 01–13 | `1` | `14 – 26` | **+13** | File `01.mkv` $+ 13 \to$ **S01E14** |
| **Mushoku Tensei (Part 2)** | 12–23 | 01–12 | `1` | `12 – 23` | **+11** | File `01.mkv` $+ 11 \to$ **S01E12** |
| **Bleach: TYBW (Part 2)** | 14–26 | 01–13 | `1` | `14 – 26` | **+13** | File `01.mkv` $+ 13 \to$ **S01E14** |
| **Spy x Family (Part 2)** | 13–25 | 01–13 | `1` | `13 – 25` | **+12** | File `01.mkv` $+ 12 \to$ **S01E13** |

> [!TIP]
> Learn more in the [Scoped Aliases and Offsets Guide](docs/scoped_aliases_and_offsets.en.md).

---

### 2. Lossless Movie Merger (Multi-Part Releases)
- **Automatic Part Detection**: Identifies `CD1/CD2`, `Part 1/Part 2`, `Disc 1/Disc 2`, `Pt 1/Pt 2` patterns seamlessly.
- **Lossless Concatenation**: Merges all video, audio tracks, subtitles, and chapters without re-encoding via `mkvmerge` (MKVToolNix) with fallback to `ffmpeg -f concat -c copy`.
- **100% Seeding-Safe**: Download directory files are opened **strictly in Read-Only mode**. Active torrent seeding in your client is never interrupted or corrupted.
- **Clean Fallback**: If system merge tools are absent, files are imported according to Plex/Jellyfin multi-part standards (`Movie - part1.mkv`, `Movie - part2.mkv`).

---

### 3. Movie Editions & TMDb Franchises (Sagas)
- **Edition Recognition**: Extracts cut editions: *Director's Cut*, *Extended Edition*, *Special Extended Edition (SEE)*, *Theatrical Cut*, *IMAX Enhanced*, *Unrated / Uncut*, *Remastered*, *Criterion Collection*, *Open Matte*, etc.
- **Naming Tokens**: The `{Movie Edition}` token cleanly strips empty parentheses when no specific edition is detected.
- **Movie Sagas**: Native TMDb franchise navigation directly in your library with 1-click batch discovery and addition of missing installments.

---

### 4. Diverse Tracker Ecosystem & Naming Quirks
- **Smart Episode Parser (1400+ lines regex)**:
  - Formats: `S01E05`, `1x05`, `01-12`, «01-08 of 12» (recording total aired episodes), Roman numerals (`Season II`), ordinal prefixes (`1st Season`, `2nd Season`).
  - Studio & Voiceover tagging: *LostFilm*, *HDRezka*, *Red Head Sound*, *Cube in Cube*, *AniLibria*, *AniMedia*, *Studio Band*, etc.
  - Multi-language identification: distinct badges for `RU`, `EN`, `JP`, `MULTI`, `DUAL`.
  - Ongoing thread monitoring on trackers by `topic_guid` and URL, downloading only newly added episodes.
- **Global Non-Video Content Filtering**:
  - Strict pruning of light novels, manga, comics, artbooks, scans, audiobooks, soundtracks, and e-books (`.epub`, `.fb2`, `.pdf`, `.cbr`, `[vols 1-11]`).
  - Protection against false positive matches on spin-offs and live-action adaptations.

---

### 5. Hardlinks & Selective Seeding
- **0 Bytes Used & 0 ms Import**: Instant file linking regardless of size (even an 80 GB 4K Remux) without duplicating disk storage.
- **Per-Tracker Seeding Rules**: Custom Seed Ratio and Seed Time thresholds for each individual tracker.
- **Safe Cleanup**: When seeding quotas are satisfied, the torrent is removed from the client while the library file remains intact (Inode reference count decrements).
- **Automatic Fallback**: Transparently and safely copies files across separate filesystem pools when hardlinks are physically unsupported.

> [!NOTE]
> Learn more in the [Hardlinks, Indexers, and Download Clients Guide](docs/hardlinks_indexers_and_clients.en.md).

---

### 6. 3-Level Upgrade Hierarchy & Downgrade Protection
- **Three Tiers of Quality Upgrades**:
  1. *Global Quality Profile* (`QualityProfile.upgrade_allowed` + Cutoff Quality & Score thresholds).
  2. *Title Card* («Upgrading» toggle with auto-reset once cutoff target is reached).
  3. *Granular Episode/Season* (manual upgrade request for a specific episode).
- **Downgrade Protection**:
  - Before replacing an existing file, Aliasarr inspects the downloaded video file using MediaProbe/ffprobe.
  - If the actual media quality is inferior to the existing file on disk (for instance, a torrent header claimed 1080p but contained 480p), the replacement is **blocked**, the current file is preserved, and the bogus torrent is removed from the client.

> [!TIP]
> Learn more in the [Quality Upgrades and Tracking Guide](docs/quality_upgrades_and_tracking.en.md).

---

### 7. Companion Files (Subtitles, Audio) & Fonts
- **Subtitles and Audio**: Automatically transfers external subtitles (`.srt`, `.ass`, `.ssa`, `.vtt`) and audio streams (`.mka`, `.ac3`, `.flac`).
- **Anime Font Kits**: Copies companion font directories (`.ttf`, `.otf`) while writing `.plexignore` / `.embyignore` markers to prevent media servers from indexing fonts as media.
- **Clutter Filtration**: Discards openings (OP), endings (ED), samples, promos, trailers, and PV/CM files.

### 8. Changing a Title's Folder Without Losing Links
- **Pick the folder in the interface**: the "Change Folder" button on a title card opens the filesystem browser — navigate to an existing folder, type a path by hand, or create a new one.
- **Two modes**: move the contents of the old folder into the new one (episode paths in the database follow, the emptied folder is removed), or only update the stored path when the files were already relocated on the NAS.
- **Preview before applying**: how many files and how much data would move, whether the target folder exists, and whether another title already claims it.
- **No silent overwrites**: entries whose names already exist in the target are left in place and reported as conflicts in the operation result.

---

---

## Feature Comparison Matrix: Aliasarr vs Sonarr vs Radarr

| Capability | Aliasarr | Sonarr v4 | Radarr v5 |
| :--- | :---: | :---: | :---: |
| **All-in-One Suite (Movies + TV Series + Anime)** | **Yes (Unified Service)** | No (TV Series Only) | No (Movies Only) |
| **Multilingual Aliases (EN / RU / JP / Kanji)** | **Native (`/`, `\|` splitting)** | Limited | Limited |
| **Scoped Aliases (+Offset Shifting for Split-Cours)** | **Native with formulas** | No | Not Applicable |
| **Season Splitter (Split-Cour / Part 1, 2)** | **Built-in editor** | No | Not Applicable |
| **Lossless Movie Merger (CD1+CD2 Concatenation)** | **Automatic (mkvmerge/ffmpeg)** | No | Requires manual merge |
| **TMDb Sagas & Franchises (1-Click Collection Import)**| **Native with saga progress**| No | Basic Lists |
| **Regional Tracker Parsing («01-08 of 12», dub groups)**| **100% Comprehensive** | Frequently fails | Frequently fails |
| **Ongoing Tracker Thread Sync (Selective Updates)** | **Yes (Incremental Grabs)** | No | No |
| **Downgrade Protection (MediaProbe Inspection)** | **Yes (Real File Inspection)**| Header-based only | Header-based only |
| **Per-Tracker Seeding Rules (Ratio / Time Limits)** | **Customized per Tracker** | Limited | Limited |
| **Built-in pure-Python Media Inspector** | **Yes (Zero Dependencies)** | Requires ffprobe | Requires ffprobe |
| **2FA TOTP & RBAC (Role-Based Access Control)** | **Native in Web UI** | No | No |
| **Autonomous 100-Year Self-Signed SSL** | **Yes (Auto-Renewing)** | No | No |
| **Zero-Build Vanilla SPA Interface** | **Yes (0 ms build, instant load)**| Heavy Webpack build | Heavy Webpack build |

---

## Quickstart (Docker & Docker Compose)

The fastest and most reliable deployment method is using the pre-built container from the GitHub Container Registry (GHCR).

### 1. Launch with Docker Compose (Recommended)

Create a `docker-compose.yml` file:

```yaml
version: "3.8"

services:
  aliasarr:
    image: ghcr.io/lqwestl/aliasarr:latest
    container_name: aliasarr
    restart: unless-stopped
    ports:
      - "8989:8989"   # HTTP Web UI and REST API
      - "9898:9898"   # HTTPS port (when SSL is enabled)
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=UTC
      # - DATABASE_URL=sqlite:////config/aliasarr.db   # Default SQLite WAL
    volumes:
      - ./config:/config                  # Database, settings, certs, and backups
      - /mnt/storage/downloads:/downloads # Torrent client download directory
      - /mnt/storage/media:/media         # Media library (movies, series, anime)
```

Start the container:

```bash
docker compose up -d
```

Access the web interface at `http://localhost:8989` (or `https://localhost:9898` when SSL is enabled).

---

### 2. Launch via Docker CLI

```bash
docker run -d \
  --name=aliasarr \
  --restart=unless-stopped \
  -p 8989:8989 \
  -p 9898:9898 \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=UTC \
  -v $(pwd)/config:/config \
  -v /mnt/storage/downloads:/downloads \
  -v /mnt/storage/media:/media \
  ghcr.io/lqwestl/aliasarr:latest
```

---

## Environment Variables and Volume Structure

### Volume Mounting Strategy
For **Hardlinks** to operate with maximum speed and zero storage duplication, the downloads directory and media library must reside within the **same filesystem mount**:

```
/mnt/storage/
├── downloads/      <-- Inbound downloads directory for qBit / Transmission
└── media/
    ├── serials/    <-- Root series directory
    ├── films/      <-- Root movies directory
    └── anime/      <-- Root anime directory
```

### Key Environment Variables

| Variable | Default Value | Description |
| :--- | :---: | :--- |
| `PUID` | `1000` | Linux User ID for file creation permissions |
| `PGID` | `1000` | Linux Group ID for file creation permissions |
| `TZ` | `UTC` | Server timezone for calendar and background scheduling |
| `DATABASE_URL` | `sqlite:////config/aliasarr.db` | Database URI (`sqlite://` and `postgresql+psycopg2://` supported) |
| `ALIASARR_PORT` | `8989` | HTTP server port |
| `ALIASARR_BACKUP_DIR` | `/config/backups` | Directory for storing automated backups |
| `ALIASARR_TRUSTED_PROXIES` | empty | Comma-separated trusted reverse proxy IPs/CIDRs for `X-Forwarded-For` and `CF-Connecting-IP` |

---

## System Architecture

```
                             ┌──────────────────────────────────────┐
                             │        Web Browser / Clients         │
                             │  (Vanguard Luxe / Neo-Glass SPA UI)  │
                             └──────────────────┬───────────────────┘
                                                │ REST API / WebSocket
                                                ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│                                   FastAPI Core                                    │
│                                                                                   │
│  ┌─────────────────┐    ┌──────────────────┐    ┌──────────────────────────────┐  │
│  │   Auth & RBAC   │    │  DecisionEngine  │    │      Metadata Provider       │  │
│  │  (2FA / Cookies)│    │ (Scores, Cutoff) │    │(TMDB, TVMaze, SkyHook, TVDB) │  │
│  └─────────────────┘    └────────┬─────────┘    └──────────────────────────────┘  │
│                                  │                                                │
│  ┌───────────────────────────────────────────────┐   ┌─────────────────────────┐  │
│  │        Universal Parser & Release Matcher     │   │   APScheduler Workers   │  │
│  │ (Scoped Aliases, SXXEXX, Anime, Split-Cour)   │   │  (AutoSearch, Monitor)  │  │
│  └───────────────────────┬───────────────────────┘   └────────────┬────────────┘  │
└──────────────────────────┼────────────────────────────────────────┼───────────────┘
                           │                                        │
           ┌───────────────┴───────────────┐        ┌───────────────┴───────────────┐
           ▼                               ▼        ▼                               ▼
┌──────────────────────┐       ┌──────────────────────┐ ┌───────────────────────────┐
│   Torznab / Nyaa     │       │   Download Clients   │ │      Postprocess Hub      │
│     Indexers         │       │ (qBit, Transmission, │ │ (Hardlinks, Lossless Merge│
│(RateLimiter, Backoff)│       │  Deluge, rTorrent)   │ │  MediaProbe, Cleanups)    │
└──────────────────────┘       └──────────────────────┘ └─────────────┬─────────────┘
                                                                      │ Inode Link / Concat
                                                                      ▼
                                                        ┌───────────────────────────┐
                                                        │       Media Library       │
                                                        │  (Plex, Jellyfin, Emby)   │
                                                        └───────────────────────────┘
```

---

## Security, RBAC, and Audit

1. **Role-Based Access Control (RBAC)**:
   - `Admin` — Full access to settings, user management, backups, and library.
   - `Manager` — Library management, quality profiles, and indexer settings.
   - `User` — Adding titles and manual release grabbing.
   - `Viewer` — Read-only access to library items and calendar schedules.
2. **Two-Factor Authentication (2FA TOTP)**:
   - Compatible with Google Authenticator, Aegis, 1Password, Bitwarden.
   - Generates one-time emergency recovery codes.
3. **Autonomous Self-Signed SSL**:
   - Automated generation of RSA 2048 X.509 certificates with maximum validity (~100 years).
   - Automatic renewal 30 days prior to expiration.
4. **Safety Rollback Snapshot**:
   - Creates an automated database snapshot immediately before restoring any backup for zero-risk rollbacks.

---

## REST API and Automation

Aliasarr exposes an open RESTful API with integrated Swagger documentation (`/docs`):

```bash
# Get all titles in library
curl -X GET "http://localhost:8989/api/v1/shows" \
  -H "X-Api-Key: YOUR_API_KEY"

# Add a scoped search alias with offset (+Offset)
curl -X POST "http://localhost:8989/api/v1/shows/42/aliases" \
  -H "X-Api-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Space Dandy TV-2",
    "season_number": 1,
    "episode_from": 14,
    "episode_to": 26,
    "episode_offset": 13
  }'

# Trigger an immediate search for wanted episodes
curl -X POST "http://localhost:8989/api/v1/wanted/search" \
  -H "X-Api-Key: YOUR_API_KEY"
```

---

## Documentation and Guides

- [Hardlinks, Indexers, and Download Clients Guide](docs/hardlinks_indexers_and_clients.en.md)
- [Scoped Aliases, Split-Cours, and Episode Offsets Guide](docs/scoped_aliases_and_offsets.en.md)
- [3-Level Quality Upgrades and Release Tracking Guide](docs/quality_upgrades_and_tracking.en.md)
- [Interactive Built-in Wiki](web/wiki.html) (accessible directly in the application menu)

---

## License

This project is licensed under the **[GNU General Public License v3.0](LICENSE)**. You are free to use, modify, and distribute the code under the condition that derivative works remain open-source.

<div align="center">
  <sub>Engineered with care for cinema, television, and anime enthusiasts. Aliasarr Team.</sub>
</div>
