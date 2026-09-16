const state = {
  history: [],
  display: [],
  abortController: null,
  lastUserMessage: null,
  activeAssistantId: null,
  messageId: 0,
};

const elements = {
  composer: document.querySelector("#composer"),
  input: document.querySelector("#message-input"),
  messages: document.querySelector("#messages"),
  welcome: document.querySelector("#welcome"),
  followups: document.querySelector("#followups"),
  send: document.querySelector("#send-button"),
  stop: document.querySelector("#stop-button"),
  clear: document.querySelector("#clear-button"),
  regenerate: document.querySelector("#regenerate-button"),
  modal: document.querySelector("#modal"),
  how: document.querySelector("#how-button"),
  modalClose: document.querySelector("#modal-close"),
  menuButton: document.querySelector("#menu-button"),
  menu: document.querySelector("#menu"),
};

function nextId() {
  state.messageId += 1;
  return `message-${state.messageId}`;
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMarkdownish(text) {
  const lines = escapeHtml(text).split(/\n+/);
  const blocks = [];
  let list = [];

  const flushList = () => {
    if (!list.length) return;
    blocks.push(`<ul>${list.map((item) => `<li>${item}</li>`).join("")}</ul>`);
    list = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      continue;
    }
    const bullet = trimmed.match(/^[-*]\s+(.+)/);
    if (bullet) {
      list.push(formatInline(bullet[1]));
      continue;
    }
    flushList();
    blocks.push(`<p>${formatInline(trimmed)}</p>`);
  }
  flushList();
  return blocks.join("");
}

function formatInline(text) {
  return text.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
}

function isNearBottom() {
  return window.innerHeight + window.scrollY >= document.body.scrollHeight - 180;
}

function scrollIfNeeded(shouldScroll) {
  if (!shouldScroll) return;
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  });
}

function setBusy(isBusy) {
  elements.send.disabled = isBusy;
  elements.input.disabled = isBusy;
  elements.stop.hidden = !isBusy;
}

function updateWelcome() {
  elements.welcome.classList.toggle("hidden", state.display.length > 0);
}

function avatarHtml(extraClass = "") {
  return `
    <span class="message-avatar ${extraClass}" aria-hidden="true">
      <img src="/static/assets/anish-avatar-chat.png" alt="" onerror="this.hidden=true" />
      <span>A</span>
    </span>
  `;
}

function statusHtml(label) {
  return `
    <div class="thinking">
      <span>${escapeHtml(label || "Anish is thinking...")}</span>
      <i></i><i></i><i></i>
    </div>
  `;
}

function appendMessage(message) {
  state.display.push(message);
  const shouldScroll = isNearBottom();
  elements.messages.appendChild(createMessageElement(message));
  updateWelcome();
  scrollIfNeeded(shouldScroll);
}

