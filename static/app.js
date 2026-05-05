(function () {
  "use strict";

  const STORAGE_KEY = "print-task:draft";
  const UNDO_KEY = "print-task:last_batch";
  const UNDO_DURATION_MS = 30000;
  const SAVE_DEBOUNCE_MS = 200;
  const IMG_MAX_WIDTH = 384;
  const IMG_QUALITY = 0.7;

  const editor = document.getElementById("editor");
  const printBtn = document.getElementById("print-btn");
  const printLabel = document.getElementById("print-label");
  const previewPane = document.getElementById("preview");
  const toastContainer = document.getElementById("toasts");
  const cheatsheetBtn = document.getElementById("cheatsheet-btn");
  const cheatsheetModal = document.getElementById("cheatsheet-modal");
  const cheatsheetClose = document.getElementById("cheatsheet-close");
  const testBtn = document.getElementById("test-btn");
  const tabEdit = document.getElementById("tab-edit");
  const tabPreview = document.getElementById("tab-preview");

  // ---- Draft persistence ----

  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) editor.value = saved;
  } catch (e) {
    // localStorage unavailable; carry on with empty editor
  }

  let saveTimer = null;
  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try { localStorage.setItem(STORAGE_KEY, editor.value); } catch (e) {}
    }, SAVE_DEBOUNCE_MS);
  }

  // ---- Strip count ----

  function countTasks(text) {
    if (!text || !text.trim()) return 0;
    const chunks = text.split(/^\s*;;;\s*$/m).map(s => s.trim()).filter(Boolean);
    return chunks.length;
  }

  function updatePrintLabel() {
    const n = countTasks(editor.value);
    if (n === 0) {
      printLabel.textContent = "Print";
      printBtn.disabled = true;
    } else {
      printLabel.textContent = `Print ${n} strip${n === 1 ? "" : "s"}`;
      printBtn.disabled = false;
    }
  }

  editor.addEventListener("input", () => {
    scheduleSave();
    updatePrintLabel();
  });

  // ---- Manual HTMX trigger after programmatic value changes ----

  function triggerPreviewRender() {
    if (window.htmx) {
      window.htmx.trigger(editor, "input");
    } else {
      editor.dispatchEvent(new Event("input"));
    }
  }

  // ---- Print action ----

  printBtn.addEventListener("click", async () => {
    if (printBtn.disabled) return;
    const originalLabel = printLabel.textContent;
    const text = editor.value;
    const n = countTasks(text);
    if (n === 0) return;

    printBtn.disabled = true;
    printLabel.textContent = `Printing ${n} strip${n === 1 ? "" : "s"}…`;

    try {
      const formData = new FormData();
      formData.append("text", text);
      const res = await fetch("/print", { method: "POST", body: formData });
      const data = await res.json().catch(() => ({}));

      if (!res.ok || !data.ok) {
        const msg = data.error || `HTTP ${res.status}`;
        showToast("error", `Print failed: ${msg}`);
        printLabel.textContent = originalLabel;
        printBtn.disabled = false;
        return;
      }

      // Success: stash undo, clear editor, refresh preview
      try {
        localStorage.setItem(UNDO_KEY, text);
      } catch (e) {}
      editor.value = "";
      try { localStorage.setItem(STORAGE_KEY, ""); } catch (e) {}
      triggerPreviewRender();
      showRestoreToast(data.printed || n, text);
      updatePrintLabel();
      editor.focus();
    } catch (e) {
      showToast("error", `Network error: ${e.message}`);
      printLabel.textContent = originalLabel;
      printBtn.disabled = false;
    }
  });

  // ---- Test print ----

  if (testBtn) {
    testBtn.addEventListener("click", async () => {
      testBtn.disabled = true;
      try {
        const res = await fetch("/test", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.ok) showToast("success", "Test strip printed");
        else showToast("error", `Test print failed: ${data.error || res.status}`);
      } catch (e) {
        showToast("error", `Network error: ${e.message}`);
      } finally {
        testBtn.disabled = false;
      }
    });
  }

  // ---- Toasts ----

  function makeToast(kind) {
    const t = document.createElement("div");
    t.className = `toast toast-${kind}`;
    return t;
  }

  function dismissToast(t) {
    if (!t.isConnected) return;
    t.classList.add("toast-leaving");
    setTimeout(() => t.remove(), 280);
  }

  function showToast(kind, message, durationMs) {
    const t = makeToast(kind);
    t.textContent = message;
    toastContainer.appendChild(t);
    setTimeout(() => dismissToast(t), durationMs || 4000);
  }

  function showRestoreToast(printedCount, savedText) {
    const t = makeToast("success");
    const msg = document.createElement("span");
    msg.textContent = `Printed ${printedCount} strip${printedCount === 1 ? "" : "s"}`;
    const action = document.createElement("button");
    action.className = "toast-action";
    action.type = "button";
    action.textContent = "Restore last batch";
    action.addEventListener("click", () => {
      editor.value = savedText;
      try { localStorage.setItem(STORAGE_KEY, savedText); } catch (e) {}
      triggerPreviewRender();
      updatePrintLabel();
      editor.focus();
      dismissToast(t);
    });
    t.appendChild(msg);
    t.appendChild(action);
    toastContainer.appendChild(t);
    setTimeout(() => dismissToast(t), UNDO_DURATION_MS);
  }

  // ---- Keyboard ----

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      if (cheatsheetModal && cheatsheetModal.classList.contains("open")) return;
      e.preventDefault();
      if (!printBtn.disabled) printBtn.click();
    } else if (e.key === "Escape") {
      if (cheatsheetModal && cheatsheetModal.classList.contains("open")) {
        cheatsheetModal.classList.remove("open");
      }
    }
  });

  // ---- Drag-drop & paste images ----

  function insertAtCursor(textarea, text) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = textarea.value.substring(0, start);
    const after = textarea.value.substring(end);
    textarea.value = before + text + after;
    const pos = start + text.length;
    textarea.selectionStart = textarea.selectionEnd = pos;
    textarea.focus();
    textarea.dispatchEvent(new Event("input"));
  }

  async function fileToResizedDataURI(file, maxW, quality) {
    const bitmap = await createImageBitmap(file);
    const ratio = bitmap.width > maxW ? maxW / bitmap.width : 1;
    const w = Math.max(1, Math.round(bitmap.width * ratio));
    const h = Math.max(1, Math.round(bitmap.height * ratio));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(bitmap, 0, 0, w, h);
    return canvas.toDataURL("image/jpeg", quality);
  }

  async function insertImageFile(file, sourceLabel) {
    if (!file || !file.type || !file.type.startsWith("image/")) return false;
    try {
      const dataURI = await fileToResizedDataURI(file, IMG_MAX_WIDTH, IMG_QUALITY);
      const alt = (file.name || sourceLabel || "image").replace(/[\]\[]/g, "");
      insertAtCursor(editor, `\n![${alt}](${dataURI})\n`);
      return true;
    } catch (e) {
      showToast("error", `Image insert failed: ${e.message}`);
      return false;
    }
  }

  editor.addEventListener("dragover", (e) => {
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files")) {
      e.preventDefault();
      editor.classList.add("drop-active");
    }
  });
  editor.addEventListener("dragleave", () => {
    editor.classList.remove("drop-active");
  });
  editor.addEventListener("drop", async (e) => {
    editor.classList.remove("drop-active");
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
    e.preventDefault();
    for (const f of Array.from(e.dataTransfer.files)) {
      await insertImageFile(f, "dropped");
    }
  });

  editor.addEventListener("paste", async (e) => {
    if (!e.clipboardData) return;
    const items = e.clipboardData.items || [];
    for (const item of items) {
      if (item.kind === "file" && item.type && item.type.startsWith("image/")) {
        e.preventDefault();
        const file = item.getAsFile();
        if (file) await insertImageFile(file, "pasted");
        return;
      }
    }
  });

  // ---- Cheatsheet modal ----

  if (cheatsheetBtn && cheatsheetModal) {
    cheatsheetBtn.addEventListener("click", () => cheatsheetModal.classList.add("open"));
    cheatsheetModal.addEventListener("click", (e) => {
      if (e.target === cheatsheetModal) cheatsheetModal.classList.remove("open");
    });
    if (cheatsheetClose) {
      cheatsheetClose.addEventListener("click", () => cheatsheetModal.classList.remove("open"));
    }
  }

  // ---- Mobile tab toggle ----

  if (tabEdit && tabPreview) {
    function setTab(name) {
      document.body.dataset.tab = name;
      tabEdit.classList.toggle("active", name === "edit");
      tabPreview.classList.toggle("active", name === "preview");
    }
    tabEdit.addEventListener("click", () => setTab("edit"));
    tabPreview.addEventListener("click", () => setTab("preview"));
    setTab("edit");
  }

  // ---- Init ----

  updatePrintLabel();
  editor.focus();
  if (editor.value) {
    triggerPreviewRender();
  }
})();
