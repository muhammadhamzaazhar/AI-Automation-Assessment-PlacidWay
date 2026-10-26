// Chat UI. Conversation state lives in the browser and is sent with each request,
// so the server stays stateless.
const HISTORY_LIMIT = 12; // messages sent back for follow-up questions

const state = { history: [], disclaimerShown: false, busy: false };

const messagesEl = document.getElementById("messages");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const suggestions = document.getElementById("suggestions");

form.addEventListener("submit", (event) => {
  event.preventDefault();
  send(input.value);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send(input.value);
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
});

suggestions.addEventListener("click", (event) => {
  if (event.target.tagName === "BUTTON") send(event.target.textContent);
});

document.getElementById("new-chat").addEventListener("click", () => {
  state.history = [];
  state.disclaimerShown = false;
  messagesEl.querySelectorAll(".message:not(:first-child)").forEach((el) => el.remove());
  suggestions.hidden = false;
  input.focus();
});

async function send(rawText) {
  const text = rawText.trim();
  if (!text || state.busy) return;

  setBusy(true);
  suggestions.hidden = true;
  input.value = "";
  input.style.height = "auto";
  addUserMessage(text);
  const typing = addTypingIndicator();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        history: state.history.slice(-HISTORY_LIMIT),
        disclaimer_shown: state.disclaimerShown,
      }),
    });
    const data = await response.json().catch(() => ({}));
    typing.remove();

    if (!response.ok) {
      addErrorMessage(errorText(response.status, data));
      return;
    }
    if (data.disclaimer) state.disclaimerShown = true;
    state.history.push({ role: "user", content: text }, { role: "assistant", content: data.answer });
    addBotMessage(data);
  } catch (error) {
    typing.remove();
    addErrorMessage("Connection problem. Please check your internet connection and try again.");
  } finally {
    setBusy(false);
    input.focus();
  }
}

function setBusy(busy) {
  state.busy = busy;
  sendButton.disabled = busy;
}

function errorText(status, data) {
  if (status === 429) return data.detail || "Too many requests. Please wait a minute.";
  if (status === 422) return "Please enter a question (up to 1000 characters).";
  return data.detail || "Something went wrong. Please try again.";
}

// --- rendering --------------------------------------------------------------------

function addUserMessage(text) {
  const bubble = appendMessage("user");
  bubble.textContent = text;
}

function addErrorMessage(text) {
  const bubble = appendMessage("bot");
  const p = document.createElement("p");
  p.className = "error-text";
  p.textContent = text;
  bubble.append(p);
}

function addTypingIndicator() {
  const bubble = appendMessage("bot", { timestamp: false });
  bubble.classList.add("typing");
  bubble.setAttribute("aria-label", "Assistant is typing");
  bubble.innerHTML = "<span></span><span></span><span></span>";
  return bubble.closest(".message");
}

function addBotMessage(data) {
  const bubble = appendMessage("bot");
  bubble.innerHTML = renderMarkdown(data.answer);

  if (data.sources && data.sources.length) {
    const box = document.createElement("div");
    box.className = "sources";
    box.innerHTML = "<span>Sources</span>";
    const list = document.createElement("ul");
    for (const source of data.sources) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = source.url;
      link.textContent = source.title;
      link.target = "_blank";
      link.rel = "noopener";
      item.append(link);
      list.append(item);
    }
    box.append(list);
    bubble.append(box);
  }

  if (data.disclaimer) {
    const note = document.createElement("div");
    note.className = "disclaimer";
    note.textContent = data.disclaimer;
    bubble.append(note);
  }

  if (data.show_quote_cta) bubble.append(buildCallToAction(data.quote_url));
}

// Builds <div.message> <div.stack> <div.bubble/> <time/> </div> </div> and returns the bubble.
function appendMessage(role, { timestamp = true } = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;
  wrapper.dir = "auto"; // right-to-left for Arabic
  const stack = document.createElement("div");
  stack.className = "stack";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  stack.append(bubble);
  if (timestamp) {
    const time = document.createElement("time");
    time.textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    stack.append(time);
  }
  wrapper.append(stack);
  messagesEl.append(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

// Minimal, safe Markdown: escape everything, then allow **bold** and "- " bullet lists.
function renderMarkdown(text) {
  const escape = (s) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const inline = (s) => escape(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  const html = [];
  let list = [];
  let paragraph = [];
  const flushList = () => { if (list.length) html.push(`<ul>${list.join("")}</ul>`); list = []; };
  const flushParagraph = () => { if (paragraph.length) html.push(`<p>${paragraph.join("<br>")}</p>`); paragraph = []; };

  for (const line of text.split("\n")) {
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bullet) {
      flushParagraph();
      list.push(`<li>${inline(bullet[1])}</li>`);
    } else if (!line.trim()) {
      flushList();
      flushParagraph();
    } else {
      flushList();
      paragraph.push(inline(line));
    }
  }
  flushList();
  flushParagraph();
  return html.join("");
}

// --- quote / lead capture -----------------------------------------------------------

function buildCallToAction(quoteUrl) {
  const container = document.createElement("div");
  const actions = document.createElement("div");
  actions.className = "cta";

  const quoteLink = document.createElement("a");
  quoteLink.href = quoteUrl;
  quoteLink.target = "_blank";
  quoteLink.rel = "noopener";
  quoteLink.className = "pill primary";
  quoteLink.textContent = "Get a free quote ↗";

  const detailsButton = document.createElement("button");
  detailsButton.type = "button";
  detailsButton.className = "pill";
  detailsButton.textContent = "Leave my details here";
  detailsButton.addEventListener("click", () => {
    detailsButton.remove();
    container.append(buildLeadForm());
  });

  actions.append(quoteLink, detailsButton);
  container.append(actions);
  return container;
}

function buildLeadForm() {
  const form = document.getElementById("lead-form-template").content.firstElementChild.cloneNode(true);
  const errorEl = form.querySelector(".lead-error");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    errorEl.hidden = true;

    const fields = new FormData(form);
    try {
      const response = await fetch("/api/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: fields.get("name"),
          email: fields.get("email"),
          message: fields.get("message") || null,
          consent: fields.get("consent") === "on",
          conversation: state.history.slice(-HISTORY_LIMIT),
        }),
      });
      if (!response.ok) throw new Error(response.status === 422 ? "Please check your name and email." : "Could not send your details. Please try again.");
      const thanks = document.createElement("p");
      thanks.textContent = `Thank you! PlacidWay's team will contact you at ${fields.get("email")}.`;
      form.replaceWith(thanks);
    } catch (error) {
      errorEl.textContent = error.message;
      errorEl.hidden = false;
      submit.disabled = false;
    }
  });
  return form;
}