function createMessageElement(message) {
  const row = document.createElement("article");
  row.className = `message ${message.role}`;
  row.dataset.id = message.id;

  if (message.role === "assistant") {
    row.insertAdjacentHTML("beforeend", avatarHtml(message.loading ? "thinking-avatar" : ""));
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  row.appendChild(bubble);
  updateMessageElement(row, message, { shouldScroll: false });
  return row;
}

function updateMessageElement(row, message, { shouldScroll = true } = {}) {
  const keepFollowing = shouldScroll && isNearBottom();
  const bubble = row.querySelector(".bubble");
  const avatar = row.querySelector(".message-avatar");

  if (avatar) {
    avatar.classList.toggle("thinking-avatar", Boolean(message.loading));
  }

  if (message.role === "user") {
    bubble.textContent = message.content;
  } else if (message.loading && !message.content) {
    bubble.innerHTML = statusHtml(message.status);
  } else {
    bubble.innerHTML = renderMarkdownish(message.content || message.fallback || "");
    if (message.status && message.loading) {
      bubble.insertAdjacentHTML("beforeend", `<p class="stream-status">${escapeHtml(message.status)}</p>`);
    }
    if (!message.loading) {
      bubble.appendChild(messageActions(message));
      if (message.sources?.length) bubble.appendChild(sourcePanel(message.sources));
      if (message.why) bubble.appendChild(whyPanel(message.why));
    }
  }

  scrollIfNeeded(keepFollowing);
}

function updateAssistant(message) {
  const row = elements.messages.querySelector(`[data-id="${message.id}"]`);
  if (row) updateMessageElement(row, message);
}

function messageActions(message) {
  const actions = document.createElement("div");
  actions.className = "message-actions";

  const copy = document.createElement("button");
  copy.className = "mini-action";
  copy.type = "button";
  copy.textContent = "Copy";
  copy.addEventListener("click", async () => {
    await navigator.clipboard.writeText(message.content || "");
    copy.textContent = "Copied";
    setTimeout(() => (copy.textContent = "Copy"), 1000);
  });
  actions.appendChild(copy);

  if (message.error || message.stopped) {
    const retry = document.createElement("button");
    retry.className = "mini-action";
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", regenerate);
    actions.appendChild(retry);
  }

  if (message.sources?.length) {
    const sources = document.createElement("button");
    sources.className = "source-toggle";
    sources.type = "button";
    sources.textContent = `Grounded in ${message.sources.length} verified source${message.sources.length === 1 ? "" : "s"}`;
    sources.addEventListener("click", () => {
      actions.parentElement.querySelector(".source-panel")?.classList.toggle("open");
    });
    actions.appendChild(sources);
  }

  if (message.why) {
    const why = document.createElement("button");
    why.className = "mini-action";
    why.type = "button";
    why.textContent = "Why this answer?";
    why.addEventListener("click", () => {
      actions.parentElement.querySelector(".why-panel")?.classList.toggle("open");
    });
    actions.appendChild(why);
  }

  return actions;
}

function sourcePanel(sources) {
  const panel = document.createElement("section");
  panel.className = "source-panel";
  panel.innerHTML = `
    <h3>Sources behind this answer</h3>
    <ul class="source-list">
      ${sources.map(sourceCardHtml).join("")}
    </ul>
  `;
  return panel;
}

function sourceCardHtml(source) {
  const link = source.link
    ? `<a href="${escapeHtml(source.link)}" target="_blank" rel="noreferrer">Open public source</a>`
    : "";
  return `
    <li class="source-card">
      <strong>${escapeHtml(source.title)}</strong>
      <span>${escapeHtml(source.meta || source.kind || "Verified source")}</span>
      <p><b>Supports:</b> ${escapeHtml(source.supports || "Verified details used in this answer.")}</p>
      ${source.excerpt ? `<blockquote>${escapeHtml(source.excerpt)}</blockquote>` : ""}
      ${link}
    </li>
  `;
}

function whyPanel(why) {
  const panel = document.createElement("section");
  panel.className = "why-panel";
  panel.innerHTML = `<p>${escapeHtml(why)}</p>`;
  return panel;
}

function renderFollowups(suggestions = []) {
  elements.followups.innerHTML = "";
  if (!suggestions.length) return;
  const heading = document.createElement("p");
  heading.textContent = "Ask a follow-up";
  elements.followups.appendChild(heading);
  for (const suggestion of suggestions.slice(0, 3)) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = suggestion;
    button.addEventListener("click", () => submitMessage(suggestion));
    elements.followups.appendChild(button);
  }
}

function clearFollowups() {
  elements.followups.innerHTML = "";
}

