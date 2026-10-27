# Stream Media

A third-party Hesper plugin with a streaming-app layout: **Home / Movies / TV Shows** tabs, a featured title,
rows (trending, top rated, coming soon, genres), **Categories**, streaming-service filters, ratings on every
poster, trailers, cast, director/creator, networks, and **Play**.

## Backdrop billboard
On a Hesper build that supports `ui.hero` (the bundled `plugin_sandbox.js` / `style.css` update), the featured title is a
full-width backdrop with title, rating, blurb and Play / Info buttons. Titles with no trailer also get a backdrop header.
On older builds the poster billboard is used instead, so nothing breaks.

## Layouts
Phone, tablet and TV each get their own layout: shorter rows and a compact billboard on phones; longer rows,
bigger posters, categories open and the menu bar first (remote friendly) on TV.

## What you see
- **Not out yet**: unreleased movies and shows get a "Not out yet" badge and message (with the date) instead of Play.
  Episodes that have not aired say the same.
- **No streaming links available**: shown when no stream can be found or none of the best three will start.

## Play
- **Movie:** open it and press Play.
- **TV show:** open it, pick a season, tap an episode.

Stream Media's built-in release search builds a query for that title/episode, fetches and scores the results, then Hesper buffers the start
and opens the player while the rest downloads. Closing the player stops the torrent and deletes the
temporary data. If several releases are found, the best match (quality + seeders) plays; turn on
**Settings > Playing > Let me choose the release** to pick yourself. After playing, "Other releases"
lists the alternatives in case one was bad.

