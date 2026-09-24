/* GMAT mock exam — front-end controller. */

let sid = null;
let phase = null;
let localRemaining = -1;   // seconds; -1 = untimed
let timerId = null;
let selectedChoice = null;
let calcVisible = false;

// ── Boot ──────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  Calculator.render();
  try {
    const res = await fetch("/api/topics");
    const data = await res.json();
    const sel = document.getElementById("practice-type");
    for (const t of data.topics) {
      const o = document.createElement("option");
      o.value = t.type;
      o.textContent = `${t.label} (${t.available})`;
      sel.appendChild(o);
    }
    if (!data.bank_size) {
      showError("Question bank is empty. Build it: python -m authoring.build_bank");
    }
  } catch (e) {
    showError("Could not reach the server.");
  }
});

function showError(msg) {
  document.getElementById("home-error").textContent = msg;
}

// ── Screen routing ────────────────────────────────────────────────────
function showScreen(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  document.getElementById(id).classList.add("active");
}

// ── Start ─────────────────────────────────────────────────────────────
async function startFull() {
  await start({ mode: "full" });
}

async function startPractice() {
  const qtype = document.getElementById("practice-type").value;
  const count = parseInt(document.getElementById("practice-count").value, 10) || 10;
  const timed = document.getElementById("practice-timed").checked;
  await start({ mode: "practice", qtype, count, timed });
}

async function start(body) {
  const res = await fetch("/api/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showError(err.detail || "Could not start.");
    return;
  }
  const payload = await res.json();
  sid = payload.sid;
  render(payload);
}

// ── Render dispatch ───────────────────────────────────────────────────
function render(payload) {
  phase = payload.phase;
  if (payload.section) syncTimer(payload.section);

  if (phase === "question") renderQuestion(payload);
  else if (phase === "review") renderReview(payload);
  else if (phase === "finished") renderResults(payload);
}

// ── Question screen ───────────────────────────────────────────────────
function renderQuestion(payload) {
  showScreen("screen-exam");
  const sec = payload.section;
  const q = payload.question;
  selectedChoice = null;

  document.getElementById("ex-section").textContent = sec.name;
  document.getElementById("ex-progress").textContent =
    `Question ${payload.question_number} of ${sec.num_questions}`;

  // Calculator visibility follows the section rule.
  const calcBtn = document.getElementById("calc-btn");
  calcBtn.classList.toggle("hidden", !sec.allow_calculator);
  if (!sec.allow_calculator) hideCalc();

  const passage = document.getElementById("passage");
  if (q.passage) {
    passage.textContent = q.passage;
    passage.classList.remove("hidden");
  } else {
    passage.classList.add("hidden");
  }

  document.getElementById("stem").textContent = q.stem;

  const form = document.getElementById("options");
  form.innerHTML = "";
  q.options.forEach((opt, i) => {
    const label = document.createElement("label");
    label.className = "opt";
    label.innerHTML =
      `<input type="radio" name="opt" value="${i}" /> <span>${escapeHtml(opt)}</span>`;
    label.querySelector("input").addEventListener("change", () => {
      selectedChoice = i;
      document.querySelectorAll(".opt").forEach((o) => o.classList.remove("selected"));
      label.classList.add("selected");
      document.getElementById("next-btn").disabled = false;
    });
    form.appendChild(label);
  });

  const nextBtn = document.getElementById("next-btn");
  nextBtn.disabled = true;
  nextBtn.textContent = payload.question_number >= sec.num_questions ? "Finish Section" : "Next";
  nextBtn.dataset.qid = q.id;
  typeset(document.getElementById("screen-exam"));
}

async function submitAnswer() {
  if (selectedChoice === null) return;
  const qid = document.getElementById("next-btn").dataset.qid;
  document.getElementById("next-btn").disabled = true;
  const res = await fetch("/api/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sid, qid, choice: selectedChoice }),
  });
  render(await res.json());
}

// ── Review screen ─────────────────────────────────────────────────────
function renderReview(payload) {
  showScreen("screen-review");
  const sec = payload.section;
  document.getElementById("rev-limit").textContent = sec.edit_limit;
  document.getElementById("rev-used").textContent = sec.edits_used;

  const list = document.getElementById("review-list");
  list.innerHTML = "";
  payload.review.forEach((item, idx) => {
    const div = document.createElement("div");
    div.className = "review-item";
    const opts = item.options
      .map(
        (o, i) =>
          `<label class="r-opt"><input type="radio" name="rev-${item.id}" value="${i}" ${
            item.chosen === i ? "checked" : ""
          }/> ${escapeHtml(o)}</label>`
      )
      .join("");
    const psg = item.passage ? `<div class="muted">${escapeHtml(item.passage)}</div>` : "";
    div.innerHTML = `<div class="r-stem"><strong>Q${idx + 1}.</strong> ${psg}${escapeHtml(
      item.stem
    )}</div>${opts}`;
    div.querySelectorAll(`input[name="rev-${item.id}"]`).forEach((inp) => {
      inp.addEventListener("change", () => editAnswer(item.id, parseInt(inp.value, 10)));
    });
    list.appendChild(div);
  });
  typeset(list);
}

async function editAnswer(qid, choice) {
  const res = await fetch("/api/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sid, qid, choice }),
  });
  const payload = await res.json();
  if (payload.edit_accepted === false) {
    alert("Edit limit reached for this section.");
  }
  if (payload.phase === "review") {
    document.getElementById("rev-used").textContent = payload.section.edits_used;
  } else {
    render(payload);
  }
}

