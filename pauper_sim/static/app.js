"use strict";

const MATCH_GAMES_TO_WIN = 2;
const STORAGE_KEY = "pauperDuel_v1";

const state = {
  decks: [],
  matrix: {},
  poolSize: 20,
  fetchedAt: null,
  players: [],
  matches: [],
  bye: null,
  currentMatch: 0,
  scores: {},
  history: {},
};

const $ = (sel) => document.querySelector(sel);

/* ---------- helpers ---------- */

function normalizeDeck(s) {
  return (s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function resolveDeck(raw) {
  const key = normalizeDeck(raw);
  if (!key) return null;
  return state.decks.find((d) => normalizeDeck(d.name) === key)?.name || null;
}

function deckByName(name) {
  return state.decks.find((d) => d.name === name) || null;
}

function winProbability(a, b) {
  const direct = (state.matrix[a] || {})[b];
  const reverse = (state.matrix[b] || {})[a];
  if (direct != null && reverse != null) return (direct + (100 - reverse)) / 2;
  if (direct != null) return direct;
  if (reverse != null) return 100 - reverse;
  const wa = deckByName(a)?.overall_winrate;
  const wb = deckByName(b)?.overall_winrate;
  if (!wa || !wb) return 50;
  return (wa * 100) / (wa + wb);
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/* ---------- localStorage ---------- */

function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      players: state.players,
      matches: state.matches,
      bye: state.bye,
      currentMatch: state.currentMatch,
      scores: state.scores,
      history: state.history,
    }));
  } catch (_) {
    /* storage unavailable — ignore */
  }
}

function restoreState() {
  let raw = null;
  try {
    raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
  } catch (_) {
    raw = null;
  }
  if (!raw) return;
  state.players = raw.players || [];
  state.matches = raw.matches || [];
  state.bye = raw.bye || null;
  state.currentMatch = raw.currentMatch || 0;
  state.scores = raw.scores || {};
  state.history = raw.history || {};
}

function resetTournament() {
  state.players = [];
  state.matches = [];
  state.bye = null;
  state.currentMatch = 0;
  state.scores = {};
  state.history = {};
  saveState();
  renderAll();
}

/* ---------- deck pool ---------- */

async function loadWinrates() {
  showError(null);
  try {
    const res = await fetch("/api/winrates");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    state.decks = data.decks;
    state.matrix = data.matrix;
    state.poolSize = data.pool_size;
    state.fetchedAt = data.fetched_at;
    $("#dataLabel").textContent = `Данные: ${fmtDate(data.fetched_at)}`;
    renderPool();
    renderPlayers();
    renderMatches();
    renderMatch();
    renderSummary();
  } catch (e) {
    showError(`Не удалось загрузить винрейты с mtgdecks.net: ${e.message}`);
  }
}

