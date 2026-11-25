"""Booth's page (served by `web`): setup, how Booth is doing, and its settings. On Air colours from the brand
kit; system fonts only, so the page loads nothing from the internet."""

import json

from radiobooth import LICENSE_URL, __version__

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
#update-actions { flex-shrink: 0; }  /* a long "What's new" beside it mustn't squeeze the button away */
#whats-new ul { margin: 8px 0 0; padding-left: 20px; font-size: 14px; }
#whats-new li { margin: 4px 0; }
pre { font: 12px/1.5 var(--label); white-space: pre-wrap; word-break: break-word; color: var(--muted);
  max-height: 320px; overflow: auto; margin: 10px 0 0; }
.hidden { display: none !important; }
a { color: var(--brass); }
.note { margin: 14px 0 0; padding: 10px 12px; border-radius: 9px; background: rgba(63, 90, 82, .35);
  border: 1px solid var(--felt); font-size: 14px; }
#updated { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
#updated p { margin: 0; }
#off { display: none; text-align: center; padding: 36px 20px; }
#off h2 { font-size: 28px; margin-bottom: 10px; }
body.off #off { display: block; }
body.off main > section:not(#off) { display: none; }
body.off .light { color: var(--chalk); border-color: var(--chalk); }
.people-share { display: grid; gap: 6px; font: 12px/1.3 var(--label); letter-spacing: .1em;
  text-transform: uppercase; color: var(--muted); }
.people-share select { font: 16px/1.4 var(--text); padding: 10px 12px; border-radius: 9px;
  border: 1px solid var(--line); background: var(--studio); color: var(--chalk); width: 100%; min-width: 0;
  text-transform: none; letter-spacing: normal; }
#who-row { margin-bottom: 4px; }
.ok { color: #b9dccf; margin: 0; }
.shows { list-style: none; padding: 0; margin: 14px 0 0; }
.shows li { padding: 10px 0; border-top: 1px solid var(--line); display: grid; gap: 2px; }
.shows .title { font-weight: 600; overflow-wrap: anywhere; }
.shows .st { font-size: 14px; }
.shows .st.delivered { color: #b9dccf; }
.shows .st.failed, .shows .st.expired { color: #ffb4a3; }
.phone-card { display: flex; gap: 20px; align-items: center; }
.phone-card img { flex: none; width: 168px; height: 168px; padding: 10px; border-radius: 12px;
  background: var(--chalk); image-rendering: pixelated; }
.phone-card > div { min-width: 0; }
.phone-card h2 { font-size: 26px; }
a.button { display: inline-block; font: 600 15px var(--text); border-radius: 9px; padding: 10px 16px;
  border: 1px solid var(--chalk); background: var(--chalk); color: var(--studio); text-decoration: none; }
@media (max-width: 520px) { .phone-card { flex-direction: column; align-items: flex-start; } }
footer { text-align: center; color: var(--muted); font-size: 13px; margin-top: 24px; }
#files-form { display: grid; gap: 6px; margin-top: 10px; }
#files-form label { font: 12px/1.3 var(--label); letter-spacing: .1em; text-transform: uppercase;
  color: var(--muted); margin-top: 8px; }
#files-form p { margin: 0; font-size: 14px; }
progress { width: 100%; height: 10px; margin: 10px 0 4px; accent-color: var(--tally); }
#report { white-space: pre-wrap; overflow-wrap: anywhere; }
.show-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.remove { justify-self: start; margin-top: 6px; padding: 6px 12px; font-size: 14px; }
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

  <section id="updated" class="hidden" role="status">
    <p id="updated-text"></p>
    <button type="button" id="updated-go">Refresh</button>
  </section>

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

  <section id="phone" class="hidden">
    <p class="label">New show</p>
    <div class="phone-card">
      <img id="phone-qr" class="hidden" alt="QR code for your Booth page">
      <div>
        <h2>Make a show on your phone</h2>
        <p>Your Booth page is where you ask for shows, hear the DJs, rate a show and flag a break.</p>
        <p id="phone-go"><span id="phone-scan"></span><a id="phone-link" target="_blank" rel="noopener"></a>.</p>
        <div class="actions"><a class="button" id="phone-open" target="_blank" rel="noopener">Open it here</a>
        </div>
      </div>
    </div>
  </section>

  <section id="your-shows" class="hidden">
    <p class="label">Your shows</p>
    <label for="who" class="people-share hidden" id="who-row">Whose shows <select id="who"></select></label>
    <p class="muted" id="shows-text"></p>
    <div class="error hidden" id="shows-error"></div>
    <ul class="shows hidden" id="shows"></ul>
    <p class="muted hidden" id="copy-status"></p>
  </section>

  <section id="setup">
    <p class="label">Setup</p>
    <h2 id="setup-title">Let's get Booth ready</h2>
    <p class="muted" id="setup-intro">Booth reads the titles and details of your music, in Plex or in your
      music files' tags, to plan shows, and makes each finished show a playlist. Your music files stay on
      this computer, unless you ask to download a show on your phone.</p>

    <div class="step" id="step-plex">
      <div class="num">1</div>
      <div>
        <h2>Your music</h2>
        <p id="plex-text">Is your music in Plex, or in a folder of music files?</p>
        <div class="actions" id="plex-actions"><button id="plex-go">It's in Plex</button>
          <button id="files-go">It's in a folder</button></div>
        <form class="hidden" id="files-form">
          <label for="music-path">Your music folder</label>
          <input type="text" class="path" id="music-path" spellcheck="false" autocomplete="off">
          <p class="muted">Copy its path from the address bar of File Explorer, or in Finder hold Option and
            choose Copy as Pathname. Booth reads the tags of the music files in it and its subfolders. It never
            changes, moves or uploads them.</p>
          <label for="shows-path">Folder for your shows</label>
          <input type="text" class="path" id="shows-path" spellcheck="false" autocomplete="off">
          <p class="muted">Each show is a playlist file here, with its DJ breaks beside it. Open it in your
            music player. Booth makes the folder if it isn't there.</p>
          <div class="actions"><button type="submit" id="files-use">Use these folders</button>
            <button type="button" class="quiet" id="files-cancel">Cancel</button></div>
        </form>
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
        <div class="hidden" id="pair-ask">
          <p id="pair-ask-text"></p>
          <div class="actions">
            <button type="button" id="pair-add"></button>
            <button type="button" class="quiet" id="pair-switch"></button>
          </div>
        </div>
        <div class="error hidden" id="pair-error"></div>
      </div>
    </div>
  </section>

  <section id="scan" class="hidden">
    <p class="label">Your music</p>
    <h2 id="scan-title">Reading your music</h2>
    <div class="hidden" id="scan-progress">
      <progress id="scan-bar" max="1" value="0"></progress>
      <p class="muted" id="scan-text"></p>
      <p class="note">The first time takes a while for a big collection. After that, Booth reads only what's
        new or changed. You can close this page: Booth keeps going.</p>
    </div>
    <p id="report-text"></p>
    <details class="hidden" id="report-box"><summary>What Booth found in your tags</summary>
      <pre id="report"></pre></details>
    <div class="actions"><button class="quiet" id="rescan">Read my music again</button></div>
    <div class="error hidden" id="scan-error"></div>
  </section>

  <section id="settings">
    <p class="label">Settings</p>
    <div class="row" id="row-autostart">
      <div><b>Start when I sign in</b>
        <p class="muted">So shows arrive without opening anything. Recommended.</p></div>
      <label class="switch"><input type="checkbox" id="autostart"><span></span></label>
    </div>
    <div class="row">
      <div><b>Updates</b><p class="muted" id="update-text"></p>
        <details class="hidden" id="whats-new"><summary id="whats-new-title"></summary>
          <ul id="whats-new-list"></ul></details></div>
      <div class="actions" id="update-actions"></div>
    </div>
    <div class="row" id="row-auto-update">
      <div><b>Update by itself</b>
        <p class="muted">Installs new versions when no show is on its way.</p></div>
      <label class="switch"><input type="checkbox" id="auto-update"><span></span></label>
    </div>
    <div class="row" id="row-people">
      <div><b>People</b>
        <p class="muted" id="people-text"></p></div>
      <button class="quiet" id="add-person">Add another person</button>
    </div>
    <ul class="shows hidden" id="people"></ul>
    <div class="hidden" id="person-add">
      <p class="muted">Share this Booth with someone who has their own Radio Booth account. On their phone,
        signed in as them, they open their Booth page and tap <b>Get a pairing code</b>. Their shows come from
        this computer's music and go to the same place as yours, with their name at the start of each
        playlist.</p>
      <form class="actions" id="person-form">
        <input type="text" id="person-code" autocomplete="off" spellcheck="false" aria-label="Their pairing code"
          placeholder="Their code">
        <button type="submit" id="person-go">Add</button>
      </form>
    </div>
    <div class="row">
      <div><b>Change Booth's setup</b>
        <p class="muted">Where your music is, or a new pairing.</p></div>
      <button class="quiet" id="change">Change</button>
    </div>
    <div class="row">
      <div><b>Turn Booth off</b>
        <p class="muted" id="quit-text">Until you open Radio Booth again.</p></div>
      <button class="quiet" id="quit">Turn off</button>
    </div>
    <p class="ok hidden" id="settings-ok"></p>
    <div class="error hidden" id="settings-error"></div>
  </section>

  <section>
    <details><summary>What Booth has been doing</summary><pre id="log"></pre></details>
  </section>

  <footer id="footer"><span id="footer-text"></span><a id="terms" href="{LICENSE_URL}" target="_blank"
    rel="noopener">free software, no warranty (GNU GPL)</a></footer>
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
let showsTimer = null, showsWanted = false, showsAsk = 0, phoneShown = null;
const PAGE_VERSION = "__BOOTH_VERSION__";  // the version that served this page
const edited = new Set();  // fields typed in and not yet sent: a reload would lose them
let adding = false, peopleShown = "", plexUsers = null, plexUsersAsked = false, filesOpen = false;
const SHOW_STATUS = {
  queued: "Waiting for Booth", making: "Your DJ is putting it together", ready: "Sending to Plex",
  delivered: "In Plex", failed: "Didn't work", expired: "Expired before Booth could deliver it",
};
const FOLDER_STATUS = {ready: "Saving the playlist", delivered: "In your Booth shows folder"};
// Music in a folder: shows are playlist files in the Booth shows folder, not in Plex.
const inFolder = () => !!(last && last.music && last.music.kind === "folder");
const arrives = () => inFolder() ? "in your Booth shows folder" : "in Plex";

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

// What's new in the version that's out: one line per change, **bold** as in CHANGELOG.md. Built from text
// nodes only, and rebuilt only when the notes change, so an open list stays open between refreshes.
let whatsNewShown = "";
function whatsNew(u) {
  const items = (u && u.notes) || [];
  const key = items.length ? u.latest + "\n" + items.join("\n") : "";
  if (key === whatsNewShown) return;
  whatsNewShown = key;
  show($("whats-new"), items.length > 0);
  if (!items.length) return;
  $("whats-new-title").textContent = "What's new in " + u.latest;
  $("whats-new-list").replaceChildren(...items.map((text) =>
    el("li", {}, ...text.split("**").map((part, i) => (i % 2 ? el("b", {textContent: part}) : part)))));
}

function error(id, message) {
  $(id).textContent = message || "";
  show($(id), !!message);
}

// The New show card: shows are asked for on the phone page (it works in a computer's browser too), so it
// shows that page's QR code and link. Rebuilt only when they change, so a click on the link isn't lost.
function renderPhone(s) {
  const url = /^https?:\/\//.test(s.server) ? s.server.replace(/\/+$/, "") + "/" : "";
  const key = url + "|" + (s.phone_qr || "");
  if (key === phoneShown) return;
  phoneShown = key;
  const qr = $("phone-qr");
  if (s.phone_qr) qr.src = s.phone_qr; else qr.removeAttribute("src");
  show(qr, !!s.phone_qr);
  show($("phone-link"), !!url);
  show($("phone-open"), !!url);
  if (!url) { $("phone-scan").textContent = "On your phone, open your Booth page"; return; }
  $("phone-scan").textContent = s.phone_qr ? "Scan the code with your phone's camera, or open " : "On your phone, open ";
  $("phone-link").href = $("phone-open").href = url;
  $("phone-link").textContent = url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

const STATUS = {
  on_air: ["Booth is on the air", "Shows you ask for on your phone show up {where} as a playlist a few minutes later."],
  starting: ["Booth is starting", "Connecting to your Booth account..."],
  offline: ["Booth can't reach Radio Booth", "Is this computer online? Booth keeps trying by itself."],
  needs_plex: ["Plex needs you to sign in again", "Plex stopped accepting Booth's sign-in. Sign in again below."],
  needs_pairing: ["Connect Booth to your account again", "This computer was removed from your Radio Booth. To use it again, get a new pairing code on your phone and type it below."],
  needs_folder: ["Booth can't find {folder}", "Is the drive or shared folder connected? Booth keeps checking."],
  stopped: ["Booth is paused", ""],
  not_set_up: ["Booth isn't set up yet", ""],
};

function render(s) {
  last = s;
  const e = s.engine, ready = s.music.ready && s.account.paired, files = s.music.kind === "folder";
  const onAir = e.state === "on_air";
  document.body.classList.toggle("on-air", onAir);
  $("light").textContent = onAir ? (e.busy ? "On air · busy" : "On air") : "Off air";
  $("light").classList.toggle("on", onAir);

  // Status
  show($("status"), ready);
  const [title, text] = STATUS[e.state] || ["Booth", ""];
  $("status-title").textContent = title.replace("{folder}", files ? "your music or shows folder" : "the breaks folder");
  $("status-text").textContent = text.replace("{where}", arrives());
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

  // New show (on the phone) and the shows here to copy or remove: once Booth is set up
  const canAsk = ready && e.state !== "needs_pairing";
  show($("phone"), canAsk);
  renderPhone(s);
  show($("your-shows"), canAsk);
  const wantShows = canAsk && e.state !== "stopped";  // paused: no need to keep asking Radio Booth
  if (wantShows && !showsWanted) { showsWanted = true; loadShows(); }
  if (!wantShows) { showsWanted = false; clearTimeout(showsTimer); }

  renderScan(s, files);
  renderCopy(s.copy);

  // Setup: shown until done, when something needs fixing, or when asked for
  const needsPlex = !s.music.ready || (!files && e.state === "needs_plex");
  const needsPair = !s.account.paired || e.state === "needs_pairing";
  const st = s.setup, plexBusy = st.step !== "idle" && st.step !== "done";
  show($("setup"), !ready || needsPlex || needsPair || changing || plexBusy);
  $("setup-title").textContent = ready ? "Booth's setup" : "Let's get Booth ready";
  show($("setup-intro"), !ready);

  const plexDone = s.music.ready && !needsPlex && !plexBusy;
  $("step-plex").classList.toggle("done", plexDone);
  $("plex-text").textContent = filesOpen ? "Where's your music?"
    : plexDone && files ? "Using the music in " + s.music.folder + ". Shows go to " + s.music.shows_folder + "."
    : plexDone ? "Using your Plex music library " + JSON.stringify(s.plex.music) + "."
    : st.step === "working" ? "Looking at your Plex server..."
    : st.step === "server" ? "Which Plex server has your music?"
    : st.step === "library" ? "Which Plex library is your music in?"
    : st.step === "plex_wait" ? "Sign in to Plex and allow Radio Booth. Booth never sees your Plex password."
    : !files && s.plex.ready ? "Plex stopped accepting Booth's sign-in. Sign in again, or use a folder instead."
    : "Is your music in Plex, or in a folder of music files?";
  $("plex-go").textContent = s.music.ready && !files ? "Sign in to Plex again" : s.music.ready ? "Use Plex instead" : "It's in Plex";
  $("files-go").textContent = s.music.ready && files ? "Change folders" : s.music.ready ? "Use a folder instead" : "It's in a folder";
  show($("plex-actions"), (st.step === "idle" || st.step === "done") && !filesOpen);
  show($("plex-go"), !plexDone || changing);
  show($("files-go"), !plexDone || changing);
  show($("files-form"), filesOpen);
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
  show($("pair-form"), (!pairDone || changing) && $("pair-ask").classList.contains("hidden"));

  // People sharing this Booth, and whose shows the list shows
  const people = s.account.people || [];
  const own = s.account.account_name || "You";
  $("people-text").textContent = people.length
    ? "Booth makes shows for " + [own, ...people.map((p) => p.name)].join(", ") + "."
    : "Booth makes shows for " + (s.account.account_name || "your account") + ". Someone else with their own Radio Booth account can use it too.";
  if (people.length && !plexUsersAsked && !files) {  // whom their playlists can be shared with, asked for once
    plexUsersAsked = true;
    fetch("/api/plex_users", {cache: "no-store"}).then((r) => r.json().then((d) => {
      if (!r.ok) throw new Error(d.error || "Booth didn't answer.");
      plexUsers = d.users;
      peopleShown = "";
      if (last) render(last);
    })).catch((x) => {
      error("settings-error", x.message);
      setTimeout(() => { plexUsersAsked = false; }, 30000);  // ask again on a later refresh
    });
  }
  const peopleKey = JSON.stringify([own, people, plexUsers, files]);
  if (peopleKey !== peopleShown) {
    peopleShown = peopleKey;
    const ul = $("people");
    ul.replaceChildren(...people.map((p) => {
      const li = document.createElement("li");
      const t = document.createElement("span");
      t.className = "title";
      t.textContent = p.name;
      const st = document.createElement("span");
      st.className = "st" + (p.unpaired ? " failed" : "");
      st.textContent = p.unpaired ? "This computer was removed from their Radio Booth. Add them again with a new code."
        : "Their playlists start with “" + p.name + ":”" + (files ? "." :
          p.plex_user ? ". New ones are shared with " + p.plex_user.title + " in Plex." : ". They stay in your Plex.");
      const share = document.createElement("label");
      share.className = "people-share";
      share.textContent = "Share their playlists in Plex with";
      const pick = document.createElement("select");
      const users = [...(plexUsers || [])];
      if (p.plex_user && !users.some((u) => u.id === p.plex_user.id))  // not (or not yet) in the list
        users.push({id: p.plex_user.id, title: p.plex_user.title + (plexUsers ? " (no longer in your Plex)" : "")});
      pick.replaceChildren(new Option("Nobody (only in your Plex)", ""),
        ...users.map((u) => new Option(u.title, String(u.id))));
      pick.value = p.plex_user ? String(p.plex_user.id) : "";
      pick.onchange = async () => {
        error("settings-error", "");
        pick.disabled = true;
        try {
          const {said} = await post("person_plex", {id: p.id, user: pick.value || null});
          const before = p.plex_user ? " Playlists already shared with " + p.plex_user.title +
            " stay shared; you can change that in Plex." : "";
          if (said || before) error("settings-error", (said + before).trim());
        } catch (x) { error("settings-error", x.message); }
        pick.disabled = false;
        refresh();
      };
      share.append(pick);
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.append(button("Remove", async () => {
        if (!confirm("Stop making shows for " + p.name + " on this computer?")) return;
        await post("remove_person", {id: p.id}).catch((x) => error("settings-error", x.message));
        refresh();
      }, true));
      li.append(t, st, ...(files ? [] : [share]), actions);
      return li;
    }));
    show(ul, people.length > 0);
    const who = $("who"), picked = who.value;
    who.replaceChildren(new Option(own, ""), ...people.map((p) => new Option(p.name, p.id)));
    who.value = picked;
    if (who.selectedIndex < 0) { who.value = ""; whoChanged(); }
    show($("who-row"), people.length > 0);
  }
  show($("person-add"), adding);
  $("add-person").textContent = adding ? "Cancel" : "Add another person";

  // Settings
  show($("settings"), ready);
  show($("row-autostart"), s.autostart.available);
  $("autostart").checked = s.autostart.on;
  const u = s.update;
  const ua = $("update-actions");
  ua.replaceChildren();
  if (u.state === "installing" || u.state === "installed") $("update-text").textContent = u.message;
  else if (u.available && u.can_install) {
    // A try that failed says why, and the button tries again.
    $("update-text").textContent = (u.state === "failed" ? u.message + " " : "") +
      "Version " + u.latest + " is ready (you have " + u.current + ").";
    ua.append(button(u.state === "failed" ? "Try again" : "Update now", () => post("install_update").then(refresh)));
  } else if (u.available) {
    $("update-text").textContent = "Version " + u.latest + " is out (you have " + u.current + "). Update it the way you installed it.";
  } else {
    $("update-text").textContent = (u.state === "failed" ? u.message + " " : "") + "Version " + u.current +
      (u.checked_at ? ", up to date (checked " + ago(u.checked_at) + ")." : ".");
    ua.append(button("Check now", () => post("check_update").then(refresh), true));
  }
  whatsNew(u.available ? u : null);
  show($("row-auto-update"), u.can_install);
  $("auto-update").checked = u.auto;
  $("quit-text").textContent = s.autostart.on
    ? "Until you open Radio Booth again, or next time you sign in."
    : "Until you open Radio Booth again.";
  $("change").textContent = changing ? "Done" : "Change";

  $("log").textContent = e.log.join("\n") || "Nothing yet.";
  // Only the text changes: the link stays put, so it keeps focus and clicks across refreshes.
  $("footer").classList.remove("hidden");
  $("footer-text").textContent = s.restarting ? "Booth is starting again with the new version..." : "Booth " + s.version + " · this page is only on this computer · ";
  $("terms").classList.toggle("hidden", !!s.restarting);
}

async function refresh() {
  try {
    const r = await fetch("/api/state", {cache: "no-store"});
    if (r.status === 403) { location.reload(); return; }
    if (turningOff) return;  // Booth is about to stop: don't bring the buttons back meanwhile
    const s = await r.json();
    if (s.version !== PAGE_VERSION && newVersion(s.version)) return;
    render(s);
    gone = 0;
    document.body.classList.remove("off");
  } catch (x) {
    gone += 1;
    turningOff = false;
    if (gone > 2) showOff();
  }
}

function unsaved() {
  // Would a reload lose something? Typing, a half-filled field, or a setup step left open.
  const at = document.activeElement;
  if (at && at.matches("textarea, select, input:not([type=checkbox])") && at.id !== "who") return true;
  for (const f of edited) if (f.isConnected && f.value !== "") return true;
  return adding || changing || filesOpen;
}

function newVersion(version) {
  // Booth updated itself: this page is the old one. Reload when that loses nothing, else offer it.
  if (!unsaved()) { location.reload(); return true; }
  $("updated-text").textContent = "Booth updated to " + version + ". Refresh the page to see what's new.";
  show($("updated"), true);
  return false;
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
    : "Shows you ask for wait until it's on again. To turn it on, open Radio Booth" + where +
      ". This page comes back by itself.";
  $("footer").classList.add("hidden");
}

function renderShows(list, listed = true) {
  const ul = $("shows");
  show(ul, list.length > 0);
  $("shows-text").textContent = !listed ? "" : list.length ? "The latest ones. Take one with you, or remove it when you're done."
    : "No shows yet. Ask for one on your phone.";
  ul.replaceChildren(...list.map((s) => {
    const li = document.createElement("li");
    li.dataset.show = s.show_id;
    const t = document.createElement("span");
    t.className = "title";
    t.textContent = s.title || s.prompt;
    const st = document.createElement("span");
    st.className = "st " + s.status;
    const here = inFolder() && !s.for_computer;
    let text = (here && FOLDER_STATUS[s.status]) || SHOW_STATUS[s.status] || s.status;
    if (s.waiting_for_earlier) text = "Up next, after your earlier show";
    if (!s.for_computer && s.status === "delivered" && s.on_disk === false) {
      text = here ? "Removed from your Booth shows folder" : "Removed from Plex";
    }
    else
    if (s.status === "delivered" && s.playlist) text += ": " + s.playlist;
    if (s.status === "failed" && s.error) text += ". " + s.error;
    if (s.for_computer) text += " (made on " + s.for_computer + ")";  // another computer's show
    st.textContent = text;
    const m = document.createElement("span");
    m.className = "muted";
    m.textContent = s.minutes + " min · " + ago(Date.parse(s.created_at) / 1000);
    li.append(t, st, m);
    if (!s.for_computer && s.status === "delivered" && s.on_disk) li.append(el("div", {className: "show-actions"}, copyButton(s, "file"), copyButton(s), removeButton(s)));
    return li;
  }));
  placeCopy();
}

// The copy's progress sits under its own show, or below the list when that show isn't listed.
// Kept by reference: rebuilding the list takes it out of the page while it sits in a show.
let copyShow = null;
const copyStatus = $("copy-status");
function placeCopy() {
  const p = copyStatus;
  const li = copyShow && [...$("shows").children].find((li) => li.dataset.show === copyShow);
  if (li ? p.parentNode !== li || li.lastChild !== p : p.previousElementSibling !== $("shows")) {
    if (li) li.append(p); else $("shows").after(p);
  }
}

const COPY_KINDS = {
  folder: ["Copy to a folder", "Copies the songs and breaks into a folder of their own, numbered in order, to put" +
    " on a phone, a USB stick or a car's drive"],
  file: ["Make one file", "Mixes the show into one MP3, like it sounds on the radio, with a chapter for each song" +
    " and break"],
};

function copyButton(s, kind = "folder") {
  const [textContent, title] = COPY_KINDS[kind];
  const b = el("button", {type: "button", className: "quiet remove", textContent, title});
  b.onclick = async () => {
    b.disabled = true;
    try {
      await post("copy_show", {show_id: s.show_id, kind, title: s.title || ""});
      error("shows-error", "");
      refresh();
    } catch (x) { error("shows-error", x.message); }
    b.disabled = false;
  };
  return b;
}

// A show being copied to a folder or made into one file, or the last one.
function renderCopy(c) {
  const p = copyStatus;
  copyShow = c ? c.show_id : null;
  placeCopy();
  show(p, !!c);
  if (!c) return;
  const missing = (what) => c.missing ? " " + c.missing + (c.missing === 1 ? " file wasn't" : " files weren't") +
    " there to " + what + "." : "";
  if (c.kind === "file") {
    if (!c.finished) {
      p.textContent = "Making the show into one file" + (c.total ? ": " + Math.round(100 * c.done / c.total) + "%..." : "...");
    } else if (c.error) {
      p.textContent = "The file wasn't made: " + c.error;
    } else {
      p.textContent = "Made " + c.file + " (" + c.minutes + " min). Players that read chapters can skip from song to" +
        " song." + missing("use");
    }
  } else if (!c.finished) {
    p.textContent = c.total ? "Copying the show: " + c.done + " of " + c.total + " files..." : "Copying the show...";
  } else if (c.error) {
    p.textContent = "The copy didn't finish: " + c.error;
  } else {
    p.textContent = "Copied to " + c.folder + ". The files are numbered, so they play in order on a phone, a" +
      " USB stick or a car's drive." + missing("copy");
  }
}

function removeButton(s) {
  const b = el("button", {type: "button", className: "quiet remove", textContent: "Remove"});
  b.onclick = async () => {
    const where = inFolder() ? "your Booth shows folder" : "Plex";
    if (!confirm("Remove “" + (s.playlist || s.title) + "” from " + where + "? Its playlist, DJ breaks" +
      " and any copy or one file Booth made of it are deleted. Your music stays where it is.")) return;
    b.disabled = true;
    try {
      await post("remove_show", {show_id: s.show_id, title: s.title || ""});
      error("shows-error", "");
    } catch (x) { error("shows-error", x.message); }
    loadShows();
  };
  return b;
}

// The music folder: how reading it goes, and what Booth found in the tags.
function renderScan(s, files) {
  const scan = s.engine.scan, report = s.engine.report;
  show($("scan"), files && s.music.ready && !!(scan || report));
  if (!files) return;
  show($("scan-progress"), !!scan);
  $("rescan").disabled = !!scan;
  if (scan) {
    $("scan-title").textContent = "Reading your music";
    const bar = $("scan-bar");
    if (scan.total) { bar.max = scan.total; bar.value = scan.done; } else bar.removeAttribute("value");
    const n = (x) => x.toLocaleString();
    const parts = [scan.total ? n(scan.done) + " of " + n(scan.total) + " files" : "Looking through your folders..."];
    if (scan.rate) parts.push(Math.round(scan.rate) + " files a second");
    if (scan.left_s != null && scan.done < scan.total) parts.push("about " + duration(scan.left_s) + " left");
    $("scan-text").textContent = parts.join(" · ");
  } else $("scan-title").textContent = "Your music";
  if (report) {
    const n = (x) => x.toLocaleString();
    $("report-text").textContent = n(report.used) + " tracks ready for shows, from " + n(report.files) +
      " music files (read " + ago(report.at) + ").";
    const text = report.lines.join("\n");
    if ($("report").textContent !== text) $("report").textContent = text;
  }
  show($("report-text"), !!report);
  show($("report-box"), !!report);
}

function duration(seconds) {
  if (seconds < 90) return "a minute";
  if (seconds < 3600) return Math.round(seconds / 60) + " minutes";
  const h = Math.floor(seconds / 3600), m = Math.round((seconds % 3600) / 60);
  return h + " h" + (m ? " " + m + " min" : "");
}

function el(tag, props = {}, ...kids) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...kids);
  return node;
}

async function loadShows() {
  clearTimeout(showsTimer);
  if (!showsWanted || document.hidden) return;  // a hidden tab asks again when it's shown
  let wait = 30000;
  const ask = ++showsAsk;  // only the latest answer counts: an older one arriving late is dropped
  try {
    const who = $("who").value;
    const r = await fetch("/api/shows" + (who ? "?who=" + encodeURIComponent(who) : ""), {cache: "no-store"});
    const data = await r.json().catch(() => ({}));
    if (ask !== showsAsk) return;
    if (!r.ok) throw new Error(data.error || "Booth didn't answer.");
    renderShows(data.shows);
    // Quicker while a show asked for in the last hour is on its way, unless another computer makes it.
    const soon = (s) => ["queued", "making", "ready"].includes(s.status) && !s.for_computer &&
      Date.now() - Date.parse(s.created_at) < 3600000;
    if (data.shows.some(soon)) wait = 5000;
    error("shows-error", "");
  } catch (x) {
    if (ask !== showsAsk) return;
    error("shows-error", x.message);  // keep what's shown, and try again
    wait = 15000;
  }
  if (showsWanted) showsTimer = setTimeout(loadShows, wait);
}

function whoChanged() {
  // Someone else's shows: don't leave the last person's on view meanwhile.
  showsAsk += 1;
  renderShows([], false);
  loadShows();
}

function wire() {
  document.addEventListener("input", (ev) => {
    const f = ev.target;
    if (f.matches("textarea, select, input:not([type=checkbox])") && f.id !== "who") edited.add(f);
  });
  $("updated-go").onclick = () => location.reload();
  $("who").onchange = whoChanged;
  $("add-person").onclick = () => {
    adding = !adding;
    error("settings-error", "");
    show($("settings-ok"), false);
    if (last) render(last);
  };
  $("person-form").onsubmit = async (ev) => {
    ev.preventDefault();
    error("settings-error", "");
    $("person-go").disabled = true;
    try {
      const {name} = await post("add_person", {code: $("person-code").value});
      $("person-code").value = "";
      adding = false;
      $("settings-ok").textContent = "Booth makes shows for " + name + " too now.";
      show($("settings-ok"), true);
      setTimeout(() => show($("settings-ok"), false), 10000);
    } catch (x) { error("settings-error", x.message); }
    $("person-go").disabled = false;
    refresh();
  };
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
  $("files-go").onclick = () => {
    filesOpen = true;
    error("plex-error", "");
    const m = last ? last.music : {};
    if (!$("music-path").value) $("music-path").value = m.folder || m.suggest.music || "";
    if (!$("shows-path").value) $("shows-path").value = m.shows_folder || m.suggest.shows || "";
    if (last) render(last);
    $("music-path").focus();
  };
  $("files-cancel").onclick = () => {
    filesOpen = false;
    for (const id of ["music-path", "shows-path"]) { $(id).value = ""; edited.delete($(id)); }
    error("plex-error", "");
    if (last) render(last);
  };
  $("files-form").onsubmit = async (ev) => {
    ev.preventDefault();
    error("plex-error", "");
    $("files-use").disabled = true;
    try {
      await post("music_folder", {music: $("music-path").value, shows: $("shows-path").value});
      filesOpen = false;
      for (const id of ["music-path", "shows-path"]) edited.delete($(id));
    } catch (x) { error("plex-error", x.message); }
    $("files-use").disabled = false;
    refresh();
  };
  $("rescan").onclick = () => post("rescan").then(() => error("scan-error", ""))
    .catch((x) => error("scan-error", x.message)).then(refresh);
  $("folder-go").onclick = () => post("folder", {path: $("folder-path").value})
    .then(() => { edited.delete($("folder-path")); refresh(); }).catch((x) => error("plex-error", x.message));
  $("pair-form").onsubmit = async (ev) => {
    ev.preventDefault();
    error("pair-error", "");
    $("pair-go").disabled = true;
    try {
      const r = await post("pair", {code: $("pair-code").value});
      $("pair-code").value = "";
      if (r.ask) {  // another person's code, and this computer still makes shows for someone: ask which
        $("pair-ask-text").textContent = "That code is from " + r.ask.theirs + "’s account. Booth makes shows"
          + " for " + r.ask.own + " here now. Add " + r.ask.theirs + " as another person, or switch this"
          + " computer to " + r.ask.theirs + "’s account? (Switching stops " + r.ask.own + "’s shows here.)";
        $("pair-add").textContent = "Add " + r.ask.theirs + " too";
        $("pair-switch").textContent = "Switch to " + r.ask.theirs;
        show($("pair-form"), false);
        show($("pair-ask"), true);
      } else paired();
    } catch (x) { error("pair-error", x.message); }
    $("pair-go").disabled = false;
    refresh();
  };
  function paired() {
    changing = false;
    renderShows([], false);  // maybe another account now: don't show the last one's shows meanwhile
    loadShows();
  }
  const pairChoice = (choice) => async () => {
    error("pair-error", "");
    $("pair-add").disabled = $("pair-switch").disabled = true;
    try {
      const r = await post("pair_choice", {choice});
      if (r.added) changing = false;
      else paired();
    } catch (x) { error("pair-error", x.message); }
    show($("pair-ask"), false);
    $("pair-add").disabled = $("pair-switch").disabled = false;
    refresh();
  };
  $("pair-add").onclick = pairChoice("add");
  $("pair-switch").onclick = pairChoice("switch");
  $("autostart").onchange = (ev) => post("autostart", {on: ev.target.checked}).then(refresh)
    .catch((x) => { error("settings-error", x.message); refresh(); });
  $("auto-update").onchange = (ev) => post("auto_update", {on: ev.target.checked}).then(refresh);
  $("change").onclick = () => {
    changing = !changing;
    show($("pair-ask"), false);  // a question about someone's code, left unanswered: the code is spent
    if (!changing) { post("cancel"); filesOpen = false; }
    if (last) render(last);
  };
  $("quit").onclick = async () => {
    if (!confirm("Turn Booth off? Shows you ask for wait until Booth is on again.")) return;
    await post("quit").catch(() => {});
    gone = 3;
    turningOff = true;
    showOff();
  };
}

document.addEventListener("visibilitychange", () => { if (!document.hidden) loadShows(); });

document.addEventListener("DOMContentLoaded", () => {
  wire();
  refresh();
  setInterval(refresh, 1500);
});
""".replace('"__BOOTH_VERSION__"', json.dumps(__version__)).replace("__LICENSE_URL__", LICENSE_URL)
