(() => {
  "use strict";

  const { api, toast } = window.Meet2Notes;
  const $ = (selector) => document.querySelector(selector);
  const exportRoot = $("#mvp-export-root");
  const exportStatus = $("#mvp-export-status");
  const apiStatus = $("#mvp-api-status");

  if (!exportRoot) return;

  async function load() {
    try {
      const settings = await api("/api/mvp/settings");
      exportRoot.value = settings.export_root || "";
      $("#mvp-audio-api-url").value = settings.audio_api_base_url || "";
      $("#mvp-audio-api-model").value = settings.audio_api_model || "";
      apiStatus.textContent = settings.api_key_configured
        ? "Chave guardada no Windows"
        : "Chave não configurada";
      exportStatus.textContent = settings.export_root
        ? "Pasta configurada para exportar um Markdown por reunião. A sincronização do OneDrive não é verificada pelo aplicativo."
        : "Escolha onde salvar o Markdown de cada reunião finalizada.";
    } catch (error) {
      exportStatus.textContent = error.message;
    }
  }

  $("#mvp-save-export-root")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const settings = await api("/api/mvp/settings", {
        method: "PUT",
        body: JSON.stringify({ export_root: exportRoot.value.trim() }),
      });
      exportRoot.value = settings.export_root;
      exportStatus.textContent = "Pasta configurada para salvar um Markdown por reunião. O áudio original permanece no armazenamento local do aplicativo.";
      toast("Pasta de exportação salva.");
    } catch (error) {
      exportStatus.textContent = error.message;
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("#mvp-save-api-settings")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const settings = await api("/api/mvp/settings", {
        method: "PUT",
        body: JSON.stringify({
          audio_api_base_url: $("#mvp-audio-api-url").value.trim(),
          audio_api_model: $("#mvp-audio-api-model").value.trim(),
        }),
      });
      apiStatus.textContent = settings.api_key_configured
        ? "Provedor salvo · chave guardada no Windows"
        : "Provedor salvo · chave não configurada";
      toast("Provedor de transcrição salvo. Nenhum áudio foi enviado.");
    } catch (error) {
      apiStatus.textContent = error.message;
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("#mvp-save-api-key")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const input = $("#mvp-audio-api-key");
    if (!input.value) {
      toast("Informe a chave manualmente antes de guardar.", "error");
      return;
    }
    button.disabled = true;
    try {
      await api("/api/mvp/api-key", {
        method: "PUT",
        body: JSON.stringify({ api_key: input.value }),
      });
      input.value = "";
      apiStatus.textContent = "Chave guardada no Windows";
      toast("Chave protegida pelo Gerenciador de Credenciais do Windows.");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("#mvp-remove-api-key")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await api("/api/mvp/api-key", { method: "DELETE" });
      apiStatus.textContent = "Chave removida";
      toast("Chave da API removida do Windows.");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  [exportRoot, $("#mvp-audio-api-url"), $("#mvp-audio-api-model")].forEach((input) => {
    input?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });
  });
  load();
})();
