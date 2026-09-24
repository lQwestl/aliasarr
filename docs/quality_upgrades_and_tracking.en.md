<p align="right">
  <a href="quality_upgrades_and_tracking.md">Русский</a> | <b>English</b>
</p>

# Guide: Quality Upgrades, 3-Level Hierarchy, and Tracker Sync in Aliasarr

This document provides a detailed overview of the architecture and mechanics governing media file quality upgrades, downgrade protection, and optimized ongoing release tracking on torrent trackers within **Aliasarr**.

---

## 1. Three Levels of Upgrade Management (Hierarchy)

Aliasarr features a flexible 3-tier system for managing media library quality upgrades:

```
┌──────────────────────────────────────────────────────────────┐
│  Level 3: Episode / Season (ep.upgrade_requested)            │ ──► Highest Priority
├──────────────────────────────────────────────────────────────┤
│  Level 2: Entire Title (show.upgrade_requested)              │ ──► High Priority
├──────────────────────────────────────────────────────────────┤
│  Level 1: Quality Profile (QualityProfile.upgrade_allowed)   │ ──► Background Mode
└──────────────────────────────────────────────────────────────┘
```

### Level 1: Global Quality Profile (`QualityProfile`)
- **Parameters:**
  - `upgrade_allowed` (auto-upgrade permission flag).
  - `cutoff_quality` (baseline quality threshold, e.g., `Bluray-1080p`).
  - `cutoff_score` (custom format quality score threshold, e.g., `150`).
- **Operation:**
  - If `upgrade_allowed` is enabled in the profile, the automated background search scheduler inspects all monitored episodes of the title. If the quality of an existing file is below `cutoff_quality` or its score is below `cutoff_score`, the system searches for an upgraded release.
  - As soon as an episode reaches `cutoff_quality` (and `cutoff_score`), it is marked as completed and will no longer be re-downloaded in the background.
  - If `upgrade_allowed` is disabled, the system downloads a release once and never searches for replacements in background mode.

### Level 2: Title Card Button ("Upgrading")
- **Parameter:** `show.upgrade_requested`
- **UI Icon:** Upward arrow inside a circle (`arrow-up-circle`).
- **Operation:**
  - An explicit user request to upgrade a specific series or movie.
  - Always active, even if `upgrade_allowed` is disabled globally in the quality profile.
  - All episodes of the title that have not yet reached the target cutoff threshold participate in automated upgrade searches.
  - **Automatic Reset:** As soon as the target quality cutoff is reached and imported for all episodes of the title, the `show.upgrade_requested` flag is **automatically reset**, and the "Upgrading" status badge turns off.

### Level 3: Granular Episode or Season Icon
- **Parameter:** `episode.upgrade_requested`
- **UI Icon:** Upward arrow inside a circle (`arrow-up-circle`).
- **Operation:**
  - Allows targeting an individual episode for re-download (e.g., if an episode was released with inferior audio or watermarks) or an entire season via the button in the season header.
  - Upon successful download and import of the improved file, the `episode.upgrade_requested` flag is **automatically reset to `False`**, and the icon highlighting is cleared.

---

## 2. Downgrade Protection and Fake Release Filtering

### The Problem:
Occasionally, a torrent release title on an indexer advertises high quality (such as `WEB-DL 1080p`), but the files inside the archive or directory are actually low resolution (such as `480p XviD Web-DLRip`).

### How Aliasarr Protects:
1. **Physical File Inspection**: When a download completes in the torrent client, the import module inspects the actual physical properties of the downloaded files (resolution, codec, media tags).
2. **Rank Comparison**: If the existing file on disk has a higher rank (e.g., `HDTV-1080p`, rank 17) and the downloaded candidate has a lower rank (e.g., `480p`, rank 10), the replacement is **blocked**.
3. **Restoration and Cleanup**:
   - The existing high-quality file remains untouched and safe.
   - The episode status in the database is restored to `DOWNLOADED`.
   - The defective or low-quality release is **immediately removed from the torrent client** along with its downloaded files.
   - The infohash of this release is automatically appended to the **Blocklist** with the reason recorded (import rejected due to attempted downgrade), preventing recursive download loops.

---

## 3. Optimized Ongoing Tracking (`tracker_sync`)

### How `TrackedRelease` Operates:
- When a release is grabbed for an ongoing series, a tracker topic tracking record is established.
- The background scheduler routinely queries indexers to detect new episode additions in that same topic.

### Optimization Rules:
- Only releases for **actively monitored titles** (`Show.monitored == True`) with remaining unobtained episodes (`WANTED`, `UNAIRED`) are queried.
- If a series is unmonitored or concluded (all episodes downloaded, status `ended` or `completed`), tracking is **automatically deactivated (`active = False`)**.
- For movies, tracking is deactivated immediately following successful import.
- This shortens background checking cycles from tens of minutes down to seconds while safeguarding against indexer rate limits.

### Favorite release for a season
- Open a season's interactive search and click the star beside a release. Aliasarr verifies its GUID with the original indexer and pins that topic to the season. Only one release can be pinned per season.
- General auto-search skips that season while continuing to search other seasons. The tracker job checks **only the same topic on the same indexer**; an updated torrent is sent through the normal selective-download and import path for wanted episodes.
- An unavailable topic or indexer does not trigger an automatic fallback to other releases. The check status appears in the season search dialog. Unpinning restores general auto-search.
- Update detection prefers the `.torrent` infohash. If neither a torrent file nor a hash is available, it falls back to release size, publication date, and title; changes invisible to those fields may be missed.
