# MVP decisions

This file separates verified `v0.6.1` behavior from intended fork changes.

## Baseline verified in upstream `v0.6.1`

- The project is a local Python/web application with modular capture and transcription components.
- `docs/mcp.md` describes a local, read-only MCP server over `stdio`; the MCP process connects to the running app's local API.
- `M2N_DATA_DIR` and `M2N_MODELS_DIR` can relocate data and model storage independently (`README.md`, `src/local_meeting_ai/paths.py`).
- The PowerShell updater pins its accepted remote to `estebanstifli/Meet2Notes`, requires a clean working tree, backs up data, verifies a fast-forward release, and rolls back source on failure (`update.ps1`). This guard is incompatible with blindly updating this fork.

## User-approved MVP direction

- Repository: public `solvit-consultoria/Meet2Notes` fork, based on `v0.6.1`; retain the original Git remote as `upstream`.
- Capture: preserve microphone and system audio as separate local masters, synchronized; create a derived mix for the initial transcription path. A mix does not justify assigning speaker labels such as “Você” and “Outro lado”. Keep capture running through transcription/network failures.
- Storage/export: retain active database and in-progress audio locally. Export finalized Markdown, metadata, segments, integrity manifest, and both audio tracks to a user-selected parent folder, including OneDrive if selected. Show local persistence and destination synchronization as distinct states. Organize by client/project with an “A classificar” choice and stable meeting ID.
- Transcription: local is the default. A configurable OpenAI Audio-compatible endpoint is optional; API is currently left unconfigured. Each upload requires a separate user confirmation after showing provider, estimated duration, and files. Never auto-upload or silently fall back; mark missing timestamps as approximate or unavailable.
- MCP: reuse a local `stdio`, read-only surface only. No remote MCP/tunnel, write operation, or ChatGPT web/Notion AI connection in this MVP.
- UX: Portuguese local browser interface, manual start/stop, and at most a non-starting suggestion that requires an explicit click. No custom native installer in this delivery.
- Release: preserve upstream attribution and updater safety; adapt or disable fork-incompatible update flow so it cannot overwrite fork work. Publish only after acceptance checks pass.

## Validation required for new behavior

- Test audio channel synchronization, mix derivation, and continued capture/recovery after transcription or network failure.
- Test repeated export without duplicates, integrity manifest, local/export state reporting, and client/project assignment.
- Test API adapter with simulated responses, explicit confirmation boundary, absent credentials, timestamp handling, and no credential leakage in logs.
- Test MCP listing/search/transcript retrieval and verify no write-capable tools are exposed.
- Run the fork's applicable existing checks. Real Portuguese meeting trials require consent and are not implied by these repository decisions.
