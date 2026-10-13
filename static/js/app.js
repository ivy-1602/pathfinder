(function () {
  const token = document.querySelector('meta[name="csrf-token"]').content;

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Something went wrong. Please try again.");
    return data;
  }

  // Minimal, safe formatter: escapes HTML first, then supports **bold** and "- " bullets.
  function format(text) {
    const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const lines = esc(text).split("\n");
    let html = "", inList = false;
    for (const raw of lines) {
      const line = raw.trim();
      const bullet = line.match(/^[-*]\s+(.*)/);
      if (bullet) { if (!inList) { html += "<ul>"; inList = true; } html += "<li>" + bullet[1] + "</li>"; continue; }
      if (inList) { html += "</ul>"; inList = false; }
      if (line) html += "<p>" + line + "</p>";
    }
    if (inList) html += "</ul>";
    return html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }

  // Personal fit analysis on the opportunity page
  const fitBtn = document.getElementById("fit-btn");
  if (fitBtn) {
    const out = document.getElementById("fit-output");
    fitBtn.addEventListener("click", async () => {
      fitBtn.disabled = true; fitBtn.textContent = "Analysing...";
      try {
        const data = await postJSON(fitBtn.dataset.url);
        out.textContent = data.text;
        fitBtn.textContent = "Analyse again";
      } catch (err) {
        out.textContent = err.message; fitBtn.textContent = "Try again";
      } finally { fitBtn.disabled = false; }
    });
  }

  // Advisor chat
  const form = document.getElementById("chat-form");
  if (form) {
    const chat = document.getElementById("chat");
    const input = document.getElementById("chat-input");
    const send = document.getElementById("chat-send");
    const history = [];
    const add = (cls, html) => {
      const div = document.createElement("div");
      div.className = "msg " + cls; div.innerHTML = html;
      chat.appendChild(div); chat.scrollTop = chat.scrollHeight; return div;
    };
    add("msg-bot", "<p>Hi! Ask me what to study next, how your matches compare, or how to prepare for an internship.</p>");

    async function ask(question) {
      history.push({ role: "user", content: question });
      add("msg-user", format(question));
      const pending = add("msg-bot pending", "Thinking...");
      send.disabled = true;
      try {
        const data = await postJSON(form.dataset.url, { messages: history });
        history.push({ role: "assistant", content: data.reply });
        pending.className = "msg msg-bot"; pending.innerHTML = format(data.reply);
      } catch (err) {
        history.pop();
        pending.className = "msg msg-bot"; pending.textContent = err.message;
      } finally { send.disabled = false; input.focus(); chat.scrollTop = chat.scrollHeight; }
    }
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (!q) return;
      input.value = ""; ask(q);
    });
    document.querySelectorAll("[data-prompt]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.prompt)));
  }

  // Roadmap generation can take a few seconds
  const rf = document.getElementById("roadmap-form");
  if (rf) rf.addEventListener("submit", () => {
    const b = rf.querySelector("button[type=submit]"); b.disabled = true; b.textContent = "Building your roadmap...";
  });
})();
