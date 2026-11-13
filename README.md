# Stream Media

A third-party Hesper plugin with a streaming-app layout: **Home / Movies / TV Shows** tabs, a featured title,
rows (trending, top rated, coming soon, genres), **Categories**, streaming-service filters, ratings on every
poster, trailers, cast, director/creator, networks, and **Play**.

## 3.9.0

- **Up next, Continue watching and Resume keep your quality.** The quality you last tapped in the version list (High, Medium or Low) is remembered. When PEK starts a stream by itself it looks for that quality first. If there is none of it, it takes the next one up (Low goes to Medium, then High). If nothing higher exists either, it falls back to the nearest lower one. Streams flagged too heavy for the device are still skipped, and before you have ever chosen, the best match starts as before.
