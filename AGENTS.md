# Project guidance

## Scope

- This is the public `solvit-consultoria/Meet2Notes` fork based on upstream tag `v0.6.1`. Keep the original project as the `upstream` remote; `origin` is the fork.
- Implement the local meeting MVP incrementally: separate local audio masters, optional derived mix/transcription, Portuguese UI, explicit export organization, and local read-only MCP. Treat planned behavior as work to implement, not as already present upstream.
- Finalized exports are a single Markdown file with frontmatter, summary/manual notes first, then the complete transcript grouped into speaker paragraphs with timestamps. Keep source audio in local app storage; do not copy it into the export folder by default.
- Preserve upstream architecture and MIT attribution. Avoid unrelated rewrites and native-installer work in this MVP.

## Privacy and integration boundaries

- Keep active database, in-progress recordings, and model files in local app storage. Export finalized sessions only to the explicitly selected destination (which may be OneDrive); report local-save and export/sync state separately.
- Never add recordings, transcripts, credentials, model weights, or personal meeting data to Git. Keep examples synthetic and ensure ignore rules cover local secrets and artifacts.
- Remote transcription is optional. Upload only after an explicit per-send confirmation that identifies provider, estimated duration, and files. No automatic upload or fallback. API credentials are currently unconfigured; never request them in source control or logs.
- MCP stays local `stdio` and read-only. Do not add recording, editing, or deletion tools, remote listeners, or tunnels in this MVP.

## Change coordination and validation

- The audio capture/backend and its persistence pipeline have a single owner per change set. Do not edit that capture/backend concurrently with another agent; coordinate before touching shared capture files.
- Add or update focused tests for each new behavior, including relevant failure paths. Run applicable existing checks and `git diff --check`; report checks that could not run.
- Preserve the fork's updater safety. The upstream updater explicitly accepts only the upstream repository; fork changes must not silently overwrite fork work or bypass clean-tree, backup, ancestry, and rollback protections. Disable fork-incompatible update paths or adapt them deliberately and test the guard.
- Keep `DECISIONS.md` current when changing an architectural boundary or user-approved scope.