async function confirmSection() {
  const res = await fetch("/api/confirm-section", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sid }),
  });
  render(await res.json());
}

// ── Results screen ────────────────────────────────────────────────────
function renderResults(payload) {
  stopTimer();
  hideCalc();
  showScreen("screen-results");
  const r = payload.results;
  const box = document.getElementById("score-summary");
  let html = "";
  if (r.total_score != null) {
    html += `<div class="score-card"><div class="muted">Total</div><div class="big">${r.total_score}</div><div class="muted">205–805</div></div>`;
  }
  for (const s of r.sections) {
    html += `<div class="score-card"><div class="muted">${escapeHtml(s.name)}</div>` +
      `<div class="big">${s.score}</div>` +
      `<div class="muted">${s.num_correct}/${s.num_served} correct</div></div>`;
  }
  box.innerHTML = html;
  loadQuickReport();
}

async function loadQuickReport() {
  const el = document.getElementById("quick-report");
  el.innerHTML = "<span class='muted'>Loading…</span>";
  try {
    const res = await fetch(`/api/analytics?sid=${sid}`);
    const data = await res.json();
    el.innerHTML = mdToHtml(data.markdown || "No analysis.");
    typeset(el);
  } catch (e) {
    el.innerHTML = "<span class='muted'>Could not load analysis.</span>";
  }
}

async function getReport() {
  const btn = document.getElementById("report-btn");
  btn.disabled = true;
  document.getElementById("report-status").textContent = "Analyzing your attempt with AI…";
  try {
    const res = await fetch("/api/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sid }),
    });
    const data = await res.json();
    document.getElementById("report-status").textContent = "";
    document.getElementById("report").innerHTML = mdToHtml(data.markdown || "No report.");
    typeset(document.getElementById("report"));
  } catch (e) {
    document.getElementById("report-status").textContent = "Report generation failed.";
    btn.disabled = false;
  }
}

// ── Timer ─────────────────────────────────────────────────────────────
function syncTimer(sec) {
  localRemaining = sec.timed ? sec.time_remaining : -1;
  if (localRemaining < 0) {
    document.getElementById("ex-timer").textContent = "Untimed";
    stopTimer();
    return;
  }
  startTimer();
}

function startTimer() {
  stopTimer();
  updateTimerDisplay();
  timerId = setInterval(() => {
    localRemaining -= 1;
    updateTimerDisplay();
    if (localRemaining <= 0) {
      stopTimer();
      // Let the server transition the section (time is up).
      fetch(`/api/state?sid=${sid}`).then((r) => r.json()).then(render);
    }
  }, 1000);
}

function stopTimer() {
  if (timerId) clearInterval(timerId);
  timerId = null;
}

function updateTimerDisplay() {
  const el = document.getElementById("ex-timer");
  const m = Math.floor(Math.max(0, localRemaining) / 60);
  const s = Math.max(0, localRemaining) % 60;
  el.textContent = `${m}:${String(s).padStart(2, "0")}`;
  el.classList.toggle("warn", localRemaining <= 60);
}

// ── Calculator toggle ─────────────────────────────────────────────────
function toggleCalc() {
  calcVisible = !calcVisible;
  document.getElementById("calculator").classList.toggle("hidden", !calcVisible);
}
function hideCalc() {
  calcVisible = false;
  document.getElementById("calculator").classList.add("hidden");
}

// ── Helpers ───────────────────────────────────────────────────────────
function typeset(el) {
  if (window.renderMathInElement && el) {
    try {
      renderMathInElement(el, {
        delimiters: [
          { left: "\\[", right: "\\]", display: true },
          { left: "\\(", right: "\\)", display: false },
        ],
        throwOnError: false,
      });
    } catch (e) {}
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Minimal Markdown -> HTML (headings, bold, lists, tables, paragraphs).
function mdToHtml(md) {
  const lines = md.split("\n");
  let html = "", inList = false, inTable = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  const closeTable = () => { if (inTable) { html += "</table>"; inTable = false; } };

  for (let raw of lines) {
    let line = escapeHtml(raw).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    if (/^\s*\|(.+)\|\s*$/.test(raw)) {
      if (/^\s*\|[\s:|-]+\|\s*$/.test(raw)) continue; // separator row
      if (!inTable) { closeList(); html += "<table>"; inTable = true; }
      const cells = raw.split("|").slice(1, -1).map((c) => `<td>${escapeHtml(c.trim())}</td>`).join("");
      html += `<tr>${cells}</tr>`;
      continue;
    }
    closeTable();
    if (/^###\s+/.test(raw)) { closeList(); html += `<h3>${line.replace(/^###\s+/, "")}</h3>`; }
    else if (/^##\s+/.test(raw)) { closeList(); html += `<h2>${line.replace(/^##\s+/, "")}</h2>`; }
    else if (/^#\s+/.test(raw)) { closeList(); html += `<h1>${line.replace(/^#\s+/, "")}</h1>`; }
    else if (/^\s*[-*]\s+/.test(raw)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${line.replace(/^\s*[-*]\s+/, "")}</li>`;
    } else if (raw.trim() === "") { closeList(); }
    else { closeList(); html += `<p>${line}</p>`; }
  }
  closeList(); closeTable();
  return html;
}
