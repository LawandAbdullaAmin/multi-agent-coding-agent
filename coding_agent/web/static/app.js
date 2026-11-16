// Web interface of the coding agent: turns server events (server-sent events) into the feed and the 3D scene.

import { AGENTS, SUPERVISOR, Universe } from "./galaxy.js";
import { PREVIEW_EVENTS } from "./preview.js";

const ICONS = {
  compass: '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  flask: '<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
  code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
  dot: '<circle cx="12" cy="12" r="3"/>',
};

const $ = (id) => document.getElementById(id);
const state = {
  project: null, sessionId: null, source: null, cards: {}, steps: 0, unseen: 0, timer: null, elapsed: 0,
  preview: false, sheetOpen: false, sheetReady: false, previewTimers: [],
};

const galaxy = new Universe($("space"), $("spaceLabels"));
galaxy.anchor($("heroGalaxy"));
galaxy.idle(true);

// ---------- Helpers ----------

function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
}

function avatar(agent) {
  return `<div class="avatar" style="--c:${agent.color}">${icon(agent.icon)}</div>`;
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Small Markdown subset for the reports: **bold**, `code`, lists, paragraphs.
function formatText(text) {
  const inline = (line) => escapeHtml(line)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, '<span class="mono">$1</span>');
  let html = "", inList = false;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const item = line.match(/^(?:[-*•]|\d+\.)\s+(.*)/);
    if (item) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(item[1])}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }
    if (line) html += `<p>${inline(line.replace(/^#+\s*/, ""))}</p>`;
  }
  return html + (inList ? "</ul>" : "");
}

