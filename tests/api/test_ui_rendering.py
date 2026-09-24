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
    assert portuguese["literal"]["Click to rename this speaker"] == "Clique para renomear este falante"
    assert portuguese["activity.hide"] == "Ocultar registro"
    assert portuguese["activity.show"] == "Mostrar registro"
    assert portuguese["settings.available"] == "Disponível"
    assert portuguese["settings.port_restart"].startswith("Endereço atual:")
    assert portuguese["capture.system_suffix"] == "áudio do sistema"
