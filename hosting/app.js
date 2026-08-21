const limits = {
  fileBytes: 10 * 1024 * 1024,
  batchBytes: 25 * 1024 * 1024,
  batchCount: 5,
};

const allowedTypes = new Set(["image/jpeg", "image/png", "image/gif"]);
const state = { mode: "single", files: [], busy: false };

const elements = {
  input: document.querySelector("#file-input"),
  dropZone: document.querySelector("#drop-zone"),
  dropHelp: document.querySelector("#drop-help"),
  fileList: document.querySelector("#file-list"),
  error: document.querySelector("#form-error"),
  button: document.querySelector("#extract-button"),
  normalize: document.querySelector("#normalize"),
  metadata: document.querySelector("#metadata"),
  resultsSection: document.querySelector("#results-section"),
  results: document.querySelector("#results"),
  summary: document.querySelector("#result-summary"),
};

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.hidden = !message;
}

function validateFiles(files) {
  const maxCount = state.mode === "batch" ? limits.batchCount : 1;
  if (files.length > maxCount) {
    return state.mode === "batch"
      ? `Choose no more than ${limits.batchCount} images per batch.`
      : "Choose one image in single mode.";
  }
  const invalidType = files.find((file) => !allowedTypes.has(file.type));
  if (invalidType) return `${invalidType.name} is not a JPEG, PNG, or GIF image.`;
  const oversized = files.find((file) => file.size > limits.fileBytes);
  if (oversized) return `${oversized.name} exceeds the 10 MiB limit.`;
  const total = files.reduce((sum, file) => sum + file.size, 0);
  if (total > limits.batchBytes) return "The selected images exceed the 25 MiB batch limit.";
  return "";
}

function setFiles(fileList) {
  const incoming = Array.from(fileList);
  const files = state.mode === "batch" ? [...state.files, ...incoming] : incoming.slice(0, 1);
  const error = validateFiles(files);
  if (error) {
    showError(error);
    return;
  }
  showError("");
  state.files = files;
  renderFiles();
}

function renderFiles() {
  elements.fileList.replaceChildren();
  state.files.forEach((file, index) => {
    const row = document.createElement("div");
    row.className = "file-row";

    const image = document.createElement("img");
    image.className = "file-thumb";
    image.alt = "";
    const objectUrl = URL.createObjectURL(file);
    image.src = objectUrl;
    image.addEventListener("load", () => URL.revokeObjectURL(objectUrl), { once: true });

    const info = document.createElement("div");
    info.className = "file-info";
    const name = document.createElement("strong");
    name.textContent = file.name;
    const size = document.createElement("small");
    size.textContent = `${formatBytes(file.size)} · ${file.type.replace("image/", "").toUpperCase()}`;
    info.append(name, size);

    const remove = document.createElement("button");
    remove.className = "remove-file";
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${file.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      state.files.splice(index, 1);
      renderFiles();
    });

    row.append(image, info, remove);
    elements.fileList.append(row);
  });
  elements.button.disabled = state.files.length === 0 || state.busy;
}

function selectMode(mode) {
  state.mode = mode;
  state.files = [];
  elements.input.value = "";
  elements.input.multiple = mode === "batch";
  elements.dropHelp.textContent =
    mode === "batch"
      ? "JPEG, PNG, or GIF · Up to 5 images · 25 MiB combined"
      : "JPEG, PNG, or GIF · Maximum 10 MiB";
  document.querySelectorAll(".mode").forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  showError("");
  renderFiles();
}

function buildResultCard(result, file, index) {
  const card = document.createElement("article");
  card.className = `result-card${result.success ? "" : " error"}`;

  const head = document.createElement("div");
  head.className = "result-card-head";
  const filename = document.createElement("span");
  filename.className = "result-file";
  filename.textContent = file?.name || `Image ${index + 1}`;
  const metrics = document.createElement("div");
  metrics.className = "metrics";
  if (result.success) {
    const confidence = document.createElement("span");
    confidence.textContent = `${Math.round(result.confidence * 100)}% confidence`;
    metrics.append(confidence);
  }
  const time = document.createElement("span");
  time.textContent = `${result.processing_time_ms} ms`;
  metrics.append(time);
  head.append(filename, metrics);

  const body = document.createElement("div");
  body.className = "result-body";
  if (result.success) {
    const text = result.normalized_text ?? result.text;
    const output = document.createElement("pre");
    output.className = "result-text";
    output.textContent = text || "No text found in this image.";
    const copy = document.createElement("button");
    copy.className = "copy-button";
    copy.type = "button";
    copy.textContent = "Copy";
    copy.addEventListener("click", async () => {
      await navigator.clipboard.writeText(text);
      copy.textContent = "Copied";
      window.setTimeout(() => { copy.textContent = "Copy"; }, 1500);
    });
    body.append(output, copy);
    if (result.metadata) {
      const metadata = document.createElement("div");
      metadata.className = "metadata-list";
      const values = [
        `${result.metadata.width} × ${result.metadata.height}`,
        result.metadata.format,
        result.metadata.color_mode,
        formatBytes(result.metadata.byte_size),
      ];
      values.forEach((value) => {
        const item = document.createElement("span");
        item.textContent = value;
        metadata.append(item);
      });
      body.append(metadata);
    }
  } else {
    const error = document.createElement("p");
    error.className = "error-message";
    error.textContent = result.error?.message || "This image could not be processed.";
    body.append(error);
  }

  card.append(head, body);
  return card;
}

function renderResults(payload) {
  const results = state.mode === "batch" ? payload.results : [payload];
  elements.results.replaceChildren();
  results.forEach((result, index) => {
    elements.results.append(buildResultCard(result, state.files[index], index));
  });
  const successes = results.filter((result) => result.success).length;
  elements.summary.textContent = `${successes}/${results.length} successful · ${payload.processing_time_ms} ms total`;
  elements.resultsSection.hidden = false;
  elements.resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function extractText() {
  if (!state.files.length || state.busy) return;
  state.busy = true;
  showError("");
  elements.button.disabled = true;
  elements.button.classList.add("loading");
  elements.button.querySelector(".button-label").textContent = "Processing";

  const form = new FormData();
  const field = state.mode === "batch" ? "images" : "image";
  state.files.forEach((file) => form.append(field, file));
  const query = new URLSearchParams({
    metadata: String(elements.metadata.checked),
    normalize: String(elements.normalize.checked),
  });
  const path = state.mode === "batch" ? "/extract-text/batch" : "/extract-text";

  try {
    const response = await fetch(`${path}?${query}`, { method: "POST", body: form });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(payload?.error?.message || `Request failed with status ${response.status}.`);
    }
    renderResults(payload);
  } catch (error) {
    showError(error instanceof Error ? error.message : "The API could not be reached.");
  } finally {
    state.busy = false;
    elements.button.disabled = state.files.length === 0;
    elements.button.classList.remove("loading");
    elements.button.querySelector(".button-label").textContent = "Extract text";
  }
}

document.querySelectorAll(".mode").forEach((button) => {
  button.addEventListener("click", () => selectMode(button.dataset.mode));
});
elements.input.addEventListener("change", () => setFiles(elements.input.files));
elements.button.addEventListener("click", extractText);

["dragenter", "dragover"].forEach((eventName) => {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.add("dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.remove("dragging");
  });
});
elements.dropZone.addEventListener("drop", (event) => setFiles(event.dataTransfer.files));

selectMode("single");