## What you need
1. **Nothing to set up for TMDb.** This plugin's own TMDb worker is used (see snake-skin-tmdb-worker.js). Optional: paste your own free v3 API key (themoviedb.org > Settings > API) in this plugin's Settings tab to use that instead.
2. **Search sites (no Torznab needed).** The list lives between the `SITES-START` / `SITES-END` markers in
   `ui.js` and `release_search.py`. Easiest: run `python add_site.py "https://site/search?q={q}"` (from the
   plugin folder's parent, see add_site.py); it adds the link to both files and the host to `plugin.json`.
   No sites are built in: Stream Media only searches the sites you add. Reinstall the plugin after changing sites.
3. **A Hesper build with the torrent engine** (otherwise the Play button says it can't play torrents).

## Permissions (shown when you install it)
- `network`: snake-skin-tmdb.aquariusibeats.workers.dev, api.themoviedb.org, image.tmdb.org, www.youtube-nocookie.com
- `storage`: its own settings (an optional own TMDb key, trailer options)
- `library`: its Python part reads titles + years (not file names) to mark "In library"
- `torrent`: start streams through Hesper

Data: TMDb. Streaming availability: JustWatch (via TMDb). Trailers: YouTube.


## Faster starts (2.5.1)
- Releases are matched on the whole title ("Breaking Bad"), so look-alikes such as "The Bad Guys: Breaking In" are no longer picked.
- Smaller releases are preferred (Settings: "Prefer smaller files"): a 0.9 GB 720p episode starts sooner and keeps up on a slow
  connection where a 2.5 GB 1080p one stalls. Remux and 4K releases are ranked last. Turn the setting off for maximum quality.


## Resume Watching (2.6.0)
What you start from here shows up under Resume Watching in Hesper. It keeps your place, and picking it there starts the same release again at that spot. Needs a Hesper build that supports it; on older builds playback works as before.

## Favorites, Watch on..., other plugins (2.7.0)
- **♡ Add to favorites** on a title's page adds it to Hesper's Favorites tab (shared with TMDb Discover). Pressing it there opens it here.
- "Where to watch" is now a row of service buttons with logos (Netflix, Hulu ...) that open the service's app on Android or its website. Titles on no service list nothing.
- If another installed plugin can play titles, a **Play with another plugin** button is shown for released titles.
- plugin.json: `"provides": {"stream": true}` lets other plugins offer a "Play with Stream Media" button. New permissions: `favorites`, `providers`, `plugins`.

## Up next (2.8.0)

Near the end of an episode started from this plugin, PEK can offer the next one on the right side of the player. Stream Media checks that the next episode has aired and that a stream exists for it, then plays it when you press **Play now** (or automatically 5 seconds after the episode ends, unless you cancel). If the next episode is in your own library folders, PEK offers that one first.

## Matched to your device (2.9.0)

Releases are now ranked for the device they will play on. PEK checks which video formats the hardware decodes (H.264, HEVC, 10-bit HEVC / HDR10, AV1), the screen size and whether it shows HDR, and Stream Media uses that when it scores releases:

- **A device that can play it** (4K hardware decoding, 10-bit HEVC, an HDR screen or a TV) keeps 4K, HDR10 and Dolby Vision on top, with a much roomier size allowance.
- **A device that cannot** (for example a budget phone) pushes anything beyond its hardware decoder, such as 4K, 10-bit HEVC or 10-bit H.264, to the bottom of the list instead of stuttering on it. A 1080p or 720p H.264 release comes first.
- Releases that will probably stutter are marked **may stutter on this device** in the release list, and each row now shows its HDR / Dolby Vision / codec / Remux tags.
- If PEK cannot tell what the device can do (an older build, or not the Android app) nothing changes: the ranking is exactly the one from before.

Settings > Playing > **Match releases to this device** turns it off, and shows what was detected. This needs the new `device` permission (read-only: codecs, screen size, HDR, memory; no identifiers) and a PEK build that provides `pek.device.profile()`.

## Episode pictures and descriptions (2.10.0)

In a show's episode list, each episode now shows its still picture and a short description next to the title and air date.
This needs the PEK TV / Hesper build that has `ui.episodeRow` (shipped with this update); older builds keep the plain list.


## 3.2
- **Search suggestions:** movies and shows matching what you type appear under the search box (tap, or D-pad + OK, to open the info page).
- **Trailer button on phones:** stays on screen as a toggle and plays the trailer in a normal YouTube player with controls.
- Adds BT4G and apibay.org as release-search sources.

## Netflix look and trailers (2.11.0)

The whole screen now follows the Netflix layout (needs the PEK TV / PEK Android build that ships with this update; older builds keep the previous layout):

- **TV:** top bar (Home, TV Shows, Movies, Categories, search, settings), a full-width billboard that stays put while the rows scroll under it, wide tiles with a white focus border. Rest the D-pad on a title and the billboard switches to it; after a moment its trailer starts, muted (speaker button to unmute). The trailer ends and the artwork comes back, like Netflix.
- **Phone / tablet:** poster billboard with Play and My List, pill tabs, poster rows. Nothing plays by itself: you see the description, cast and episodes. A **Trailer** button on a title's page plays it on request.
- **How trailers play now:** PEK's own `/api/trailer` (new `trailer.h` in the backend) looks the video up and PEK plays it as a plain video, with no YouTube player or embed errors. If that is not available the billboard falls back to the YouTube frame. Settings > Trailers can turn it off.
- The release-search sites and everything about finding and starting streams are unchanged.


## 2.11.1: D-pad fixes
- **Rows no longer jump back to the top while you scroll with the D-pad.** Every time the highlight rested on a tile, the screen was redrawn for the billboard and the rows list restarted at the top. This needs the updated `www/plugin_sandbox.js` that ships with this release.
- **Trailers in PEK TV's TV / D-pad mode on a phone or tablet.** The plugin used to decide "TV" only from the screen's pointer type, so a touch device in D-pad mode was treated as a phone and never played trailers by itself. It now also asks PEK TV (`pek.isTv()`).
- Trailers also need the backend built with `trailer.h` (see `/api/trailer`); otherwise PEK TV falls back to the YouTube frame, which many WebViews refuse.

## 3.2.1 - steadier TV browsing
- A trailer lookup that failed (slow or dropped network) is retried after 15 s instead of being remembered as "no trailer" until restart.
- A trailer answer that arrives after you moved on no longer redraws the page, so it cannot snap focus back or make rows jump mid-move.
- Window "resize" events (fired by trailers starting, system bars, keyboard) only redraw on a real size change, at most once per 300 ms.

## 3.3.0 - Flutter UI (PEK Android)
`screen.py` is the Flutter version of this screen (plugin.json: `"flutter": {"screen": "screen.py"}`). `ui.js` is unchanged, so the web UI still works.
- Same TMDb worker, same permissions, same sites: the search sites are read from `release_search.py` (SITES-START / SITES-END), which is not modified.
- `stream_search.py` queries every site at the same time, follows listing pages (1337x style) and honours "Prefer smaller files".
- **Play** needs the small host hook in `host-torrent-play.patch` (`pek_ui.play_torrent`, the `torrent.play` effect, and its handler in `plugin_ui.dart`). Without it browsing works and Play shows an "update PEK" message.
- Episode pictures and descriptions use `pek_ui.episode_row` (also in the host patch); a PEK without it shows the plain list.
- Not in the Flutter screen (no equivalent in `pek_ui`): backdrop billboard / TV auto-preview, live search suggestions while typing, Up Next in the player, automatic retry of the next release if one will not start (the other releases are listed under "Other sources").
- Release ranking for the device turns on by itself if PEK passes a device profile in `ui.ctx()["device"]`; until then the usual ranking is used.


## 3.4.0
- Trailer error 153 fixed (the player is now loaded with a proper referrer, in PEK TV's plugin trailer view).
- No emoji or symbol characters in buttons and labels; search is one rounded bar, tabs are one sleek strip.
- A stream started from here keeps its poster, so Continue Watching shows a thumbnail.

## 3.4.1
- Stream Media now has its own picture (`icon.png`, set in plugin.json), shown on the Plugins page, the More page pins and the dashboard shortcut.
- Pictures no longer stay blank until you refresh: a TMDb request that fails (a slow or cold worker, a 429 / 5xx answer, a dropped connection) is tried again by itself for up to about 11 seconds before the row shows an error. Posters that could not load are asked for again by the app (see FLUTTER.md, "Pictures that heal themselves").

## 3.4.2
- Trailer is full width and covers the top half of the screen on a TV, plays with no YouTube controls, play button or icons, and scrolls away with the page instead of staying pinned over the buttons.
- Remote: the D-pad no longer gets stuck in search boxes.
- Movie and show cards are landscape on a TV and portrait on a phone.
- Episode descriptions are shown in full on a phone.

## 3.5.0
- Rate what you watch: the detail page has a "Rate this movie / show" line with buttons 1 to 10. It is your own rating in PEK TV (the same one shown on the posters and sent to Trakt); press the number you already gave to take the rating off. This needs the new "watched" permission, which is why the plugin asks for it.
