(function () {
  // Prevent duplicate execution
  if (window.__HUB_TOOLBAR_INITIALIZED__) return;
  window.__HUB_TOOLBAR_INITIALIZED__ = true;

  // Poll for document body readiness
  const initInterval = setInterval(() => {
    if (document.body) {
      clearInterval(initInterval);
      initHubToolbar();
    }
  }, 100);

  let sessionData = {
    email: "Loading...",
    username: "",
    branch: "main",
    parent_hub_url: "/",
  };

  async function initHubToolbar() {
    injectStyles();
    createToastContainer();
    const toolbar = renderToolbar();
    document.body.appendChild(toolbar);

    // Fetch session details from Starlette /hub/session-info
    try {
      const res = await fetch("/hub/session-info");
      if (res.ok) {
        sessionData = await res.json();
        updateToolbarInfo();
      }
    } catch (err) {
      console.warn("[Hub Toolbar] Failed to fetch session info:", err);
      document.getElementById("hub-user-pill-text").innerText = "Offline Session";
    }
  }

    function getHubHeaders() {
      const token =
        document.querySelector('meta[name="marimo-server-token"]')?.getAttribute('content') ||
        document.querySelector('marimo-server-token')?.getAttribute('data-token') ||
        '';

      const headers = {
        'Content-Type': 'application/json'
      };

      if (token) {
        headers['Marimo-Server-Token'] = token;
      }

      return headers;
    }

  // --- UI Injection ---

  function renderToolbar() {
    const bar = document.createElement("aside");
    bar.id = "hub-toolbar-root";
    bar.setAttribute("aria-label", "Insights Hub Controls");

    bar.innerHTML = `
      <!-- User / Branch Info Pill -->
      <div class="hub-pill" id="hub-user-pill" title="Active Branch: Loading...">
        <span class="hub-indicator"></span>
        <span class="hub-user-text" id="hub-user-pill-text">Connecting...</span>
      </div>

      <!-- Action Buttons -->
      <div class="hub-actions">
        <button id="hub-btn-commit" class="hub-btn hub-btn--secondary" title="Stage and commit changes">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><line x1="1.05" y1="12" x2="7" y2="12"/><line x1="17.01" y1="12" x2="22.96" y2="12"/></svg>
          Commit
        </button>

        <button id="hub-btn-publish" class="hub-btn hub-btn--primary" title="Push branch, create PR, and merge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>
          Publish (PR)
        </button>

        <button id="hub-btn-finish" class="hub-btn hub-btn--danger" title="Save and terminate notebook container">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
          Finish
        </button>
      </div>
    `;

    // Attach listeners
    bar.querySelector("#hub-btn-commit").onclick = handleCommitClick;
    bar.querySelector("#hub-btn-publish").onclick = handlePublishClick;
    bar.querySelector("#hub-btn-finish").onclick = handleFinishClick;

    return bar;
  }

  function updateToolbarInfo() {
    const textEl = document.getElementById("hub-user-pill-text");
    const pill = document.getElementById("hub-user-pill");
    const displayIdentity = sessionData.email || sessionData.username || "Authenticated";

    textEl.innerText = displayIdentity;
    pill.title = `User: ${displayIdentity}\nBranch: ${sessionData.branch || "main"}\nNotebook: ${sessionData.notebook || ""}`;
  }

  // --- Action Handlers ---

  async function handleCommitClick() {
    const commitMsg = await showPromptModal({
      title: "Commit Notebook Changes",
      placeholder: "e.g., Update data cleaning pipeline and charts",
      actionText: "Commit",
    });

    if (!commitMsg) return;

    const btn = document.getElementById("hub-btn-commit");
    setButtonLoading(btn, true, "Committing...");

    try {
      const res = await fetch("/hub/commit", {
        method: "POST",
        headers: getHubHeaders(),
        body: JSON.stringify({ message: commitMsg }),
      });
      const data = await res.json();

      if (!res.ok) throw new Error(data.detail || "Failed to commit changes");

      showToast(`Committed [${data.commit_hex}]: ${data.message}`, "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setButtonLoading(btn, false, "Commit");
    }
  }

  async function handlePublishClick() {
    const confirmed = await showConfirmModal({
      title: "Publish to Repository",
      message: `This will push branch <strong>${sessionData.branch}</strong>, create a GitHub Pull Request, and auto-merge if there are no conflicts.`,
      actionText: "Publish & Merge",
      confirmClass: "hub-btn--primary",
    });

    if (!confirmed) return;

    const btn = document.getElementById("hub-btn-publish");
    setButtonLoading(btn, true, "Publishing...");

    try {
      const res = await fetch("/hub/publish", {
        method: "POST",
        headers: getHubHeaders(),
        body: JSON.stringify({}),
      });
      const data = await res.json();

      if (!res.ok) throw new Error(data.detail || "Failed to publish PR");

      if (data.status === "conflict") {
        showToast(`PR #${data.pr_number} created with conflicts. Review on GitHub.`, "warning", 8000);
        window.open(data.pr_url, "_blank");
      } else {
        showToast(`PR #${data.pr_number} merged successfully into main!`, "success", 6000);
      }
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setButtonLoading(btn, false, "Publish (PR)");
    }
  }

  async function handleFinishClick() {
    const confirmed = await showConfirmModal({
      title: "End Editing Session",
      message: "Are you sure you want to exit? <strong>Uncommitted changes will be lost.</strong> This will delete the Kubernetes pod.",
      actionText: "Terminate Session",
      confirmClass: "hub-btn--danger",
    });

    if (!confirmed) return;

    const btn = document.getElementById("hub-btn-finish");
    setButtonLoading(btn, true, "Terminating...");

    try {
      await fetch("/hub/kill", { method: "POST", headers: getHubHeaders() });
      renderTeardownOverlay();
    } catch (err) {
      showToast(`Teardown request failed: ${err.message}`, "error");
      setButtonLoading(btn, false, "Finish");
    }
  }

  // --- Modal Helpers ---

  function showPromptModal({ title, placeholder, actionText }) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "hub-modal-overlay";
      overlay.innerHTML = `
        <div class="hub-modal">
          <h3 class="hub-modal-title">${title}</h3>
          <textarea id="hub-prompt-input" class="hub-modal-input" rows="3" placeholder="${placeholder}"></textarea>
          <div class="hub-modal-footer">
            <button class="hub-btn hub-btn--subtle" id="hub-modal-cancel">Cancel</button>
            <button class="hub-btn hub-btn--primary" id="hub-modal-submit">${actionText}</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const input = overlay.querySelector("#hub-prompt-input");
      input.focus();

      const cleanup = (val) => {
        overlay.remove();
        resolve(val);
      };

      overlay.querySelector("#hub-modal-cancel").onclick = () => cleanup(null);
      overlay.querySelector("#hub-modal-submit").onclick = () => {
        const val = input.value.trim();
        if (val) cleanup(val);
      };
      overlay.onclick = (e) => {
        if (e.target === overlay) cleanup(null);
      };
    });
  }

  function showConfirmModal({ title, message, actionText, confirmClass }) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "hub-modal-overlay";
      overlay.innerHTML = `
        <div class="hub-modal">
          <h3 class="hub-modal-title">${title}</h3>
          <p class="hub-modal-body">${message}</p>
          <div class="hub-modal-footer">
            <button class="hub-btn hub-btn--subtle" id="hub-modal-cancel">Cancel</button>
            <button class="hub-btn ${confirmClass || "hub-btn--primary"}" id="hub-modal-submit">${actionText}</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const cleanup = (confirmed) => {
        overlay.remove();
        resolve(confirmed);
      };

      overlay.querySelector("#hub-modal-cancel").onclick = () => cleanup(false);
      overlay.querySelector("#hub-modal-submit").onclick = () => cleanup(true);
      overlay.onclick = (e) => {
        if (e.target === overlay) cleanup(false);
      };
    });
  }

  function renderTeardownOverlay() {
    const returnUrl = sessionData.parent_hub_url || "/";
    document.body.innerHTML = `
      <div style="display:flex;height:100vh;align-items:center;justify-content:center;background:#09090b;color:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,sans-serif;flex-direction:column;gap:16px;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        <h2 style="font-size:20px;font-weight:600;margin:0;">Session Terminated</h2>
        <p style="color:#a1a1aa;margin:0;font-size:14px;">The Kubernetes compute pod has been scheduled for deletion.</p>
        <a href="${returnUrl}" style="margin-top:12px;background:#2563eb;color:#fff;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:500;">
          Return to Insights Hub
        </a>
      </div>
    `;
  }

  // --- Notifications & Feedback ---

  function createToastContainer() {
    const container = document.createElement("div");
    container.id = "hub-toast-container";
    document.body.appendChild(container);
  }

  function showToast(message, type = "info", duration = 4000) {
    const container = document.getElementById("hub-toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `hub-toast hub-toast--${type}`;
    toast.innerText = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add("hub-toast--fading");
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  function setButtonLoading(btn, isLoading, label) {
    btn.disabled = isLoading;
    if (isLoading) {
      btn.dataset.origHtml = btn.innerHTML;
      btn.innerText = label;
      btn.style.opacity = "0.7";
      btn.style.cursor = "not-allowed";
    } else {
      if (btn.dataset.origHtml) btn.innerHTML = btn.dataset.origHtml;
      btn.style.opacity = "";
      btn.style.cursor = "";
    }
  }

  // --- Embedded Scoped CSS ---

  function injectStyles() {
    const style = document.createElement("style");
    style.id = "hub-toolbar-styles";
    style.textContent = `
      #hub-toolbar-root {
        position: fixed;
        top: 8px;
        right: 80px; /* Sits cleanly to the left of Marimo's native utility controls */
        z-index: 99999;
        display: flex;
        align-items: center;
        gap: 8px;
        background: rgba(18, 18, 20, 0.88);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.12);
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
        border-radius: 8px;
        padding: 4px 6px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 12px;
        color: #f4f4f5;
        user-select: none;
      }

      .hub-pill {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 4px 8px;
        background: rgba(255, 255, 255, 0.06);
        border-radius: 6px;
        cursor: default;
      }
      .hub-indicator {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background-color: #22c55e;
        box-shadow: 0 0 6px rgba(34, 197, 94, 0.6);
      }
      .hub-user-text {
        font-weight: 500;
        max-width: 150px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: #e4e4e7;
      }

      .hub-actions {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      .hub-btn {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 4px 9px;
        border-radius: 6px;
        border: 1px solid transparent;
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: background 0.15s ease, opacity 0.15s ease;
      }
      .hub-btn svg { flex-shrink: 0; }

      .hub-btn--secondary {
        background: rgba(255, 255, 255, 0.08);
        color: #f4f4f5;
        border-color: rgba(255, 255, 255, 0.12);
      }
      .hub-btn--secondary:hover { background: rgba(255, 255, 255, 0.15); }

      .hub-btn--primary {
        background: #2563eb;
        color: #ffffff;
      }
      .hub-btn--primary:hover { background: #1d4ed8; }

      .hub-btn--danger {
        background: rgba(239, 68, 68, 0.15);
        color: #fca5a5;
        border-color: rgba(239, 68, 68, 0.25);
      }
      .hub-btn--danger:hover { background: #dc2626; color: #fff; }

      .hub-btn--subtle {
        background: transparent;
        color: #a1a1aa;
      }
      .hub-btn--subtle:hover { color: #f4f4f5; }

      /* Modals */
      .hub-modal-overlay {
        position: fixed;
        inset: 0;
        z-index: 100000;
        background: rgba(0, 0, 0, 0.6);
        backdrop-filter: blur(4px);
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .hub-modal {
        background: #18181b;
        border: 1px solid rgba(255, 255, 255, 0.15);
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
        border-radius: 10px;
        width: 420px;
        max-width: 90vw;
        padding: 18px;
        color: #f4f4f5;
        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      }
      .hub-modal-title {
        margin: 0 0 10px 0;
        font-size: 15px;
        font-weight: 600;
      }
      .hub-modal-body {
        margin: 0 0 16px 0;
        font-size: 13px;
        color: #a1a1aa;
        line-height: 1.5;
      }
      .hub-modal-input {
        width: 100%;
        box-sizing: border-box;
        background: #09090b;
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 6px;
        padding: 8px 10px;
        color: #fff;
        font-size: 13px;
        font-family: inherit;
        resize: vertical;
        margin-bottom: 14px;
        outline: none;
      }
      .hub-modal-input:focus { border-color: #2563eb; }
      .hub-modal-footer {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
      }

      /* Toasts */
      #hub-toast-container {
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 100001;
        display: flex;
        flex-direction: column;
        gap: 8px;
        pointer-events: none;
      }
      .hub-toast {
        background: #18181b;
        border: 1px solid rgba(255, 255, 255, 0.15);
        color: #fff;
        padding: 10px 14px;
        border-radius: 8px;
        box-shadow: 0 4px 14px rgba(0,0,0,0.4);
        font-size: 13px;
        font-family: sans-serif;
        transition: opacity 0.3s ease;
      }
      .hub-toast--success { border-left: 4px solid #22c55e; }
      .hub-toast--error { border-left: 4px solid #ef4444; }
      .hub-toast--warning { border-left: 4px solid #eab308; }
      .hub-toast--fading { opacity: 0; }
    `;
    document.head.appendChild(style);
  }
})();