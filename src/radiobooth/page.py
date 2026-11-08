"""Booth's page (served by `web`): setup, how Booth is doing, and its settings. On Air colours from the brand
kit; system fonts only, so the page loads nothing from the internet."""

MARK = (
    '<svg viewBox="0 0 120 100" width="44" height="37" aria-hidden="true"><defs><radialGradient id="g">'
    '<stop offset="0" stop-color="#FF5B3A" stop-opacity=".55"/><stop offset="1" stop-color="#FF5B3A"'
    ' stop-opacity="0"/></radialGradient><clipPath id="c"><rect x="11" y="11" width="98" height="78" rx="17"/>'
    '</clipPath></defs><circle class="glow" cx="84" cy="34" r="34" fill="url(#g)" clip-path="url(#c)"/>'
    '<rect x="6" y="6" width="108" height="88" rx="22" fill="none" stroke="#EFEAE1" stroke-width="10"/>'
    '<circle class="lamp" cx="84" cy="34" r="11" fill="#FF5B3A"/></svg>'
)

FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64'"
    " height='64' rx='14' fill='%231C1B1D'/%3E%3Ccircle cx='32' cy='32' r='14' fill='%23FF5B3A'/%3E%3C/svg%3E"
)

STYLE = """
:root {
  --studio: #1C1B1D; --tally: #FF5B3A; --tally-deep: #D63F1F; --brass: #C9A46A; --felt: #3F5A52;
  --chalk: #EFEAE1; --panel: #262428; --line: #3a373c; --muted: #b9b2a6;
  --display: "Young Serif", Georgia, "Times New Roman", serif;
  --text: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --label: "IBM Plex Mono", ui-monospace, "SF Mono", Consolas, monospace;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--studio); color: var(--chalk); font: 16px/1.5 var(--text); }
main { max-width: 640px; margin: 0 auto; padding: 28px 16px 64px; }
header { display: flex; align-items: center; gap: 14px; margin-bottom: 28px; }
header h1 { font: 400 28px/1 var(--display); margin: 0; flex: 1; }
.light { font: 600 12px/1 var(--label); letter-spacing: .14em; text-transform: uppercase; padding: 8px 12px;
  border-radius: 6px; border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
.light.on { color: var(--studio); background: var(--tally); border-color: var(--tally);
  box-shadow: 0 0 18px rgba(255, 91, 58, .55); }
header svg .lamp, header svg .glow { transition: opacity .4s; }
body:not(.on-air) header svg .lamp { opacity: .35; }
body:not(.on-air) header svg .glow { opacity: 0; }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 20px;
  margin-bottom: 16px; }
h2 { font: 400 21px/1.2 var(--display); margin: 0 0 6px; }
.label { font: 12px/1.4 var(--label); letter-spacing: .12em; text-transform: uppercase; color: var(--brass);
  margin: 0 0 10px; }
p { margin: 6px 0; }
.muted { color: var(--muted); font-size: 14px; }
.step { display: flex; gap: 14px; padding: 14px 0; border-top: 1px solid var(--line); }
.step:first-of-type { border-top: 0; padding-top: 4px; }
.num { flex: none; width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--line);
  display: grid; place-items: center; font: 13px var(--label); color: var(--muted); }
.done .num { background: var(--felt); border-color: var(--felt); color: var(--chalk); }
.step > div:not(.num) { flex: 1; min-width: 0; }
#setup-intro { margin-bottom: 12px; }
button { font: 600 15px var(--text); border-radius: 9px; padding: 10px 16px; cursor: pointer;
  border: 1px solid var(--chalk); background: var(--chalk); color: var(--studio); }
button.quiet { background: transparent; color: var(--chalk); border-color: var(--line); }
button:disabled { opacity: .5; cursor: default; }
button + button { margin-left: 8px; }
.actions { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; }
.actions button + button { margin-left: 0; }
input[type=text] { font: 600 18px var(--label); letter-spacing: .12em; text-transform: uppercase;
  padding: 10px 12px; border-radius: 9px; border: 1px solid var(--line); background: var(--studio);
  color: var(--chalk); width: 12em; max-width: 100%; }
input.path { text-transform: none; letter-spacing: 0; font: 15px var(--text); width: 100%; }
.choices { list-style: none; padding: 0; margin: 10px 0 0; }
.choices li + li { margin-top: 8px; }
.choices button { width: 100%; text-align: left; background: var(--studio); color: var(--chalk);
  border-color: var(--line); }
.error { color: #ffb4a3; background: rgba(214, 63, 31, .14); border: 1px solid rgba(255, 91, 58, .4);
  border-radius: 9px; padding: 10px 12px; margin-top: 10px; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; }
.row:not(.hidden) ~ .row:not(.hidden) { border-top: 1px solid var(--line); }
.row > div { min-width: 0; }
.switch { position: relative; width: 46px; height: 26px; flex: none; }
.switch input { opacity: 0; width: 0; height: 0; }
.switch span { position: absolute; inset: 0; border-radius: 13px; background: var(--line); cursor: pointer;
  transition: background .2s; }
.switch span::after { content: ""; position: absolute; width: 20px; height: 20px; left: 3px; top: 3px;
  border-radius: 50%; background: var(--chalk); transition: transform .2s; }
.switch input:checked + span { background: var(--felt); }
.switch input:checked + span::after { transform: translateX(20px); }
.switch input:focus-visible + span { outline: 2px solid var(--brass); outline-offset: 2px; }
details summary { cursor: pointer; color: var(--muted); font-size: 14px; }
pre { font: 12px/1.5 var(--label); white-space: pre-wrap; word-break: break-word; color: var(--muted);
  max-height: 320px; overflow: auto; margin: 10px 0 0; }
.hidden { display: none !important; }
a { color: var(--brass); }
.note { margin: 14px 0 0; padding: 10px 12px; border-radius: 9px; background: rgba(63, 90, 82, .35);
  border: 1px solid var(--felt); font-size: 14px; }
#off { display: none; text-align: center; padding: 36px 20px; }
#off h2 { font-size: 28px; margin-bottom: 10px; }
body.off #off { display: block; }
body.off main > section:not(#off) { display: none; }
body.off .light { color: var(--chalk); border-color: var(--chalk); }
footer { text-align: center; color: var(--muted); font-size: 13px; margin-top: 24px; }
"""

HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Radio Booth</title>
<link rel="icon" href="{FAVICON}">
<style>{STYLE}</style>
<script src="/page.js" defer></script>
</head>
<body>
<main>
  <header>{MARK}<h1>Radio Booth</h1><span class="light" id="light">Off air</span></header>

  <section id="off">
    <p class="label">Booth at home</p>
    <h2 id="off-title">Booth is off</h2>
    <p id="off-text"></p>
  </section>

  <section id="status" class="hidden">
    <p class="label">Booth at home</p>
    <h2 id="status-title"></h2>
    <p id="status-text"></p>
    <p class="muted" id="status-meta"></p>
    <div class="actions" id="status-actions"></div>
    <p class="note" id="keeps-running"></p>
  </section>

  <section id="setup">
    <p class="label">Setup</p>
    <h2 id="setup-title">Let's get Booth ready</h2>
    <p class="muted" id="setup-intro">Booth reads the titles and details of your music in Plex to plan shows,
      and puts each finished show into Plex as a playlist. Your music files never leave this computer.</p>

    <div class="step" id="step-plex">
      <div class="num">1</div>
      <div>
        <h2>Plex</h2>
        <p id="plex-text">Sign in to Plex and allow Radio Booth. Booth never sees your Plex password.</p>
        <div class="actions" id="plex-actions"><button id="plex-go">Sign in to Plex</button></div>
        <p class="muted hidden" id="plex-wait">Waiting for you to finish signing in on the Plex page...
          <a id="plex-link" target="_blank" rel="noopener noreferrer">Open it again</a></p>
        <ul class="choices hidden" id="plex-choices"></ul>
        <div class="hidden" id="plex-folder">
          <p id="folder-hint"></p>
          <input type="text" class="path" id="folder-path" aria-label="Folder">
          <div class="actions"><button id="folder-go">Use this folder</button></div>
        </div>
        <div class="error hidden" id="plex-error"></div>
      </div>
    </div>

    <div class="step" id="step-pair">
      <div class="num">2</div>
      <div>
        <h2>Your Booth account</h2>
        <p id="pair-text">On your phone, open your Booth page and tap <b>Get a pairing code</b>.
          Type the code here.</p>
        <form class="actions" id="pair-form">
          <input type="text" id="pair-code" autocomplete="off" spellcheck="false" aria-label="Pairing code"
            placeholder="Code">
          <button type="submit" id="pair-go">Connect</button>
        </form>
        <div class="error hidden" id="pair-error"></div>
      </div>
    </div>
  </section>

  <section id="settings">
    <p class="label">Settings</p>
    <div class="row" id="row-autostart">
      <div><b>Start when I sign in</b>
        <p class="muted">So shows arrive without opening anything. Recommended.</p></div>
      <label class="switch"><input type="checkbox" id="autostart"><span></span></label>
    </div>
    <div class="row">
      <div><b>Updates</b><p class="muted" id="update-text"></p></div>
      <div class="actions" id="update-actions"></div>
    </div>
    <div class="row" id="row-auto-update">
      <div><b>Update by itself</b>
        <p class="muted">Installs new versions when no show is on its way.</p></div>
      <label class="switch"><input type="checkbox" id="auto-update"><span></span></label>
    </div>
    <div class="row">
      <div><b>Change Booth's setup</b>
        <p class="muted">A different Plex server or music library, or a new pairing.</p></div>
      <button class="quiet" id="change">Change</button>
    </div>
    <div class="row">
      <div><b>Turn Booth off</b>
        <p class="muted" id="quit-text">Until you open Radio Booth again.</p></div>
      <button class="quiet" id="quit">Turn off</button>
    </div>
    <div class="error hidden" id="settings-error"></div>
  </section>

  <section>
    <details><summary>What Booth has been doing</summary><pre id="log"></pre></details>
  </section>

  <footer id="footer"></footer>