function tween(element, to, format, duration = 700) {
  const from = Number(element.dataset.value || 0);
  const start = performance.now();
  element.dataset.value = to;
  const frame = () => {
    // performance.now() instead of the requestAnimationFrame time: the two can differ
    const p = Math.min(Math.max((performance.now() - start) / duration, 0), 1);
    element.textContent = format(from + (to - from) * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(el.hideTimer);
  el.hideTimer = setTimeout(() => el.classList.add("hidden"), 7000);
}

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Error ${response.status}`);
  }
  return response.json();
}

// ---------- Start page ----------

async function initStart() {
  const [status, projects] = await Promise.all([api("/api/status"), api("/api/projects")]);
  $("budgetHint").textContent = `all roles on ${status.budget_models.fast}`;
  $("budgetToggle").addEventListener("change", (e) => {
    $("costHint").textContent = e.target.checked
      ? "Estimated cost per run: about 1–3 cents"
      : `Judging roles on ${status.models.strong}: about 5–10 cents per run`;
  });
  if (!status.docker) {
    $("sandboxToggle").checked = false;
    $("sandboxToggle").disabled = true;
    $("sandboxHint").textContent = "Docker Desktop is not running";
  }

  $("projectCount").textContent = `${projects.length} projects`;
  $("projectGrid").innerHTML = projects.map((p) => `
    <button class="project" data-id="${p.id}">
      <div class="project-name">${escapeHtml(p.name)}</div>
      <div class="project-kind">${escapeHtml(p.kind)}</div>
      <span class="badge ${p.difficulty}">${p.difficulty}</span>
    </button>`).join("");
  const select = (id) => {
    state.project = projects.find((p) => p.id === id);
    document.querySelectorAll(".project").forEach((el) => el.classList.toggle("selected", el.dataset.id === id));
    $("taskInput").value = state.project.task;
  };
  document.querySelectorAll(".project").forEach((el) => el.addEventListener("click", () => select(el.dataset.id)));
  select((projects.find((p) => p.name === "roman") || projects[0]).id);
  $("startButton").addEventListener("click", startRun);
}

async function startRun() {
  const button = $("startButton");
  button.disabled = true;
  button.querySelector("span").textContent = "Starting team …";
  try {
    const { id } = await api("/api/runs", {
      project: state.project.id, task: $("taskInput").value,
      budget: $("budgetToggle").checked, sandbox: $("sandboxToggle").checked,
    });
    openRun(id);
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Start team";
  }
}

// ---------- Run view ----------

function openRun(id) {
  state.source?.close();
  stopPreview();
  Object.assign(state, { sessionId: id, cards: {}, steps: 0, unseen: 0, elapsed: 0, sheetReady: false });
  $("feed").innerHTML = "";
  $("feedCount").textContent = "0 steps";
  $("newSteps").classList.add("hidden");
  for (const key of ["statCost", "statTokens"]) $(key).dataset.value = 0;
  $("statCost").textContent = "$0.000";
  $("statTokens").textContent = "0";
  $("statTime").textContent = "0:00";
  hideSheet();
  galaxy.idle(false);
  galaxy.reset();
  galaxy.anchor($("stage"));
  $("startScreen").classList.add("hidden");
  $("runScreen").classList.remove("hidden");
  $("runMeta").classList.remove("hidden");
  window.scrollTo({ top: 0 });
  setStatus("working", "Team is working");
  startTimer();

  if (id === "preview") {
    // Simulated run without a server and without cost, e.g. for demonstrating the interface
    state.previewTimers = PREVIEW_EVENTS.map(([at, event]) => setTimeout(() => handle(event), at));
    return;
  }
  state.source = new EventSource(`/api/runs/${id}/events`);
  state.source.onmessage = (message) => handle(JSON.parse(message.data));
}

function stopPreview() {
  state.previewTimers.forEach(clearTimeout);
  state.previewTimers = [];
}

function setStatus(kind, text) {
  $("statusPill").className = `status-pill ${kind}`;
  $("statusText").textContent = text;
}

function startTimer() {
  clearInterval(state.timer);
  state.timer = setInterval(() => {
    state.elapsed += 1;
    $("statTime").textContent = `${Math.floor(state.elapsed / 60)}:${String(state.elapsed % 60).padStart(2, "0")}`;
  }, 1000);
}

function stopTimer() { clearInterval(state.timer); }

// The feed never scrolls by itself. If something new is outside the visible area,
// a button appears that lets you jump down yourself.
function noteNew(element) {
  const feed = $("feed");
  if (element.offsetTop + element.offsetHeight <= feed.scrollTop + feed.clientHeight + 4) return;
  state.unseen += 1;
  const button = $("newSteps");
  button.textContent = `↓ ${state.unseen} ${state.unseen === 1 ? "new step" : "new steps"}`;
  button.classList.remove("hidden");
}

function clearUnseen() {
  state.unseen = 0;
  $("newSteps").classList.add("hidden");
}

function countStep() {
  state.steps += 1;
  $("feedCount").textContent = `${state.steps} steps`;
}

function addCard(html, className = "", color = SUPERVISOR.color) {
  const card = document.createElement("article");
  card.className = `card ${className}`;
  card.style.setProperty("--c", color);
  card.innerHTML = html;
  $("feed").appendChild(card);
  noteNew(card);
  return card;
}

function agentCard(key, instruction) {
  const agent = AGENTS[key];
  state.cards[key] = addCard(`
    <div class="card-head">${avatar(agent)}
      <div><div class="card-title">${agent.name}</div><div class="card-sub">${agent.role}</div></div>
      <span class="spacer"></span><span class="typing"><i></i><i></i><i></i></span>
    </div>
    ${instruction ? `<p class="instruction">${escapeHtml(instruction)}</p>` : ""}
    <ul class="steps"></ul>`, "working", agent.color);
}

function addStep(key, text, kind = "") {
  const card = state.cards[key];
  if (!card) return;
  const symbol = kind === "ok" ? "check" : kind === "bad" ? "x" : "dot";
  const list = card.querySelector(".steps");
  list.insertAdjacentHTML("beforeend",
    `<li class="step ${kind}"><span class="bullet">${icon(symbol)}</span><span>${escapeHtml(text)}</span></li>`);
  noteNew(list.lastElementChild);
  countStep();
}

function addReport(event) {
  const card = state.cards[event.agent];
  if (!card) return;
  card.classList.remove("working");
  card.querySelector(".typing")?.remove();
  if (event.model) card.querySelector(".card-head").insertAdjacentHTML("beforeend", `<span class="model-tag">${escapeHtml(event.model)}</span>`);
  const verdict = event.approved === undefined ? "" : event.approved
    ? `<span class="verdict yes">${icon("check")} Approved</span>`
    : `<span class="verdict no">${icon("x")} Needs rework</span>`;
  const text = event.text.replace(/^Approved: (yes|no)\.\s*/, "");
  const short = text.length > 340 ? text.slice(0, 340).replace(/\s+\S*$/, "") + " …" : text;
  card.insertAdjacentHTML("beforeend", `<div class="report">${verdict}<div class="report-text">${formatText(short)}</div>
    ${short !== text ? '<button class="more">Show full report</button>' : ""}</div>`);
  card.querySelector(".more")?.addEventListener("click", (e) => {
    card.querySelector(".report-text").innerHTML = formatText(text);
    e.target.remove();
  });
  noteNew(card.lastElementChild);
  delete state.cards[event.agent];
  galaxy.report(event.agent, event.model);
}

// ---------- Events from the server ----------

const handlers = {
  run(event) {
    state.preview = Boolean(event.preview);
    const source = event.preview ? "Preview (simulated) · " : "";
    $("taskProject").textContent = `${source}Project ${event.project}`;
    $("taskText").textContent = event.task;
  },
  dispatch(event) {
    if (event.agent === "finish") {
      galaxy.finish();
      addCard(`<div class="card-head">${avatar(SUPERVISOR)}<div><div class="card-title">Supervisor</div>
        <div class="card-sub">Work finished</div></div></div>${event.text ? `<div class="report">${formatText(event.text)}</div>` : ""}`);
      return;
    }
    galaxy.dispatch(event.agent);
    agentCard(event.agent, event.text);
    countStep();
  },
  action(event) { addStep(event.agent, event.text); },
  observation(event) { addStep(event.agent, event.text, event.ok ? "ok" : "bad"); },
  report(event) { addReport(event); },
  guardrail(event) {
    galaxy.guardrail();
    addCard(`<div class="card-head"><div class="avatar" style="--c:var(--amber)">${icon("alert")}</div>
      <div><div class="card-title">Guardrail</div><div class="card-sub">Finish blocked, not verified yet</div></div></div>
      <p class="instruction">${escapeHtml(event.text)}</p>`, "guard", "#fbbf24");
    countStep();
  },
  feedback(event) {
    addCard(`<div class="card-head">${avatar({ color: "#e2e8f0", icon: "user" })}<div><div class="card-title">Your feedback</div>
      <div class="card-sub">to the supervisor</div></div></div><p class="instruction">${escapeHtml(event.text)}</p>`, "", "#e2e8f0");
  },
  decision(event) {
    if (event.action === "feedback") {
      state.sheetReady = false;
      hideSheet();
      setStatus("working", "Team is working");
      startTimer();
    }
  },
  stats(event) {
    tween($("statCost"), event.cost, (v) => `$${v.toFixed(3)}`);
    tween($("statTokens"), event.tokens, (v) => Math.round(v).toLocaleString("en-US"));
  },
  review(event) {
    stopTimer();
    setStatus("waiting", "Waiting for approval");
    // Show the finish shockwave in the galaxy first, then the result.
    setTimeout(() => showSheet(event), 1600);
  },
  done(event) {
    stopTimer();
    state.source?.close();
    if (event.outcome === "approve") {
      setStatus("success", event.preview ? "Preview finished" : "Applied");
      showOutcome(true, event);
      galaxy.finish();
    } else {
      setStatus("stopped", "Discarded");
      showOutcome(false, event);
    }
  },
  error(event) {
    stopTimer();
    setStatus("failed", "Error");
    state.source?.close();
    toast(event.message);
  },
};

function handle(event) {
  (handlers[event.type] || (() => {}))(event);
}

// ---------- Result ----------

function openSheet() {
  state.sheetOpen = state.sheetReady = true;
  $("sheetBackdrop").classList.remove("hidden");
  $("sheet").classList.remove("hidden");
}

function hideSheet() {
  state.sheetOpen = false;
  $("statusPill").classList.toggle("clickable", state.sheetReady);
  $("sheet").classList.add("hidden");
  $("sheetBackdrop").classList.add("hidden");
}

function showSheet(event) {
  const passed = event.tests_passed === true;
  openSheet();
  $("sheetActions").classList.remove("hidden");
  $("sheetClose").classList.remove("hidden");
  $("sheetClose").textContent = "Look at the galaxy first";
  $("sheetEyebrow").textContent = passed ? "All tests passed" : "Tests failed";
  $("sheetTitle").textContent = "Ready for approval";
  $("sheetSummary").innerHTML = formatText(event.summary || "The team is done.");
  setRing(passed);

  $("fileChips").innerHTML = event.files.map((f) => `
    <span class="file-chip">${icon("file")}${escapeHtml(f.path)}${f.new ? " · new" : ""}
      <span class="add">+${f.added}</span><span class="del">−${f.removed}</span></span>`).join("")
    || '<span class="muted">No files changed.</span>';
  $("diffView").innerHTML = event.diff.split("\n").map((line) => {
    const cls = line.startsWith("+++") || line.startsWith("---") ? "file"
      : line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
    return `<div class="${cls}">${escapeHtml(line) || " "}</div>`;
  }).join("");
  $("diffView").classList.add("hidden");
  $("diffToggle").classList.remove("hidden");
  $("diffToggle").textContent = "View changes in detail";
  $("feedbackInput").value = "";
  $("feedbackInput").disabled = state.preview;
  $("feedbackButton").disabled = state.preview;
  $("feedbackInput").placeholder = state.preview
    ? "Feedback is not available in the preview"
    : "Feedback for the team, e.g. “Please add type hints”";
}

function setRing(success) {
  const ring = $("ringValue");
  ring.style.stroke = success ? "var(--green)" : "var(--red)";
  ring.style.color = success ? "var(--green)" : "var(--red)";
  ring.style.strokeDashoffset = 327;
  requestAnimationFrame(() => requestAnimationFrame(() => { ring.style.strokeDashoffset = success ? 0 : 245; }));
  $("ringIcon").innerHTML = `<span style="color:${success ? "var(--green)" : "var(--red)"}">${icon(success ? "check" : "x")}</span>`;
}

function showOutcome(approved, event) {
  openSheet();
  $("sheetActions").classList.add("hidden");
  $("diffToggle").classList.add("hidden");
  $("diffView").classList.add("hidden");
  $("sheetClose").classList.remove("hidden");
  $("sheetClose").textContent = "Back to the galaxy";
  setRing(approved);
  $("sheetEyebrow").textContent = event.preview ? "Preview" : "Finished";
  $("sheetTitle").textContent = approved ? "Changes applied" : "Changes discarded";
  $("sheetSummary").textContent = approved
    ? (event.preview ? "Nothing is applied in the preview. In a real run, the changes would now land in the project."
      : `Applied: ${event.files.join(", ") || "no files"}.`)
    : "The project stays unchanged.";
}

async function decide(action) {
  const feedback = $("feedbackInput").value.trim();
  if (action === "feedback" && !feedback) return toast("Please enter feedback first.");
  if (state.sessionId === "preview") {
    handle({ type: "done", outcome: action === "approve" ? "approve" : "reject", files: [], preview: true });
    return;
  }
  try {
    await api(`/api/runs/${state.sessionId}/decision`, { action, feedback });
  } catch (error) {
    toast(error.message);
  }
}

// ---------- Controls ----------

$("approveButton").addEventListener("click", () => decide("approve"));
$("rejectButton").addEventListener("click", () => decide("reject"));
$("feedbackButton").addEventListener("click", () => decide("feedback"));
$("feedbackInput").addEventListener("keydown", (e) => { if (e.key === "Enter") decide("feedback"); });
$("diffToggle").addEventListener("click", () => {
  const hidden = $("diffView").classList.toggle("hidden");
  $("diffToggle").textContent = hidden ? "View changes in detail" : "Hide details";
});
$("sheetClose").addEventListener("click", hideSheet);
$("sheetBackdrop").addEventListener("click", hideSheet);
// The status pill reopens a closed result.
$("statusPill").addEventListener("click", () => {
  if (state.sheetReady && !state.sheetOpen) openSheet();
});
$("newSteps").addEventListener("click", () => {
  const feed = $("feed");
  feed.scrollTo({ top: feed.scrollHeight, behavior: "smooth" });
  clearUnseen();
});
$("feed").addEventListener("scroll", () => {
  const feed = $("feed");
  if (feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40) clearUnseen();
});
$("newRun").addEventListener("click", () => {
  state.source?.close();
  stopPreview();
  stopTimer();
  hideSheet();
  $("runScreen").classList.add("hidden");
  $("runMeta").classList.add("hidden");
  $("startScreen").classList.remove("hidden");
  galaxy.reset();
  galaxy.anchor($("heroGalaxy"));
  galaxy.idle(true);
});
$("previewButton").addEventListener("click", () => openRun("preview"));
initStart().catch(showcaseMode);

// Without a server (e.g. on GitHub Pages) only offer the free, simulated preview
function showcaseMode() {
  document.querySelector(".launch:not(.showcase)").classList.add("hidden");
  $("showcasePanel").classList.remove("hidden");
  $("showcaseButton").addEventListener("click", () => openRun("preview"));
  if (location.hostname.endsWith(".github.io")) {
    const user = location.hostname.split(".")[0], repo = location.pathname.split("/")[1];
    $("repoLink").href = `https://github.com/${user}/${repo}`;
    $("repoLink").classList.remove("hidden");
  }
}
if (new URLSearchParams(location.search).has("preview")) openRun("preview");
