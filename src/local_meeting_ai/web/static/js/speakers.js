(() => {
  "use strict";
  const api = (...args) => window.Meet2Notes.api(...args);
  const t = (key, fallback) => window.Meet2Notes?.t(key) || fallback;
  const list = document.querySelector("#speaker-profile-list");
  const options = document.querySelector("#speaker-filter-options");
  const results = document.querySelector("#speaker-meeting-results");
  const dialog = document.querySelector("#speaker-profile-dialog");
  const form = document.querySelector("#speaker-profile-form");
  const consent = document.querySelector("#speaker-record-consent");
  const recordStart = document.querySelector("#speaker-record-start");
  const recordStop = document.querySelector("#speaker-record-stop");
  const recordRetake = document.querySelector("#speaker-record-retake");
  const recorderStatus = document.querySelector("#speaker-recorder-status");
  const preview = document.querySelector("#speaker-sample-preview");
  const saveButton = document.querySelector("#speaker-save-profile");
  const fileInput = form.elements.file;
  let profiles = [];
  let mediaRecorder = null;
  let mediaStream = null;
  let chunks = [];
  let sampleFile = null;
  let previewUrl = null;
  let recordingTimer = null;
  let recordingStartedAt = 0;
  let suppressStoppedSample = false;
  const voiceAudio = new Audio();
  let playingProfileId = null;
  const escape = (v) => String(v).replace(/[&<>'"]/g, (x) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" }[x]));
  const icon = (name) => ({
    play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="6" width="10" height="12" rx="1"/></svg>',
    rename: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 16-.5 4.5L8 20l11-11-4-4L4 16Z"/><path d="m13 7 4 4"/></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3"/></svg>',
  })[name];
  async function load() { profiles = await api("/api/speaker-profiles"); render(); }
  function render() {
    list.innerHTML = profiles.length ? profiles.map(p => `<article class="saved-voice"><span class="saved-voice-mark">${escape(p.name[0]?.toUpperCase() || "V")}</span><div><strong>${escape(p.name)}</strong><small>${p.meeting_count} ${p.meeting_count === 1 ? "meeting" : "meetings"} recognized</small></div><div class="saved-voice-actions"><button class="text-button" data-play-profile="${p.id}" aria-pressed="${p.id === playingProfileId}" title="${p.id === playingProfileId ? "Stop" : "Play saved voice"}">${icon(p.id === playingProfileId ? "stop" : "play")} ${p.id === playingProfileId ? "Stop" : "Play"}</button><button class="text-button" data-rename="${p.id}">${icon("rename")} Rename</button><button class="text-button danger" data-delete="${p.id}">${icon("delete")} Delete</button></div></article>`).join("") : `<div class="result-empty"><strong>No saved voices yet</strong><span>Remember a speaker from a meeting or add a voice sample.</span></div>`;
    options.innerHTML = profiles.length ? profiles.map(p => `<label><input type="checkbox" value="${p.id}"><span>${escape(p.name)}</span></label>`).join("") : `<span class="muted">Save a voice first to filter meetings.</span>`;
    results.innerHTML = `<div class="result-empty"><strong>Select speakers</strong><span>Choose one or more people above to search their meetings.</span></div>`;
  }
  document.querySelectorAll("[data-speaker-tab]").forEach(button => button.addEventListener("click", () => { document.querySelectorAll("[data-speaker-tab]").forEach(x => x.classList.toggle("active", x === button)); document.querySelectorAll("[data-speaker-panel]").forEach(x => x.hidden = x.dataset.speakerPanel !== button.dataset.speakerTab); }));
  document.querySelector("#add-speaker-profile").onclick = () => { resetRecorderForm(); dialog.showModal(); };
  document.querySelectorAll("[data-close-dialog]").forEach(button => button.addEventListener("click", () => dialog.close()));
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", stopAndReleaseRecorder);
  consent.addEventListener("change", updateSaveAvailability);
  form.elements.name.addEventListener("input", updateSaveAvailability);
  fileInput.addEventListener("change", () => { if (fileInput.files.length) { clearSample(); setStatus(t("speakers.file_selected", "Existing audio selected. It will be uploaded only when you save.")); } updateSaveAvailability(); });

  function setStatus(message, state = "ready") { recorderStatus.textContent = message; recorderStatus.dataset.state = state; }
  function updateSaveAvailability() { saveButton.disabled = !consent.checked || !form.elements.name.value.trim() || (!sampleFile && !fileInput.files.length) || Boolean(mediaRecorder?.state === "recording"); }
  function releaseStream() { if (recordingTimer) clearInterval(recordingTimer); recordingTimer = null; mediaStream?.getTracks().forEach(track => track.stop()); mediaStream = null; }
  function stopAndReleaseRecorder() { suppressStoppedSample = true; if (mediaRecorder?.state === "recording") mediaRecorder.stop(); releaseStream(); }
  function clearSample() { sampleFile = null; preview.pause(); preview.hidden = true; preview.removeAttribute("src"); if (previewUrl) URL.revokeObjectURL(previewUrl); previewUrl = null; recordRetake.hidden = true; updateSaveAvailability(); }
  function resetRecorderForm() { stopAndReleaseRecorder(); clearSample(); chunks = []; consent.checked = false; form.reset(); recordStart.disabled = false; recordStop.disabled = true; setStatus(t("speakers.recorder_ready", "Ready to record · 15–30 seconds recommended")); updateSaveAvailability(); }
  function formatSeconds(value) { return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`; }

  async function beginRecording() {
    if (!consent.checked) { setStatus(t("speakers.consent_required", "Check the consent box before recording."), "error"); return; }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { setStatus(t("speakers.record_unsupported", "Microphone recording is not supported in this browser."), "error"); return; }
    try {
      const activeCapture = await api("/api/capture/session");
      if (activeCapture) { setStatus(t("speakers.capture_active", "A meeting is being recorded. Stop it before recording a voice sample."), "error"); return; }
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"].find(type => MediaRecorder.isTypeSupported(type));
      mediaRecorder = new MediaRecorder(mediaStream, mimeType ? { mimeType } : undefined);
      chunks = [];
      suppressStoppedSample = false;
      clearSample();
      mediaRecorder.addEventListener("dataavailable", event => { if (event.data.size) chunks.push(event.data); });
      mediaRecorder.addEventListener("error", () => { setStatus(t("speakers.record_error", "Recording failed. Check the microphone permission and try again."), "error"); releaseStream(); recordStart.disabled = false; recordStop.disabled = true; });
      mediaRecorder.addEventListener("stop", async () => {
        releaseStream(); recordStart.disabled = false; recordStop.disabled = true;
        if (suppressStoppedSample || !dialog.open) { chunks = []; updateSaveAvailability(); return; }
        const elapsed = (Date.now() - recordingStartedAt) / 1000;
        if (elapsed < 5 || chunks.length === 0) { setStatus(t("speakers.sample_too_short", "Sample too short. Record at least 5 seconds of clear speech."), "error"); updateSaveAvailability(); return; }
        try {
          setStatus(t("speakers.sample_preparing", "Preparing a private WAV preview…"), "working");
          const converted = await mediaBlobToWav(new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" }));
          if (suppressStoppedSample || !dialog.open) return;
          sampleFile = converted;
          previewUrl = URL.createObjectURL(sampleFile); preview.src = previewUrl; preview.hidden = false; recordRetake.hidden = false;
          setStatus(t("speakers.sample_review", "Preview the sample. It is not saved until you click Save voice."));
        } catch (error) { sampleFile = null; setStatus(error.message || t("speakers.sample_convert_error", "Could not prepare the audio. Try another browser or upload a WAV/MP3."), "error"); }
        updateSaveAvailability();
      }, { once: true });
      recordingStartedAt = Date.now(); mediaRecorder.start(250); recordStart.disabled = true; recordStop.disabled = false;
      setStatus(t("speakers.recording_now", "Recording · 0:00 / 1:00"), "recording");
      recordingTimer = setInterval(() => { const seconds = Math.floor((Date.now() - recordingStartedAt) / 1000); setStatus(`${t("speakers.recording_now_prefix", "Recording")} · ${formatSeconds(seconds)} / 1:00`, "recording"); if (seconds >= 60 && mediaRecorder?.state === "recording") mediaRecorder.stop(); }, 250);
    } catch (error) {
      releaseStream(); recordStart.disabled = false; recordStop.disabled = true;
      const message = error?.name === "NotAllowedError" ? t("speakers.mic_denied", "Microphone permission was denied. Allow access in the browser and try again.") : error?.name === "NotFoundError" ? t("speakers.mic_missing", "No microphone was found. Connect one or upload a WAV/MP3 sample.") : error?.message || t("speakers.record_error", "Recording failed. Check the microphone permission and try again.");
      setStatus(message, "error");
    }
  }
  recordStart.addEventListener("click", beginRecording);
  recordStop.addEventListener("click", () => { if (mediaRecorder?.state === "recording") mediaRecorder.stop(); });
  recordRetake.addEventListener("click", () => { clearSample(); chunks = []; fileInput.value = ""; setStatus(t("speakers.recorder_ready", "Ready to record · 15–30 seconds recommended")); updateSaveAvailability(); });

  async function mediaBlobToWav(blob) {
    const context = new AudioContext({ sampleRate: 16000 });
    try {
      const buffer = await context.decodeAudioData(await blob.arrayBuffer());
      const input = buffer.getChannelData(0);
      const ratio = buffer.sampleRate / 16000;
      const outputLength = Math.max(1, Math.floor(input.length / ratio));
      const pcm = new DataView(new ArrayBuffer(44 + outputLength * 2));
      const writeText = (offset, value) => [...value].forEach((char, index) => pcm.setUint8(offset + index, char.charCodeAt(0)));
      writeText(0, "RIFF"); pcm.setUint32(4, 36 + outputLength * 2, true); writeText(8, "WAVE"); writeText(12, "fmt ");
      pcm.setUint32(16, 16, true); pcm.setUint16(20, 1, true); pcm.setUint16(22, 1, true); pcm.setUint32(24, 16000, true);
      pcm.setUint32(28, 32000, true); pcm.setUint16(32, 2, true); pcm.setUint16(34, 16, true); writeText(36, "data"); pcm.setUint32(40, outputLength * 2, true);
      for (let i = 0; i < outputLength; i += 1) { const sample = Math.max(-1, Math.min(1, input[Math.floor(i * ratio)])); pcm.setInt16(44 + i * 2, sample < 0 ? sample * 32768 : sample * 32767, true); }
      return new File([pcm], "voice-sample.wav", { type: "audio/wav" });
    } finally { await context.close(); }
  }

  form.onsubmit = async (event) => {
    event.preventDefault();
    if (!consent.checked) { setStatus(t("speakers.consent_required", "Check the consent box before recording."), "error"); return; }
    const audioFile = sampleFile || fileInput.files[0];
    if (!audioFile) { setStatus(t("speakers.sample_required", "Record or choose a sample before saving."), "error"); return; }
    const payload = new FormData(); payload.set("name", form.elements.name.value.trim()); payload.set("file", audioFile, audioFile.name || "voice-sample.wav");
    saveButton.disabled = true; saveButton.textContent = t("speakers.saving_voice", "Saving…");
    try { await api("/api/speaker-profiles", { method: "POST", body: payload }); dialog.close(); resetRecorderForm(); await load(); }
    catch (error) { setStatus(error.message || t("speakers.save_error", "Could not save the voice sample."), "error"); }
    finally { saveButton.textContent = t("speakers.save_voice", "Save voice"); updateSaveAvailability(); }
  };
  function syncPlaybackControls() { list.querySelectorAll("[data-play-profile]").forEach(button => { const active = Number(button.dataset.playProfile) === playingProfileId; button.setAttribute("aria-pressed", String(active)); button.title = active ? "Stop" : "Play saved voice"; button.innerHTML = `${icon(active ? "stop" : "play")} ${active ? "Stop" : "Play"}`; }); }
  function stopVoice() { voiceAudio.pause(); voiceAudio.currentTime = 0; playingProfileId = null; syncPlaybackControls(); }
  async function toggleVoice(profileId) { if (playingProfileId === profileId && !voiceAudio.paused) { stopVoice(); return; } voiceAudio.pause(); voiceAudio.src = `/api/speaker-profiles/${profileId}/audio`; playingProfileId = profileId; try { await voiceAudio.play(); syncPlaybackControls(); } catch { playingProfileId = null; syncPlaybackControls(); alert("The saved voice could not be played."); } }
  voiceAudio.addEventListener("ended", () => { playingProfileId = null; syncPlaybackControls(); });
  voiceAudio.addEventListener("error", () => { if (playingProfileId !== null) { playingProfileId = null; syncPlaybackControls(); } });
  document.addEventListener("click", async (event) => { const play = event.target.closest("[data-play-profile]"), rename = event.target.closest("[data-rename]"), del = event.target.closest("[data-delete]"); if (play) { await toggleVoice(Number(play.dataset.playProfile)); return; } if (rename) { const p = profiles.find(x => x.id === +rename.dataset.rename), name = prompt("Speaker name", p?.name); if (name?.trim()) { try { await api(`/api/speaker-profiles/${p.id}`, { method:"PATCH", body: JSON.stringify({ name }) }); await load(); } catch (e) { alert(e.message); } } return; } if (del && confirm("Delete this saved voice? Existing meetings are kept.")) { if (playingProfileId === Number(del.dataset.delete)) stopVoice(); await api(`/api/speaker-profiles/${del.dataset.delete}`, { method:"DELETE" }); await load(); } });
  options.addEventListener("change", async () => { const ids = [...options.querySelectorAll("input:checked")].map(x => x.value); if (!ids.length) return render(); const meetings = await api(`/api/speaker-profiles/meetings?${ids.map(id => `profile_ids=${id}`).join("&")}`); results.innerHTML = meetings.length ? meetings.map(m => `<a class="speaker-meeting-row" href="/?meeting=${m.id}"><strong>${escape(m.title)}</strong><span>${new Date(m.started_at || m.created_at).toLocaleString()}</span></a>`).join("") : `<div class="result-empty"><strong>No matching meetings</strong><span>No saved meeting contains every selected speaker yet.</span></div>`; });
  load().catch(e => { list.textContent = e.message; });
})();