</main>
</body>
</html>
"""

LOCKED = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Radio Booth</title><link rel="icon" href="{FAVICON}"><style>{STYLE}</style></head>
<body><main><header>{MARK}<h1>Radio Booth</h1></header><section><h2>Open Booth from your computer</h2>
<p>This page only opens from the Radio Booth app. Open <b>Radio Booth</b> from the Start menu (Windows) or
Applications (Mac), and it brings you back here.</p></section></main></body></html>
"""

SCRIPT = r"""
"use strict";
const $ = (id) => document.getElementById(id);
const show = (el, on) => el.classList.toggle("hidden", !on);
let last = null, changing = false, gone = 0, turningOff = false;

async function post(action, body = {}) {
  const r = await fetch("/api/" + action, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "Booth didn't answer.");
  return data;
}

function ago(t) {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  return new Date(t * 1000).toLocaleDateString();
}

function button(text, onclick, quiet = false) {
  const b = document.createElement("button");
  b.textContent = text;
  if (quiet) b.className = "quiet";
  b.onclick = onclick;
  return b;
}

function error(id, message) {
  $(id).textContent = message || "";
  show($(id), !!message);
}

const STATUS = {
  on_air: ["Booth is on the air", "Ask for a show on your phone. It shows up in Plex as a playlist a few minutes later."],
  starting: ["Booth is starting", "Connecting to your Booth account..."],
  offline: ["Booth can't reach Radio Booth", "Is this computer online? Booth keeps trying by itself."],
  needs_plex: ["Plex needs you to sign in again", "Plex stopped accepting Booth's sign-in. Sign in again below."],
  needs_pairing: ["Connect Booth to your account again", "Your Booth account no longer knows this computer. Get a new pairing code on your phone and type it below."],
  needs_folder: ["Booth can't find the breaks folder", "Is the drive or shared folder connected? Booth keeps checking."],
  stopped: ["Booth is paused", ""],
  not_set_up: ["Booth isn't set up yet", ""],
};

function render(s) {
  last = s;
  const e = s.engine, ready = s.plex.ready && s.account.paired;
  const onAir = e.state === "on_air";
  document.body.classList.toggle("on-air", onAir);
  $("light").textContent = onAir ? (e.busy ? "On air · busy" : "On air") : "Off air";
  $("light").classList.toggle("on", onAir);

  // Status
  show($("status"), ready);
  const [title, text] = STATUS[e.state] || ["Booth", ""];
  $("status-title").textContent = title;
  $("status-text").textContent = text;
  const meta = [];
  if (e.last_checkin) meta.push("Checked in " + ago(e.last_checkin));
  if (e.last_show) meta.push("Last show: " + e.last_show.playlist + ", " + ago(e.last_show.at));
  $("status-meta").textContent = meta.join(" · ");
  const where = s.platform === "win32" ? " from the Start menu" : s.platform === "darwin" ? " from Applications" : "";
  $("keeps-running").textContent = "You can close this page. Booth keeps running in the background; open Radio Booth" +
    where + " to come back here.";
  show($("keeps-running"), e.state !== "stopped");
  const actions = $("status-actions");
  actions.replaceChildren();
  if (["offline", "stopped", "needs_folder"].includes(e.state))
    actions.append(button("Try again now", () => post("restart_engine").then(refresh), true));

  // Setup: shown until done, when something needs fixing, or when asked for
  const needsPlex = !s.plex.ready || e.state === "needs_plex";
  const needsPair = !s.account.paired || e.state === "needs_pairing";
  const st = s.setup, plexBusy = st.step !== "idle" && st.step !== "done";
  show($("setup"), !ready || needsPlex || needsPair || changing || plexBusy);
  $("setup-title").textContent = ready ? "Booth's setup" : "Let's get Booth ready";
  show($("setup-intro"), !ready);

  const plexDone = s.plex.ready && !needsPlex && !plexBusy;
  $("step-plex").classList.toggle("done", plexDone);
  $("plex-text").textContent = plexDone
    ? "Using your music library " + JSON.stringify(s.plex.music) + "."
    : st.step === "working" ? "Looking at your Plex server..."
    : st.step === "server" ? "Which Plex server has your music?"
    : st.step === "library" ? "Which Plex library is your music in?"
    : "Sign in to Plex and allow Radio Booth. Booth never sees your Plex password.";
  $("plex-go").textContent = s.plex.ready ? "Sign in to Plex again" : "Sign in to Plex";
  show($("plex-actions"), st.step === "idle" || st.step === "done");
  show($("plex-go"), !plexDone || changing);
  show($("plex-wait"), st.step === "plex_wait");
  if (st.sign_in_url) $("plex-link").href = st.sign_in_url;
  const choices = $("plex-choices");
  const picking = st.step === "server" || st.step === "library";
  show(choices, picking);
  if (picking && choices.dataset.for !== st.step + st.choices.join("|")) {
    choices.dataset.for = st.step + st.choices.join("|");
    choices.replaceChildren(...st.choices.map((c, i) => {
      const li = document.createElement("li");
      li.append(button(c, () => post("choose", {index: i}).then(refresh).catch((x) => error("plex-error", x.message))));
      return li;
    }));
  }
  show($("plex-folder"), st.step === "folder");
  $("folder-hint").textContent = st.folder_hint;
  if (st.error) error("plex-error", st.error);
  else if (st.step !== "idle") error("plex-error", "");

  const pairDone = s.account.paired && !needsPair;
  $("step-pair").classList.toggle("done", pairDone);
  $("pair-text").textContent = pairDone && !changing
    ? "Connected as " + JSON.stringify(s.account.name) + "."
    : "On your phone, open your Booth page and tap “Get a pairing code”. Type the code here.";
  show($("pair-form"), !pairDone || changing);

  // Settings
  show($("settings"), ready);
  show($("row-autostart"), s.autostart.available);
  $("autostart").checked = s.autostart.on;
  const u = s.update;
  const ua = $("update-actions");
  ua.replaceChildren();
  if (u.state === "installing" || u.state === "installed") $("update-text").textContent = u.message;
  else if (u.available && u.can_install) {
    $("update-text").textContent = "Version " + u.latest + " is ready (you have " + u.current + ").";
    ua.append(button("Update now", () => post("install_update").then(refresh)));
  } else if (u.available) {
    $("update-text").textContent = "Version " + u.latest + " is out (you have " + u.current + "). Update it the way you installed it.";
  } else {
    $("update-text").textContent = (u.state === "failed" ? u.message + " " : "") + "Version " + u.current +
      (u.checked_at ? ", up to date (checked " + ago(u.checked_at) + ")." : ".");
    ua.append(button("Check now", () => post("check_update").then(refresh), true));
  }
  show($("row-auto-update"), u.can_install);
  $("auto-update").checked = u.auto;
  $("quit-text").textContent = s.autostart.on
    ? "Until you open Radio Booth again, or next time you sign in."
    : "Until you open Radio Booth again.";
  $("change").textContent = changing ? "Done" : "Change";

  $("log").textContent = e.log.join("\n") || "Nothing yet.";
  $("footer").textContent = s.restarting ? "Booth is starting again with the new version..." : "Booth " + s.version + " · this page is only on this computer";
}

async function refresh() {
  try {
    const r = await fetch("/api/state", {cache: "no-store"});
    if (r.status === 403) { location.reload(); return; }
    if (turningOff) return;  // Booth is about to stop: don't bring the buttons back meanwhile
    render(await r.json());
    gone = 0;
    document.body.classList.remove("off");
  } catch (x) {
    gone += 1;
    turningOff = false;
    if (gone > 2) showOff();
  }
}

function showOff() {
  // Nothing on the page works while Booth is off, so show only that, and how to turn it on again.
  // The page keeps checking: it comes back by itself when Booth does.
  document.body.classList.add("off");
  document.body.classList.remove("on-air");
  $("light").textContent = "Off air";
  $("light").classList.remove("on");
  const restarting = last && last.restarting;
  const p = last ? last.platform : "";
  const where = p === "win32" ? " from the Start menu" : p === "darwin" ? " from Applications" : "";
  $("off-title").textContent = restarting ? "Booth is updating" : "Booth is off";
  $("off-text").textContent = restarting
    ? "It's starting again with the new version. This page comes back by itself in a moment."
    : "Shows you ask for won't reach Plex until it's on again. To turn it on, open Radio Booth" + where +
      ". This page comes back by itself.";
  $("footer").textContent = "";
}

function wire() {
  $("plex-go").onclick = async () => {
    error("plex-error", "");
    const w = window.open("about:blank", "_blank");  // opened now, while it's a click, so it isn't blocked
    try {
      const {url} = await post("plex");
      if (w) { w.opener = null; w.location = url; } else location.assign(url);
    } catch (x) {
      if (w) w.close();
      error("plex-error", x.message);
    }
    refresh();
  };
  $("folder-go").onclick = () => post("folder", {path: $("folder-path").value}).then(refresh)
    .catch((x) => error("plex-error", x.message));
  $("pair-form").onsubmit = async (ev) => {
    ev.preventDefault();
    error("pair-error", "");
    $("pair-go").disabled = true;
    try {
      await post("pair", {code: $("pair-code").value});
      $("pair-code").value = "";
      changing = false;
    } catch (x) { error("pair-error", x.message); }
    $("pair-go").disabled = false;
    refresh();
  };
  $("autostart").onchange = (ev) => post("autostart", {on: ev.target.checked}).then(refresh)
    .catch((x) => { error("settings-error", x.message); refresh(); });
  $("auto-update").onchange = (ev) => post("auto_update", {on: ev.target.checked}).then(refresh);
  $("change").onclick = () => { changing = !changing; if (!changing) post("cancel"); if (last) render(last); };
  $("quit").onclick = async () => {
    if (!confirm("Turn Booth off? Shows you ask for won't reach Plex until Booth is on again.")) return;
    await post("quit").catch(() => {});
    gone = 3;
    turningOff = true;
    showOff();
  };
}

document.addEventListener("DOMContentLoaded", () => {
  wire();
  refresh();
  setInterval(refresh, 1500);
});
"""
