# MVP decisions

This file separates verified `v0.6.1` behavior from intended fork changes.

## Baseline verified in upstream `v0.6.1`

- The project is a local Python/web application with modular capture and transcription components.
- `docs/mcp.md` describes a local, read-only MCP server over `stdio`; the MCP process connects to the running app's local API.
- `M2N_DATA_DIR` and `M2N_MODELS_DIR` can relocate data and model storage independently (`README.md`, `src/local_meeting_ai/paths.py`).
- The PowerShell updater pins its accepted remote to `estebanstifli/Meet2Notes`, requires a clean working tree, backs up data, verifies a fast-forward release, and rolls back source on failure (`update.ps1`). This guard is incompatible with blindly updating this fork.

## User-approved MVP direction

- Repository: public `solvit-consultoria/Meet2Notes` fork, based on `v0.6.1`; retain the original Git remote as `upstream`.
- Capture: preserve microphone and system audio as separate local masters, synchronized; create a derived mix for transcription. Real-time transcription is an explicit per-session opt-in and defaults off to reduce inference load and improve the final transcript path. In offline mode, drain transient capture frames without ASR or an in-memory audio buffer; run final transcription after stop. A mix does not justify assigning speaker labels such as “Você” and “Outro lado”. Keep capture running through transcription/network failures.
- Memory: new Faster Whisper installations do not preload models or keep them resident after a job. Existing saved settings are preserved; the two controls remain independently configurable in Settings.
- Storage/export: retain active database, source audio, and in-progress sessions in local app storage. Export one Markdown file to a user-selected folder, including OneDrive if selected. Put meeting metadata in frontmatter, then summary and manual notes, followed by the complete transcript grouped into paragraphs with speaker and timestamp. Keep audio masters local for reprocessing; do not copy them or per-segment JSON into the export folder by default. Show local persistence and destination synchronization as distinct states. Organize by client/project with an “A classificar” choice and stable meeting ID.
- Transcription: local is the default. A configurable OpenAI Audio-compatible endpoint is optional; API is currently left unconfigured. Each upload requires a separate user confirmation after showing provider, estimated duration, and files. Never auto-upload or silently fall back; mark missing timestamps as approximate or unavailable.
- MCP: reuse a local `stdio`, read-only surface only. No remote MCP/tunnel, write operation, or ChatGPT web/Notion AI connection in this MVP.
- UX: Portuguese local browser interface, manual start/stop, and at most a non-starting suggestion that requires an explicit click. No custom native installer in this delivery.
- UX performance: open completed meetings on the summary tab. Fetch the full transcript only when its tab is requested; display a lightweight speaker-attributed paragraph view with search and incremental loading, without per-segment audio players/edit controls or a speaker-turn audio list.
- Speaker attribution: default to automatic speaker-count estimation and acoustic voice clustering; allow a known count when the user supplies it. Keep unknown segments explicitly unassigned and offer a retry. Map a cluster to a real name only through a saved voice profile or a user edit; transcript wording can be shown as a suggestion but must not silently establish identity.
- Default AI summary: use concise headings for summary, key points, confirmed decisions, agreed actions, and open items. Match the transcript language (Brazilian Portuguese for Portuguese meetings); omit unsupported sections, distinguish suggestions from decisions, and never infer owners or deadlines.
- Release: preserve upstream attribution and updater safety; adapt or disable fork-incompatible update flow so it cannot overwrite fork work. Publish only after acceptance checks pass.

## Product identity and local installation

- Product name: **Meeting by Solvit**. Keep the repository, Python package, data paths, and upstream attribution named Meet2Notes until a separate migration is justified.
- Visual identity follows the Solvit site: wine `#63312d`, burnt orange `#c96022`, warm ivory `#faf5ef`, Spectral headings and Inter controls. Fonts are bundled for offline use under the OFL.
- The Windows `install.ps1 -Mvp` profile installs capture, Faster Whisper, FFmpeg, FFprobe, and downloads/verifies the selected Faster Whisper model (`small` by default). `-SkipModels` and `-SkipFfmpeg` are explicit development/offline opt-outs and readiness remains incomplete.
- On this workstation, the active database, meeting storage, and Whisper model were moved to Windows local app storage outside OneDrive because the checkout lives under OneDrive. Windows may display the app package's `LocalCache` path for these folders. The export destination remains unset until the user chooses its parent folder.
- A Start Menu shortcut opens Chrome in app mode through `launch.ps1` and starts the local Python server when needed. This offers a taskbar window without packaging a native executable. Capture belongs to the server process, so closing the window does not intentionally stop an active session. Chrome app mode and the Start Menu shortcut do not provide automatic startup at Windows login or a tray icon.
- The first-run banner asks for language and export destination; available microphone and system inputs are both preselected in the start dialog. Recording still requires a click. Google Meet detection and an extension are not implemented.
- Manual meeting notes use the existing meeting description field, are saved through the local API, and render above the transcript in exported Markdown. This does not generate an AI summary.
- The local Faster Whisper adapter checks the CUDA math runtime on Windows before selecting a GPU automatically. On this workstation `cublas64_12.dll` was absent, so the application is configured for CPU, `small`, `int8`, and Portuguese. A missing CUDA runtime must not leave the live capture in a stopping state.
- The app uses the existing Solvit site logo as its visible mark and favicon. The asset is copied into the fork for offline rendering; retain Solvit ownership and do not present it as an upstream Meet2Notes asset.
- The optional Windows tray helper is PowerShell/Windows Forms, not a native installer. Its Startup shortcut launches the local server at sign-in without recording or opening a browser; double click opens the app window. The tray menu can request a graceful server shutdown, and the Startup shortcut can be removed separately.
- The lean MVP installation requires both FFmpeg and FFprobe. The installer checks both after WinGet and discovers the app executables in WinGet Links/Packages even when a long-lived shell has a stale PATH.

## Validation required for new behavior

- Test audio channel synchronization, mix derivation, and continued capture/recovery after transcription or network failure.
- Test repeatable single-Markdown export, summary-first order, speaker-paragraph grouping, timestamps, local-audio preservation, and client/project assignment.
- Test API adapter with simulated responses, explicit confirmation boundary, absent credentials, timestamp handling, and no credential leakage in logs.
- Test MCP listing/search/transcript retrieval and verify no write-capable tools are exposed.
- Run the fork's applicable existing checks. Real Portuguese meeting trials require consent and are not implied by these repository decisions.
