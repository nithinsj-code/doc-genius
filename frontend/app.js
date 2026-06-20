(() => {
  const API_BASE = (window.DOCGENIUS_API_BASE || "").replace(/\/$/, "");

  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");
  const apiBaseShown = document.getElementById("apiBaseShown");

  const genPrompt = document.getElementById("genPrompt");
  const genBtn = document.getElementById("genBtn");
  const genOutput = document.getElementById("genOutput");

  const dropzone = document.getElementById("dropzone");
  const pdfInput = document.getElementById("pdfInput");
  const fileStatus = document.getElementById("fileStatus");
  const askArea = document.getElementById("askArea");
  const pdfQuestion = document.getElementById("pdfQuestion");
  const askBtn = document.getElementById("askBtn");
  const pdfOutput = document.getElementById("pdfOutput");

  let sessionId = null;
  let qaHistory = [];

  apiBaseShown.textContent = API_BASE ? `· API: ${API_BASE}` : "";

  // ---------------- Health check ----------------
  async function checkHealth() {
    if (!API_BASE || API_BASE.includes("your-backend")) {
      statusDot.className = "status-dot err";
      statusText.textContent = "Backend URL not configured yet — edit config.js";
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/health`);
      if (!res.ok) throw new Error("bad status");
      const data = await res.json();
      statusDot.className = "status-dot ok";
      statusText.textContent = "Backend connected";
      if (!data.gemini_configured) {
        statusText.textContent += " (Gemini key missing on server)";
      }
    } catch (err) {
      statusDot.className = "status-dot err";
      statusText.textContent = "Could not reach backend — check it's running and ALLOWED_ORIGINS is set";
    }
  }
  checkHealth();

  // ---------------- Gemini generator ----------------
  function setOutput(el, text, { error = false, empty = false } = {}) {
    el.textContent = text;
    el.classList.toggle("error", error);
    el.classList.toggle("empty", empty);
  }

  async function handleGenerate() {
    const prompt = genPrompt.value.trim();
    if (!prompt) {
      setOutput(genOutput, "Please enter a prompt first.", { error: true });
      return;
    }
    genBtn.disabled = true;
    genBtn.innerHTML = `<span class="spinner"></span> Generating…`;
    setOutput(genOutput, "Thinking…", { empty: true });

    try {
      const res = await fetch(`${API_BASE}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      setOutput(genOutput, data.response);
    } catch (err) {
      setOutput(genOutput, `Error: ${err.message}`, { error: true });
    } finally {
      genBtn.disabled = false;
      genBtn.textContent = "Generate";
    }
  }

  genBtn.addEventListener("click", handleGenerate);
  genPrompt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleGenerate();
  });

  // ---------------- PDF upload ----------------
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("drag"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag");
    if (e.dataTransfer.files.length) {
      pdfInput.files = e.dataTransfer.files;
      handleUpload(e.dataTransfer.files[0]);
    }
  });
  pdfInput.addEventListener("change", () => {
    if (pdfInput.files.length) handleUpload(pdfInput.files[0]);
  });

  async function handleUpload(file) {
    if (file.type !== "application/pdf") {
      fileStatus.innerHTML = `<div class="output error">Please choose a PDF file.</div>`;
      return;
    }
    fileStatus.innerHTML = `<span class="file-pill"><span class="spinner"></span> Processing ${file.name}…</span>`;
    askArea.style.display = "none";
    sessionId = null;
    qaHistory = [];
    setOutput(pdfOutput, "Answers about your PDF will appear here.", { empty: true });

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/pdf/upload`, { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");

      sessionId = data.session_id;
      fileStatus.innerHTML = `<span class="file-pill">✓ ${data.filename} · ${data.num_chunks} chunks indexed</span>`;
      askArea.style.display = "block";
      pdfQuestion.focus();
    } catch (err) {
      fileStatus.innerHTML = `<div class="output error">Error: ${err.message}</div>`;
    }
  }

  async function handleAsk() {
    const question = pdfQuestion.value.trim();
    if (!question) return;
    if (!sessionId) {
      setOutput(pdfOutput, "Please upload a PDF first.", { error: true });
      return;
    }

    askBtn.disabled = true;
    askBtn.innerHTML = `<span class="spinner"></span> Asking…`;

    try {
      const res = await fetch(`${API_BASE}/api/pdf/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, question }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");

      qaHistory.push({ q: question, a: data.answer });
      renderHistory();
      pdfOutput.scrollTop = pdfOutput.scrollHeight;
      pdfQuestion.value = "";
    } catch (err) {
      setOutput(pdfOutput, `Error: ${err.message}`, { error: true });
    } finally {
      askBtn.disabled = false;
      askBtn.textContent = "Ask";
    }
  }

  function renderHistory() {
    pdfOutput.classList.remove("empty", "error");
    pdfOutput.innerHTML = qaHistory
      .map(
        (pair) => `
        <div class="qa-pair">
          <div class="qa-q">${escapeHtml(pair.q)}</div>
          <div class="qa-a">${escapeHtml(pair.a)}</div>
        </div>`
      )
      .join("");
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  askBtn.addEventListener("click", handleAsk);
  pdfQuestion.addEventListener("keydown", (e) => { if (e.key === "Enter") handleAsk(); });
})();
