(() => {
  "use strict";

  const {
    api,
    escapeHTML,
    formatBytes,
    formatDate,
    formatDuration,
    renderJobCard,
    subscribeJobs,
    toast,
  } = window.Meet2Notes;

  const page = document.querySelector(".meeting-page");
  const meetingId = page.dataset.meetingId;
  let meeting = null;

  async function loadMeeting() {
    try {
      const [meetingData, recordings, jobs] = await Promise.all([
        api(`/api/meetings/${meetingId}`),
      api(`/api/meetings/${meetingId}/recordings`),
      api(`/api/jobs?meeting_id=${meetingId}`),
      ]);
      meeting = meetingData;
      renderMeeting(meeting);
      renderRecordings(recordings);
      renderJobs(jobs);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function renderMeeting(item) {
    document.querySelector("#meeting-title-display").textContent = item.title;
    document.querySelector("#meeting-description-display").textContent = item.description || "Sem descrição.";
    document.querySelector("#meeting-date").textContent = formatDate(item.created_at);
    document.querySelector("#detail-created").textContent = formatDate(item.created_at);
    document.querySelector("#detail-duration").textContent = formatDuration(item.duration_ms);
    document.querySelector("#detail-status").textContent = item.status;
    document.querySelector("#meeting-client-name").textContent = item.client_name || "A classificar";
    document.querySelector("#meeting-project-name").textContent = item.project_name || "A classificar";
    const badge = document.querySelector(".meeting-kicker .status-badge");
    badge.className = `status-badge status-${item.status}`;
    badge.textContent = item.status;
    document.title = `${item.title} · Meet2Notes`;
  }

  function renderRecordings(items) {
    const container = document.querySelector("#recording-list");
    if (!items.length) {
      container.innerHTML = `
        <div class="recording-empty">
          <span class="recording-icon">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7 9m5-5 5 5M5 14v5h14v-5"/></svg>
          </span>
          <div><strong>Nenhuma gravação anexada</strong><p>Adicione um áudio ou vídeo quando quiser.</p></div>
          <button class="button secondary" data-recording-import>Adicionar mídia</button>
        </div>`;
      container.querySelector("[data-recording-import]")?.addEventListener("click", () =>
        document.querySelector("[data-open-import]")?.click());
      return;
    }
    container.innerHTML = items.map((recording) => {
      const hasVideo = Boolean(recording.metadata?.has_video);
      const stream = (recording.metadata?.streams || []).find((item) => item.codec_type === "audio");
      return `
        <div class="recording-item">
          <span class="recording-icon ${hasVideo ? "video" : ""}">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              ${hasVideo
                ? '<rect x="3" y="5" width="14" height="14" rx="2"/><path d="m17 10 4-2v8l-4-2"/>'
                : '<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"/><path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8"/>'}
            </svg>
          </span>
          <div class="recording-name">
            <strong title="${escapeHTML(recording.original_filename)}">${escapeHTML(recording.original_filename || "Recording")}</strong>
            <span>${hasVideo ? "Vídeo de origem" : "Áudio de origem"} · original preservado</span>
          </div>
          <div class="recording-stat"><strong>${formatDuration(recording.duration_ms)}</strong><span>Duração</span></div>
          <div class="recording-stat"><strong>${formatBytes(recording.size_bytes)}</strong><span>Tamanho</span></div>
          <div class="recording-stat"><strong>${escapeHTML(stream?.codec_name?.toUpperCase() || "Pendente")}</strong><span>Codec</span></div>
        </div>`;
    }).join("");
  }

  function renderJobs(items) {
    document.querySelector("#meeting-job-list").innerHTML =
      items.slice(0, 6).map((job) => renderJobCard(job)).join("");
  }

  const editDialog = document.querySelector("#edit-dialog");
  document.querySelector("#edit-meeting")?.addEventListener("click", () => {
    document.querySelector("#edit-title").value = meeting.title;
    document.querySelector("#edit-description").value = meeting.description || "";
    document.querySelector("#edit-client-name").value = meeting.client_name || "A classificar";
    document.querySelector("#edit-project-name").value = meeting.project_name || "A classificar";
    editDialog.showModal();
  });
  document.querySelectorAll("[data-close-edit]").forEach((button) =>
    button.addEventListener("click", () => editDialog.close()));
  document.querySelector("#edit-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = event.submitter;
    submit.disabled = true;
    try {
      meeting = await api(`/api/meetings/${meetingId}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: document.querySelector("#edit-title").value.trim(),
          description: document.querySelector("#edit-description").value.trim() || null,
          client_name: document.querySelector("#edit-client-name").value.trim() || "A classificar",
          project_name: document.querySelector("#edit-project-name").value.trim() || "A classificar",
        }),
      });
      renderMeeting(meeting);
      editDialog.close();
      toast("Detalhes da reunião salvos.");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      submit.disabled = false;
    }
  });

  const exportStatus = document.querySelector("#mvp-meeting-export-status");
  document.querySelector("#mvp-export-meeting")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    exportStatus.hidden = false;
    exportStatus.textContent = "Exportando Markdown, metadados, segmentos e áudios…";
    try {
      const result = await api(`/api/mvp/meetings/${meetingId}/export`, {
        method: "POST",
        body: JSON.stringify({
          client_name: meeting.client_name || "A classificar",
          project_name: meeting.project_name || "A classificar",
        }),
      });
      exportStatus.textContent = `Cópia local concluída: ${result.path}. Sincronização do OneDrive: não verificada.`;
      toast("Reunião exportada.");
    } catch (error) {
      exportStatus.textContent = error.message;
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector("#mvp-transcribe-api")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const [provider, recordings] = await Promise.all([
        api("/api/mvp/settings"),
        api(`/api/meetings/${meetingId}/recordings`),
      ]);
      const audio = [...recordings].reverse().find((item) => item.role === "original");
      if (!provider.api_key_configured || !provider.audio_api_base_url || !provider.audio_api_model || !audio) {
        throw new Error("Configure o provedor, a chave e o áudio em Configurações antes de enviar.");
      }
      const durationMs = meeting.duration_ms || audio.duration_ms || 0;
      const minutes = Math.max(1, Math.round(durationMs / 60000));
      const details = [
        "O áudio será enviado ao provedor de transcrição configurado.",
        `Provedor: ${provider.audio_api_base_url}`,
        `Modelo: ${provider.audio_api_model}`,
        `Duração estimada: ${minutes} minuto(s)`,
        `Arquivo enviado: ${audio.original_filename || "gravação original"}`,
        "Os masters permanecem locais. A API receberá o mix usado na transcrição.",
        "Confirmar o envio?",
      ].join("\n");
      if (!window.confirm(details)) return;
      toast("Enviando áudio para transcrição. A gravação local está preservada.");
      const transcription = await api(`/api/mvp/meetings/${meetingId}/transcribe-api`, {
        method: "POST",
        body: JSON.stringify({ confirm_upload: true }),
      });
      toast("Transcrição recebida e salva localmente.");
      window.location.href = `/meetings/${meetingId}/transcript?transcription=${transcription.id}`;
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  const deleteDialog = document.querySelector("#delete-dialog");
  const confirmation = document.querySelector("#delete-confirmation");
  const confirmButton = document.querySelector("#delete-confirm-button");
  document.querySelector("#delete-meeting")?.addEventListener("click", () => {
    confirmation.value = "";
    confirmButton.disabled = true;
    deleteDialog.showModal();
  });
  document.querySelectorAll("[data-close-delete]").forEach((button) =>
    button.addEventListener("click", () => deleteDialog.close()));
  confirmation.addEventListener("input", () => {
    confirmButton.disabled = confirmation.value !== "EXCLUIR";
  });
  document.querySelector("#delete-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (confirmation.value !== "EXCLUIR") return;
    confirmButton.disabled = true;
    try {
      await api(`/api/meetings/${meetingId}`, { method: "DELETE" });
      window.location.href = "/";
    } catch (error) {
      toast(error.message, "error");
      confirmButton.disabled = false;
    }
  });

  subscribeJobs((jobs) => {
    const related = jobs.filter((job) => String(job.meeting_id) === String(meetingId));
    renderJobs(related);
    if (related.some((job) => ["completed", "failed", "cancelled"].includes(job.status))) {
      Promise.all([
        api(`/api/meetings/${meetingId}`),
        api(`/api/meetings/${meetingId}/recordings`),
      ]).then(([meetingData, recordings]) => {
        meeting = meetingData;
        renderMeeting(meeting);
        renderRecordings(recordings);
      }).catch(() => {});
    }
  });

  loadMeeting();
})();