function autoGrow() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 170)}px`;
}

function trimHistory() {
  state.history = state.history.slice(-24);
}

async function submitMessage(text, { replaceLast = false } = {}) {
  const message = text.trim();
  if (!message || state.abortController) return;

  clearFollowups();
  state.lastUserMessage = message;
  if (!replaceLast) {
    appendMessage({ id: nextId(), role: "user", content: message });
  }

  const assistant = {
    id: nextId(),
    role: "assistant",
    content: "",
    loading: true,
    status: "Searching Anish’s verified sources...",
    sources: [],
    suggestions: [],
    why: "",
  };
  state.activeAssistantId = assistant.id;
  appendMessage(assistant);
  elements.input.value = "";
  autoGrow();
  setBusy(true);

  state.abortController = new AbortController();
  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: state.history }),
      signal: state.abortController.signal,
    });

    if (!response.ok) {
      throw new Error("Request failed");
    }

    const data = await readStreamedAnswer(response, assistant);
    assistant.loading = false;
    assistant.content = data.answer || assistant.content || "I got an empty response. Please try asking again.";
    assistant.sources = data.sources || assistant.sources || [];
    assistant.suggestions = data.suggestions || [];
    assistant.why = data.why || "";
    assistant.status = "";
    updateAssistant(assistant);

    state.history.push({ role: "user", content: message });
    state.history.push({ role: "assistant", content: assistant.content });
    trimHistory();
    renderFollowups(assistant.suggestions);
  } catch (error) {
    const stopped = error.name === "AbortError";
    assistant.loading = false;
    assistant.stopped = stopped;
    assistant.error = !stopped;
    assistant.status = "";
    if (!assistant.content) {
      assistant.content = stopped
        ? "I stopped that response before any answer text arrived."
        : "I’m having trouble answering right now. Please try again in a moment.";
    } else if (stopped) {
      assistant.content = `${assistant.content}\n\nStopped here.`;
    }
    updateAssistant(assistant);
  } finally {
    state.abortController = null;
    state.activeAssistantId = null;
    setBusy(false);
    elements.input.focus();
  }
}

async function readStreamedAnswer(response, assistant) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";
  let sources = [];
  let suggestions = [];
  let why = "";

  const applyEvent = (rawEvent) => {
    const lines = rawEvent.split("\n").filter(Boolean);
    const eventLine = lines.find((line) => line.startsWith("event:"));
    const dataLine = lines.find((line) => line.startsWith("data:"));
    if (!eventLine || !dataLine) return;

    const eventType = eventLine.slice(6).trim();
    const payload = JSON.parse(dataLine.slice(5).trim());

    if (eventType === "status") {
      assistant.status = payload.label || "";
      updateAssistant(assistant);
    }

    if (eventType === "meta") {
      sources = payload.sources || [];
      assistant.sources = sources;
    }

    if (eventType === "token") {
      answer += payload.content || "";
      assistant.loading = true;
      assistant.content = answer;
      updateAssistant(assistant);
    }

    if (eventType === "done") {
      answer = payload.answer || answer;
      sources = payload.sources || sources;
      suggestions = payload.suggestions || [];
      why = payload.why || "";
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    events.forEach(applyEvent);
  }

  if (buffer.trim()) applyEvent(buffer);
  return { answer, sources, suggestions, why };
}

function clearConversation() {
  if (state.abortController) state.abortController.abort();
  state.history = [];
  state.display = [];
  state.lastUserMessage = null;
  state.activeAssistantId = null;
  elements.messages.innerHTML = "";
  clearFollowups();
  updateWelcome();
  elements.input.focus();
}

function regenerate() {
  if (state.abortController || !state.lastUserMessage) return;
  const lastAssistant = [...state.display].reverse().find((item) => item.role === "assistant");
  if (lastAssistant) {
    state.display = state.display.filter((item) => item.id !== lastAssistant.id);
    elements.messages.querySelector(`[data-id="${lastAssistant.id}"]`)?.remove();
  }
  if (state.history[state.history.length - 1]?.role === "assistant") state.history.pop();
  if (state.history[state.history.length - 1]?.role === "user") state.history.pop();
  submitMessage(state.lastUserMessage, { replaceLast: true });
}

elements.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  submitMessage(elements.input.value);
});

elements.input.addEventListener("input", autoGrow);
elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.composer.requestSubmit();
  }
});

elements.stop.addEventListener("click", () => {
  if (state.abortController) state.abortController.abort();
});

elements.clear.addEventListener("click", clearConversation);
elements.regenerate.addEventListener("click", regenerate);

document.querySelectorAll(".suggestions button").forEach((button) => {
  button.addEventListener("click", () => submitMessage(button.textContent));
});

elements.how.addEventListener("click", () => {
  elements.modal.hidden = false;
  elements.modalClose.focus();
});

elements.modalClose.addEventListener("click", () => {
  elements.modal.hidden = true;
  elements.how.focus();
});

elements.modal.addEventListener("click", (event) => {
  if (event.target === elements.modal) elements.modal.hidden = true;
});

elements.menuButton.addEventListener("click", () => {
  const next = elements.menu.hidden;
  elements.menu.hidden = !next;
  elements.menuButton.setAttribute("aria-expanded", String(next));
});

document.addEventListener("click", (event) => {
  if (!elements.menu.contains(event.target) && event.target !== elements.menuButton) {
    elements.menu.hidden = true;
    elements.menuButton.setAttribute("aria-expanded", "false");
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    elements.modal.hidden = true;
    elements.menu.hidden = true;
    elements.menuButton.setAttribute("aria-expanded", "false");
  }
});

document.querySelectorAll(".brand-avatar img, .message-avatar img").forEach((img) => {
  img.addEventListener("error", () => img.setAttribute("hidden", ""));
});

updateWelcome();
window.setTimeout(() => window.scrollTo({ left: 0, top: 0, behavior: "auto" }), 50);
