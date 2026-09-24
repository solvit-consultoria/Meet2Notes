from __future__ import annotations

import json
from pathlib import Path


def test_new_transcription_has_accessible_activity_log_controls(client) -> None:
    response = client.get("/?new=1")

    assert response.status_code == 200
    assert 'id="toggle-activity-log"' in response.text
    assert 'aria-controls="activity-log-output"' in response.text
    assert 'aria-expanded="true"' in response.text
    assert 'data-i18n="activity.hide"' in response.text
    assert 'id="activity-log-resizer"' in response.text
    assert 'id="activity-performance"' in response.text
    assert 'data-i18n="performance.summary"' in response.text
    assert 'aria-live="polite"' in response.text


def test_ui_translations_use_clear_activity_log_and_search_copy() -> None:
    locale_dir = (
        Path(__file__).parents[2]
        / "src"
        / "local_meeting_ai"
        / "web"
        / "static"
        / "locales"
    )
    portuguese = json.loads((locale_dir / "pt-BR.json").read_text(encoding="utf-8"))

    assert portuguese["literal"]["Clear view"] == "Limpar registro"
    assert portuguese["literal"]["Search transcript"] == "Buscar na transcrição"
    assert (
        portuguese["literal"]["Click to rename this speaker"]
        == "Clique para renomear este falante"
    )
    assert portuguese["activity.hide"] == "Ocultar registro"
    assert portuguese["activity.show"] == "Mostrar registro"
    assert portuguese["settings.available"] == "Disponível"
    assert portuguese["settings.port_restart"].startswith("Endereço atual:")
    assert portuguese["capture.system_suffix"] == "áudio do sistema"


def test_capture_workspace_remembers_sources_and_exposes_background_progress(client) -> None:
    response = client.get("/?new=1")

    assert response.status_code == 200
    assert 'id="postprocess-open"' in response.text
    assert 'id="postprocess-diarization-unavailable"' in response.text
    assert 'id="postprocess-summary-unavailable"' in response.text
    script = (
        Path(__file__).parents[2]
        / "src"
        / "local_meeting_ai"
        / "web"
        / "static"
        / "js"
        / "transcript.js"
    ).read_text(encoding="utf-8")
    assert 'meet2notes.capture-preferences.v1' in script
    assert "diarization.available && diarization.installed" in script
    assert "summary.available && summary.installed" in script
    assert "minimizePostprocessWorkflow();" in script
    styles = (
        Path(__file__).parents[2]
        / "src"
        / "local_meeting_ai"
        / "web"
        / "static"
        / "css"
        / "transcription.css"
    ).read_text(encoding="utf-8")
    assert ".minimal-transcript-page.capture-active .timestamp-button" in styles


def test_capture_polish_translations_cover_preflight_notices() -> None:
    locale_dir = (
        Path(__file__).parents[2]
        / "src"
        / "local_meeting_ai"
        / "web"
        / "static"
        / "locales"
    )
    portuguese = json.loads((locale_dir / "pt-BR.json").read_text(encoding="utf-8"))
    spanish = json.loads((locale_dir / "es.json").read_text(encoding="utf-8"))

    assert "indisponível" in portuguese["postprocess.diarization_unavailable"]
    assert portuguese["postprocess.settings_link"] == "Configurações"
    assert "no está disponible" in spanish["postprocess.diarization_unavailable"]


def test_audio_source_check_uses_a_short_cancellable_probe_without_recording(client) -> None:
    response = client.get("/?new=1")
    assert response.status_code == 200

    root = Path(__file__).parents[2]
    script = (root / "src/local_meeting_ai/web/static/js/transcript.js").read_text(encoding="utf-8")
    styles = (root / "src/local_meeting_ai/web/static/css/transcription.css").read_text(
        encoding="utf-8"
    )
    assert "data-test-source=" in script
    assert '`/api/audio/sources/${encodeURIComponent(sourceId)}/level`' in script
    assert "new AbortController()" in script
    assert "current.controller.abort()" in script
    assert (
        'if (captureSession || document.querySelector("#transcription-form").dataset.busy)'
        in script
    )
    assert "performance.now() - state.startedAt >= 3000" in script
    assert ".source-test-button:focus-visible" in styles
    assert 'data-source-status="${escapeHTML(source.id)}" aria-live="polite"' in script

    locale_dir = root / "src/local_meeting_ai/web/static/locales"
    for locale_name in ("en.json", "pt-BR.json", "es.json"):
        locale = json.loads((locale_dir / locale_name).read_text(encoding="utf-8"))
        assert locale["capture.test_audio"]
        assert locale["capture.test_no_signal"]
        assert locale["capture.test_low"]
        assert locale["capture.test_clear"]


def test_optional_performance_panel_only_polls_while_visible(client) -> None:
    response = client.get("/?new=1")
    assert response.status_code == 200

    root = Path(__file__).parents[2]
    script = (root / "src/local_meeting_ai/web/static/js/transcript.js").read_text(encoding="utf-8")
    styles = (root / "src/local_meeting_ai/web/static/css/transcription.css").read_text(
        encoding="utf-8"
    )
    assert 'api("/api/system/performance")' in script
    assert "performancePanel.open && !document.hidden" in script
    assert "window.setTimeout(pollPerformanceMetrics, 5000)" in script
    assert 'document.addEventListener("visibilitychange", syncPerformancePolling)' in script
    assert 'performancePanel.open = false' in script
    assert 't("performance.unavailable")' in script
    assert 'resumePreview: false' in script
    assert "sourcePreviewSuppressed = true" in script
    assert ".activity-performance-popover" in styles

    locale_dir = root / "src/local_meeting_ai/web/static/locales"
    for locale_name in ("en.json", "pt-BR.json", "es.json"):
        locale = json.loads((locale_dir / locale_name).read_text(encoding="utf-8"))
        for key in (
            "performance.summary",
            "performance.title",
            "performance.system_memory",
            "performance.system_value",
            "performance.process_memory",
            "performance.updated",
            "performance.unavailable",
        ):
            assert locale[key]
