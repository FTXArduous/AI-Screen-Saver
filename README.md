# USHI — Universal Spatial-Harmonic Indexing

A GitHub-ready **developer prototype** for the USHI Generative Snake concept.

This package implements a one-command cycle runner, continuous development loop, 16-candidate radix/subdivision comparison, SQLite cycle history, BLAKE3 record hashing, CSV star-catalog ingestion, and a 21:9 SVG dashboard generated after every cycle.

> **Prototype boundary:** this is a real local software prototype, not a validated astronomical system. The included scoring is explicitly heuristic. GPU/HBM use and cluster migration are adapter interfaces/simulations; no hardware is accessed unless you implement and configure an authorized backend. The sample catalog is synthetic. Do not interpret the sample scores or coordinates as scientific findings.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -e .

# Run one complete cycle (one command)
ushi run-once

# Start developer continuous mode; Ctrl+C checkpoints and stops cleanly
ushi dev --interval 30 --power minimum
```

Outputs are written to `./ushi-data/` by default:

- `ushi.sqlite3` — persistent cycle/candidate history
- `renders/cycle-XXXX.svg` — 21:9 image for every completed cycle
- `exports/cycle-XXXX.json` — machine-readable cycle report

Open the SVG in a browser or convert it to PNG with your preferred image tool.

## Commands

```bash
ushi run-once [--data path/to/stars.csv]
ushi dev [--interval 30] [--power minimum|balanced|performance]
ushi status
ushi export --cycle 1
ushi screensaver [--backend tab|app] [--interval 1|3]
```

## Prompt overlay (`ushi screensaver`)

A fullscreen, always-on-top window with a 20×20 drop-down arrow that bounces along the bottom edge. The cursor hides after 7 seconds without movement. Press `1` (or `F5`, which also works while the cursor is in the prompt box) to start automation (press again to stop). Each question is picked at random from the 16 Milky Way distance targets in `ushi\screensaver\questions.py` (planets, stars within 16 ly and 120 ly, the Galactic Center, the disk diameter, the Large Magellanic Cloud, and Andromeda). Each target has its own number base (2 through 24, all different) and its own wording, and asks for the answer to 24 digits. Only three of the 16 wordings also request a 21:9 Milky Way map image, so ChatGPT isn't asked to render an image every time. Reference distances in the set are approximate. Anything typed in the prompt box is sent first as a preamble. With the `tab` backend, ChatGPT's reply is streamed to the screensaver while it is still being written: finished text chunks and generated images appear as 4.8-second cards as soon as each one is complete, and the last chunk is held back until the reply is finished. With the `tab` and `app` backends, the reply is streamed to the screensaver while it is still being written. The status text ("ChatGPT is thinking", "rendering", and so on) bounces around the screen like a DVD logo. Behind the slides, a ray-traced glass tesseract fills the screen. It drifts around the screen with the same bounce as the status text, its shape drifts slowly and does not jump, and the amber light moves only slightly from frame to frame. The background is rendered continuously at 192×108 and played back in order at 24 fps from a rolling buffer of 48 frames, so each frame is shown once and never repeats in a loop. Frames older than the newest 48 are deleted, and frames not yet played are never deleted. Frames are stored as JPEG, not GIF, and are scaled up to the window size. Rendering speed sets the playback speed: if the renderer falls behind, the last frame is held rather than looped. Pressing `Esc` three times quickly (within 1.5 seconds) freezes or unfreezes the drop-down arrow. The loop keeps running in windowed mode too. The loop starts by itself when the screensaver opens. Pressing `1` or `F5` to stop cancels any in-flight send or read, discards queued cards, and makes the next start begin with a fresh question, so no sends are skipped. The arrow, prompt editor, and pointer stay hidden while automation runs. Press `Esc` once to switch between fullscreen and a normal window; while automation runs, the normal window also shows the arrow, editor, and pointer, and going back to fullscreen hides them again. Click the arrow to pick a backend or set the interval. Press `F11` to toggle fullscreen as well. Press `Ctrl+Q` to quit.
- `tab` (recommended for background use): starts Edge (or Chrome, from the Backend menu) by itself on chatgpt.com with its own profile in `ushi-data\tab-profile` and a debugging port, so your normal browser windows are left alone. Sign in to ChatGPT once in the window that opens; the login is kept for later runs. The browser runs with flags that stop Chromium from pausing or throttling a window the screensaver covers, and the backend marks the tab as focused during each send. It sends each question into the chatgpt.com tab, scrolls the chat to the bottom on every poll, and shows the reply as it streams in (see below), not only after it has finished. Images are saved from the page to `ushi-data\chatgpt-images` and shown as their own cards with the reply's text. Replies are detected by the newest conversation turn after the send, so a reply is found even when the page layout changes. The backend shows its status (sending, thinking, rendering, writing, finished). Image rendering is detected from the page, so a rendering image is not mistaken for thinking. If no reply appears at all within 48 seconds and ChatGPT is not working, it sends the question once more. A reply that is still rendering an image is never re-sent. A reply counts as complete only after its text has stopped changing and any generated image has loaded (waits up to 180 seconds for an image). Retry buttons such as "Try again" inside the reply are clicked automatically, and pop-ups and dialogs are dismissed. The loop starts by itself when the screensaver opens. Needs `pip install -e .[web]`.
- `app` (ChatGPT desktop app): starts the installed ChatGPT app (the Microsoft Store package `OpenAI.Codex`, found with `Get-AppxPackage`) by itself with its own profile in `ushi-data\desktop-app` and debugging port 9223. Your normal app session is not touched. Sign in once in the window that opens. It uses the same send, streaming, and image logic as `tab`. Its reply selectors come from the web page and are not yet verified against a desktop chat, so check the first reply before relying on it. Needs `pip install -e .[web]`.

Automating the ChatGPT web page or desktop app may conflict with OpenAI's terms of use. Check them before enabling those backends.

CSV input accepts columns: `id,x_ly,y_ly,z_ly` and optional `vx_kms,vy_kms,vz_kms,epoch_year`. Coordinates must share a declared frame and units. The prototype currently treats coordinates as Cartesian light-years and does not transform frames.

## Candidate matrix

The 16 candidates are bases 8, 10, 12, 16, 20, 24, 32, and 36, each with uniform and recursive subdivision. Candidate metrics separate notation from spatial partitioning. Radix changes encoding length, not physical distances. Recursive subdivision is currently a configurable conceptual strategy; a production spatial index still needs a defined cell geometry, neighbor rules, and boundary semantics.

## Architecture

- `ushi/engine/` — candidate generation, metrics, cycle orchestration
- `ushi/data/` — CSV catalog reader and synthetic demonstration catalog
- `ushi/scheduler/` — safe local scheduler interface and simulated cluster-hop planner
- `ushi/render/` — self-contained 21:9 SVG dashboard renderer
- `ushi/storage.py` — SQLite persistence and cycle history
- `ushi/cli.py` — one-command and continuous developer modes

## Production integration work still required

1. Validate astronomical records against Gaia releases and preserve source IDs, reference frames, epochs, covariance, and provenance.
2. Replace heuristic metrics with measured conversion, indexing, query, and navigation benchmarks on held-out data.
3. Implement real spatial-cell geometry and coordinate-neighbor traversal.
4. Add a GPU backend (for example, CUDA, ROCm, or portable compute) and measure actual allocations, throughput, temperature, and energy.
5. Implement cluster migration against your own authorized scheduler (Slurm, Kubernetes, or a custom agent), including checkpoint transfer and rollback.
6. Add service supervision, authentication, resource quotas, observability, and secure remote control before exposing a network endpoint.
7. Validate long-horizon stellar propagation using astrometric uncertainties and appropriate dynamical models. Hashes identify records; they do not validate their scientific truth.

## Hashing

BLAKE3 is used for canonical record digests. Each record includes its schema version and source fields. Object identity (`oid`) is kept separate from the content digest (`dmh`). The temporal projection digest (`thi`) identifies a specific projection record. Hashing is not a distance calculation or prediction method.

## License

MIT. See `LICENSE`.