async function refreshWinrates() {
  const btn = $("#refreshBtn");
  btn.disabled = true;
  btn.textContent = "Обновление…";
  try {
    const res = await fetch("/api/winrates/refresh", { method: "POST" });
    const data = await res.json();
    state.decks = data.decks;
    state.matrix = data.matrix;
    state.fetchedAt = data.fetched_at;
    $("#dataLabel").textContent = `Данные: ${fmtDate(data.fetched_at)}`;
    renderPool();
    renderPlayers();
    renderMatches();
    renderMatch();
  } catch (_) {
    showError("mtgdecks.net сейчас недоступен — показаны сохранённые данные.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Обновить данные";
  }
}

function renderPool() {
  const hint = $("#poolHint");
  hint.textContent = `— топ-${state.poolSize} по числу матчей из ${state.decks.length}`;
  const tbody = $("#decksTable tbody");
  tbody.innerHTML = "";
  state.decks.slice(0, state.poolSize).forEach((deck) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${escapeHtml(deck.name)}</td><td class="num">${deck.overall_winrate.toFixed(1)}%</td><td class="num">${deck.matches.toLocaleString("ru-RU")}</td>`;
    tbody.appendChild(tr);
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- players ---------- */

function parsePlayerList() {
  const text = $("#playersText").value;
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const parsed = [];
  lines.forEach((line) => {
    const m = line.match(/^(.+?)\s*\(([^()]*)\)\s*$/);
    if (m) {
      parsed.push({ name: m[1].trim(), deck: resolveDeck(m[2]) || "" });
    } else {
      parsed.push({ name: line, deck: "" });
    }
  });
  if (parsed.length) state.players = parsed;
  saveState();
  renderPlayers();
}

function addPlayer() {
  state.players.push({ name: `Игрок ${state.players.length + 1}`, deck: "" });
  saveState();
  renderPlayers();
}

function removePlayer(i) {
  state.players.splice(i, 1);
  saveState();
  renderPlayers();
}

function renderPlayers() {
  const tbody = $("#playersTable tbody");
  tbody.innerHTML = "";
  const pool = state.decks.slice(0, state.poolSize);
  state.players.forEach((player, i) => {
    const tr = document.createElement("tr");
    const tdIndex = document.createElement("td");
    tdIndex.className = "num";
    tdIndex.textContent = String(i + 1);
    const tdName = document.createElement("td");
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = player.name;
    nameInput.addEventListener("input", () => {
      player.name = nameInput.value;
      saveState();
    });
    tdName.appendChild(nameInput);

    const tdDeck = document.createElement("td");
    const select = document.createElement("select");
    const options = new Map(pool.map((d) => [d.name, d]));
    if (player.deck) options.set(player.deck, null);
    [...options.entries()].forEach(([deckName, info]) => {
      const opt = document.createElement("option");
      opt.value = deckName;
      opt.textContent = info
        ? `${deckName} (${info.overall_winrate.toFixed(1)}%)`
        : `${deckName}`;
      if (player.deck === deckName) opt.selected = true;
      select.appendChild(opt);
    });
    if (!player.deck) {
      select.classList.add("warn-border");
    }
    select.addEventListener("change", () => {
      player.deck = select.value;
      select.classList.remove("warn-border");
      saveState();
    });
    tdDeck.appendChild(select);

    const tdRm = document.createElement("td");
    tdRm.className = "num";
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "remove-btn";
    rm.textContent = "✕";
    rm.title = "Удалить";
    rm.addEventListener("click", () => removePlayer(i));
    tdRm.appendChild(rm);

    tr.append(tdIndex, tdName, tdDeck, tdRm);
    tbody.appendChild(tr);
  });

  const warn = $("#playersWarn");
  const missing = state.players.filter((p) => !p.deck).length;
  if (missing) {
    warn.hidden = false;
    warn.textContent = `⚠ У ${missing} игрока(ов) не выбрана колода — выберите её из списка.`;
  } else {
    warn.hidden = true;
  }
}

/* ---------- pairings ---------- */

async function startTournament() {
  if (state.players.length < 2) {
    showError("Нужно минимум 2 игрока.");
    return;
  }
  if (state.players.some((p) => !p.deck)) {
    showError("У всех игроков должна быть выбрана колода.");
    return;
  }
  try {
    const res = await fetch("/api/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ players: state.players }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.matches = data.matches;
    state.bye = data.bye;
    state.currentMatch = 0;
    state.scores = {};
    state.history = {};
    saveState();
    renderMatches();
    renderMatch();
    renderSummary();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    showError(`Не удалось провести жеребьёвку: ${e.message}`);
  }
}

function renderMatches() {
  const list = $("#matchesList");
  const bye = $("#byeLine");
  list.innerHTML = "";
  if (!state.matches.length) {
    bye.textContent = "";
    return;
  }
  state.matches.forEach((m, i) => {
    const div = document.createElement("div");
    div.className = "match-item";
    if (i === state.currentMatch) div.classList.add("active");
    const s = state.scores[i] || { a: 0, b: 0 };
    if (matchFinished(i)) div.classList.add("done");
    const p = winProbability(m.a.deck, m.b.deck);
    div.innerHTML =
      `<span class="players-names">${escapeHtml(m.a.name)} vs ${escapeHtml(m.b.name)}</span>` +
      `<span class="mini">${escapeHtml(m.a.deck)} · ${p.toFixed(0)}% против ${escapeHtml(m.b.deck)}</span>` +
      `<span class="status">${s.a}:${s.b}</span>`;
    list.appendChild(div);
  });
  bye.textContent = state.bye ? `Пропускает (bye): ${escapeHtml(state.bye.name)} (${escapeHtml(state.bye.deck)})` : "";
}

/* ---------- match play ---------- */

function matchFinished(i) {
  const s = state.scores[i] || { a: 0, b: 0 };
  return s.a >= MATCH_GAMES_TO_WIN || s.b >= MATCH_GAMES_TO_WIN;
}

function currentMatch() {
  return state.matches[state.currentMatch] || null;
}

async function playGame() {
  const match = currentMatch();
  if (!match || matchFinished(state.currentMatch)) return;
  const btn = $("#playBtn");
  btn.disabled = true;
  try {
    const res = await fetch("/api/roll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ a: match.a.deck, b: match.b.deck }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();
    const i = state.currentMatch;
    const s = (state.scores[i] = state.scores[i] || { a: 0, b: 0 });
    const h = (state.history[i] = state.history[i] || []);
    h.push({ winner: result.winner, deck: result.winner === "a" ? match.a.deck : match.b.deck, pct: result.probability_pct });
    s[result.winner]++;
    saveState();
    renderMatches();
    renderMatch();
  } catch (e) {
    showError(`Не удалось разыграть игру: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

function nextMatch() {
  if (state.currentMatch + 1 >= state.matches.length) return;
  state.currentMatch += 1;
  saveState();
  renderMatches();
  renderMatch();
  renderSummary();
}

function renderMatch() {
  const label = $("#matchLabel");
  const box = $("#matchBox");
  const match = currentMatch();
  if (!match) {
    label.textContent = "";
    box.innerHTML = '<p class="muted">Нажмите «Старт — жеребьёвка пар».</p>';
    return;
  }
  label.textContent = `${state.currentMatch + 1} из ${state.matches.length}`;
  const i = state.currentMatch;
  const s = state.scores[i] || { a: 0, b: 0 };
  const h = state.history[i] || [];
  const done = matchFinished(i);
  const p = winProbability(match.a.deck, match.b.deck);

  const historyHtml = h.map((g, n) =>
    `<span class="game-chip ${g.winner === "a" ? "won-a" : "won-b"}">Игра ${n + 1}: ${g.winner === "a" ? escapeHtml(match.a.name) : escapeHtml(match.b.name)} (${g.pct}%)</span>`
  ).join("");

  const winnerName = done ? (s.a >= MATCH_GAMES_TO_WIN ? match.a.name : match.b.name) : "";
  const nextDisabled = !done || (i + 1 >= state.matches.length);

  box.innerHTML =
    `<div class="match-pair">
       <div class="pair-side">
         <div class="name">${escapeHtml(match.a.name)}</div>
         <div class="deck">${escapeHtml(match.a.deck)}</div>
       </div>
       <div class="pair-vs">VS</div>
       <div class="pair-side">
         <div class="name">${escapeHtml(match.b.name)}</div>
         <div class="deck">${escapeHtml(match.b.deck)}</div>
       </div>
     </div>
     <div class="prob">
       <div class="bar"><div class="a" style="width:${p.toFixed(1)}%"></div><div class="b" style="flex:1"></div></div>
       <div class="percent"><span>${escapeHtml(match.a.name)} ${p.toFixed(1)}%</span><span>${(100 - p).toFixed(1)}% ${escapeHtml(match.b.name)}</span></div>
     </div>
     <div class="score-line">${s.a} : ${s.b}</div>
     <div class="history">${historyHtml || '<span class="muted">Игр ещё не было</span>'}</div>
     <div class="row" style="justify-content:center">
       <button id="playBtn" type="button" class="btn primary big" ${done ? "disabled" : ""}>🎲 Сыграть игру</button>
       <button id="nextBtn" type="button" class="btn big" ${nextDisabled ? "disabled" : ""}>Следующая пара →</button>
     </div>
     ${done ? `<div class="match-done">Победа: ${escapeHtml(winnerName)}</div>` : `<div class="muted" style="text-align:center;margin-top:6px">Играем до ${MATCH_GAMES_TO_WIN} побед</div>`}`;

  $("#playBtn").addEventListener("click", playGame);
  $("#nextBtn").addEventListener("click", nextMatch);
}

/* ---------- summary ---------- */

function renderSummary() {
  const box = $("#summaryBox");
  box.innerHTML = "";
  if (!state.matches.length) {
    box.innerHTML = '<p class="muted">После завершения пар здесь появятся результаты.</p>';
    return;
  }
  const rows = state.matches.map((m, i) => {
    const s = state.scores[i] || { a: 0, b: 0 };
    const done = matchFinished(i);
    if (!done) return null;
    return { name: s.a > s.b ? m.a.name : m.b.name, deck: s.a > s.b ? m.a.deck : m.b.deck, score: `${s.a}:${s.b}` };
  }).filter(Boolean);
  if (state.bye && state.matches.length) {
    rows.push({ name: state.bye.name, deck: state.bye.deck, score: "bye" });
  }
  if (!rows.length) {
    box.innerHTML = '<p class="muted">Пока нет завершённых матчей.</p>';
    return;
  }
  const table = document.createElement("table");
  table.className = "summary-table";
  table.innerHTML = "<thead><tr><th>Победитель</th><th>Колода</th><th class='num'>Счёт</th></tr></thead>";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.deck)}</td><td class="num">${r.score}</td>`;
    table.appendChild(tr);
  });
  box.appendChild(table);
}

/* ---------- ui wiring ---------- */

function showError(msg) {
  const box = $("#errorBox");
  if (msg) {
    box.hidden = false;
    box.textContent = msg;
  } else {
    box.hidden = true;
  }
}

function renderAll() {
  renderPool();
  renderPlayers();
  renderMatches();
  renderMatch();
  renderSummary();
}

$("#parseBtn").addEventListener("click", parsePlayerList);
$("#addBtn").addEventListener("click", addPlayer);
$("#clearBtn").addEventListener("click", () => {
  state.players = [];
  state.matches = [];
  state.bye = null;
  state.currentMatch = 0;
  state.scores = {};
  state.history = {};
  $("#playersText").value = "";
  saveState();
  renderAll();
});
$("#startBtn").addEventListener("click", startTournament);
$("#refreshBtn").addEventListener("click", refreshWinrates);

loadWinrates().then(() => {
  restoreState();
  renderPlayers();
  renderMatches();
  renderMatch();
  renderSummary();
});