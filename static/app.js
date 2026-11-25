'use strict';
// LED Animator web editor
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

let W = 96, H = 32;
const S = {
  frames: [], cur: 0, tool: 'pen', color: [255, 0, 0],
  undo: [], redo: [], playing: null, playingName: null,
};
const PALETTE = ['#ffffff', '#ff0000', '#ff8000', '#ffff00', '#80ff00', '#00ff00', '#00ff80', '#00ffff',
  '#0080ff', '#0000ff', '#8000ff', '#ff00ff', '#ff0080', '#808080', '#402000', '#000000'];

// ---------------------------------------------------------------- utils
function toast(msg, err = false) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
  clearTimeout(t._t); t._t = setTimeout(() => (t.className = ''), 2200);
}
async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.substr(i, 2), 16));
const rgbToHex = (c) => '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');
function b64encode(u8) {
  let s = '';
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
}
function b64decode(str) {
  const s = atob(str), u8 = new Uint8ClampedArray(s.length);
  for (let i = 0; i < s.length; i++) u8[i] = s.charCodeAt(i);
  return u8;
}

// --------------------------------------------------------------- frames
const blankFrame = (duration = 100) => ({ px: new Uint8ClampedArray(W * H * 3), duration });
const cloneFrame = (f) => ({ px: new Uint8ClampedArray(f.px), duration: f.duration });
const frame = () => S.frames[S.cur];
const isBlank = (f) => !f.px.some((v) => v);

function serialize() {
  return { loop: $('#loop').checked, frames: S.frames.map((f) => ({ data: b64encode(f.px), duration: f.duration })) };
}
function loadData(data, name = '') {
  S.frames = data.frames.map((f) => ({ px: b64decode(f.data), duration: f.duration || 100 }));
  if (!S.frames.length) S.frames = [blankFrame()];
  $('#loop').checked = data.loop !== false;
  $('#animName').value = name;
  S.cur = 0; S.undo = []; S.redo = [];
  refreshAll();
}
function addFrames(newFrames) {
  pushUndo(true);
  if (S.frames.length === 1 && isBlank(S.frames[0])) { S.frames = newFrames; S.cur = 0; }
  else { S.cur = S.frames.length; S.frames.push(...newFrames); }
  refreshAll();
}

// ----------------------------------------------------------------- undo
function pushUndo(structural = false) {
  S.undo.push(structural ? { all: S.frames.map(cloneFrame), cur: S.cur }
                         : { idx: S.cur, px: new Uint8ClampedArray(frame().px) });
  if (S.undo.length > 40) S.undo.shift();
  S.redo = [];
}
function swapHistory(from, to) {
  const e = from.pop();
  if (!e) return;
  if (e.all) {
    to.push({ all: S.frames, cur: S.cur });
    S.frames = e.all; S.cur = Math.min(e.cur, S.frames.length - 1);
  } else {
    to.push({ idx: e.idx, px: S.frames[e.idx].px });
    S.frames[e.idx].px = e.px; S.cur = e.idx;
  }
  refreshAll();
}

// ---------------------------------------------------------------- canvas
const view = $('#view'), vctx = view.getContext('2d');
const off = document.createElement('canvas'), octx = off.getContext('2d');
let zoom = 8;

function toImageData(px, transparentBlack) {
  const id = octx.createImageData(W, H), d = id.data;
  for (let i = 0, j = 0; i < px.length; i += 3, j += 4) {
    d[j] = px[i]; d[j + 1] = px[i + 1]; d[j + 2] = px[i + 2];
    d[j + 3] = transparentBlack && !(px[i] | px[i + 1] | px[i + 2]) ? 0 : 255;
  }
  return id;
}
function fit() {
  const avail = $('#canvasWrap').clientWidth - 16;
  zoom = Math.max(2, Math.min(16, Math.floor(avail / W)));
  view.width = W * zoom; view.height = H * zoom;
  render();
}
function render() {
  vctx.imageSmoothingEnabled = false;
  vctx.fillStyle = '#000'; vctx.fillRect(0, 0, view.width, view.height);
  if ($('#onion').checked && S.cur > 0 && !S.playing) {
    octx.putImageData(toImageData(S.frames[S.cur - 1].px, true), 0, 0);
    vctx.globalAlpha = 0.3; vctx.drawImage(off, 0, 0, view.width, view.height); vctx.globalAlpha = 1;
  }
  octx.putImageData(toImageData(frame().px, true), 0, 0);
  vctx.drawImage(off, 0, 0, view.width, view.height);
  if ($('#grid').checked && zoom >= 5) {
    vctx.beginPath(); vctx.strokeStyle = 'rgba(255,255,255,0.07)'; vctx.lineWidth = 1;
    for (let x = 1; x < W; x++) { vctx.moveTo(x * zoom + 0.5, 0); vctx.lineTo(x * zoom + 0.5, view.height); }
    for (let y = 1; y < H; y++) { vctx.moveTo(0, y * zoom + 0.5); vctx.lineTo(view.width, y * zoom + 0.5); }
    vctx.stroke();
  }
  // panel boundaries (every 32 px)
  vctx.beginPath(); vctx.strokeStyle = 'rgba(79,140,255,0.45)';
  for (let x = 32; x < W; x += 32) { vctx.moveTo(x * zoom + 0.5, 0); vctx.lineTo(x * zoom + 0.5, view.height); }
  vctx.stroke();
  updateThumb(S.cur);
  sendLive();
}

// --------------------------------------------------------------- drawing
function setPx(px, x, y, c) {
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  const i = (y * W + x) * 3; px[i] = c[0]; px[i + 1] = c[1]; px[i + 2] = c[2];
}
function getPx(px, x, y) { const i = (y * W + x) * 3; return [px[i], px[i + 1], px[i + 2]]; }
function line(px, x0, y0, x1, y1, c) {
  const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
  let err = dx + dy;
  for (;;) {
    setPx(px, x0, y0, c);
    if (x0 === x1 && y0 === y1) break;
    const e2 = 2 * err;
    if (e2 >= dy) { err += dy; x0 += sx; }
    if (e2 <= dx) { err += dx; y0 += sy; }
  }
}
function rect(px, a, b, c, filled) {
  const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x), y0 = Math.min(a.y, b.y), y1 = Math.max(a.y, b.y);
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++)
    if (filled || x === x0 || x === x1 || y === y0 || y === y1) setPx(px, x, y, c);
}
function flood(px, x, y, c) {
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  const t = getPx(px, x, y);
  if (t[0] === c[0] && t[1] === c[1] && t[2] === c[2]) return;
  const stack = [[x, y]];
  while (stack.length) {
    const [cx, cy] = stack.pop();
    if (cx < 0 || cy < 0 || cx >= W || cy >= H) continue;
    const p = getPx(px, cx, cy);
    if (p[0] !== t[0] || p[1] !== t[1] || p[2] !== t[2]) continue;
    setPx(px, cx, cy, c);
    stack.push([cx + 1, cy], [cx - 1, cy], [cx, cy + 1], [cx, cy - 1]);
  }
}

let drag = null;
function ptOf(e) {
  const r = view.getBoundingClientRect();
  return { x: Math.floor((e.clientX - r.left) / r.width * W), y: Math.floor((e.clientY - r.top) / r.height * H) };
}
view.addEventListener('contextmenu', (e) => e.preventDefault());
view.addEventListener('pointerdown', (e) => {
  if (S.playing) stopPreview();
  const p = ptOf(e);
  const erase = e.button === 2 || S.tool === 'eraser';
  const col = erase ? [0, 0, 0] : S.color;
  if (S.tool === 'picker') {
    if (p.x >= 0 && p.y >= 0 && p.x < W && p.y < H) setColor(getPx(frame().px, p.x, p.y));
    return;
  }
  view.setPointerCapture(e.pointerId);
  pushUndo();
  const tool = e.button === 2 && S.tool !== 'fill' ? 'eraser' : S.tool;
  drag = { tool, start: p, last: p, base: new Uint8ClampedArray(frame().px), col };
  if (tool === 'fill') { flood(frame().px, p.x, p.y, col); drag = null; render(); return; }
  stroke(p);
});
view.addEventListener('pointermove', (e) => { if (drag) stroke(ptOf(e)); });
const endDrag = () => { drag = null; };
view.addEventListener('pointerup', endDrag);
view.addEventListener('pointercancel', endDrag);

function stroke(p) {
  const px = frame().px, d = drag;
  if (d.tool === 'pen' || d.tool === 'eraser') {
    line(px, d.last.x, d.last.y, p.x, p.y, d.col);
  } else {
    px.set(d.base);
    if (d.tool === 'line') line(px, d.start.x, d.start.y, p.x, p.y, d.col);
    else rect(px, d.start, p, d.col, d.tool === 'rectf');
  }
  d.last = p;
  render();
}

function shiftFrame(dx, dy) {
  pushUndo();
  const src = new Uint8ClampedArray(frame().px), px = frame().px;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const sx = (x - dx + W) % W, sy = (y - dy + H) % H;
    const i = (y * W + x) * 3, j = (sy * W + sx) * 3;
    px[i] = src[j]; px[i + 1] = src[j + 1]; px[i + 2] = src[j + 2];
  }
  render();
}

// ------------------------------------------------------------- live mode
let liveTimer = null, liveBusy = false, liveDirty = false;
function sendLive() {
  if (!$('#live').checked) return;
  liveDirty = true;
  if (liveTimer || liveBusy) return;
  liveTimer = setTimeout(async () => {
    liveTimer = null;
    if (!liveDirty) return;
    liveDirty = false; liveBusy = true;
    try { await api('POST', '/api/live', { data: b64encode(frame().px) }); }
    catch (e) { toast('Live: ' + e.message, true); }
    liveBusy = false;
    if (liveDirty) sendLive();
  }, 60);
}

// ------------------------------------------------------------ thumbnails
function buildThumbs() {
  const box = $('#frames'); box.innerHTML = '';
  S.frames.forEach((f, i) => {
    const d = document.createElement('div'); d.className = 'thumb' + (i === S.cur ? ' sel' : '');
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    c.getContext('2d').putImageData(toImageData(f.px, false), 0, 0);
    d.append(c, document.createTextNode(`${i + 1} · ${f.duration}ms`));
    d.onclick = () => select(i);
    box.append(d);
  });
}
function updateThumb(i) {
  const t = $('#frames').children[i];
  if (!t) return;
  t.querySelector('canvas').getContext('2d').putImageData(toImageData(S.frames[i].px, false), 0, 0);
}
function refreshAll() {
  buildThumbs(); updateFrameUi(); render();
}
function updateFrameUi() {
  $('#frameInfo').textContent = `${S.cur + 1} / ${S.frames.length}`;
  $('#frameDur').value = frame().duration;
  $$('#frames .thumb').forEach((t, i) => t.classList.toggle('sel', i === S.cur));
  const sel = $('#frames').children[S.cur];
  if (sel) sel.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}
function select(i) {
  S.cur = Math.max(0, Math.min(S.frames.length - 1, i));
  updateFrameUi(); render();
}

// --------------------------------------------------------------- preview
function startPreview() {
  const startAt = S.cur;
  const tick = () => {
    S.cur = (S.cur + 1) % S.frames.length;
    if (S.cur === 0 && !$('#loop').checked) { stopPreview(); return; }
    updateFrameUi(); render();
    S.playing.t = setTimeout(tick, frame().duration);
  };
  S.playing = { startAt, t: setTimeout(tick, frame().duration) };
  $('#preview').textContent = '■ Stop';
}
function stopPreview() {
  if (!S.playing) return;
  clearTimeout(S.playing.t);
  const back = S.playing.startAt; S.playing = null;
  $('#preview').textContent = '▶ Preview';
  select(Math.min(back, S.frames.length - 1));
}

// ----------------------------------------------------------------- color
function setColor(c) {
  S.color = c; $('#color').value = rgbToHex(c);
}
function buildPalette() {
  const p = $('#palette');
  PALETTE.forEach((h) => {
    const d = document.createElement('div'); d.style.background = h; d.title = h;
    d.onclick = () => setColor(hexToRgb(h));
    p.append(d);
  });
}

// --------------------------------------------------------------- library
async function refreshLibrary() {
  const list = await api('GET', '/api/animations');
  const ul = $('#library'); ul.innerHTML = '';
  if (!list.length) ul.innerHTML = '<li><small>No saved animations yet</small></li>';
  list.forEach((a) => {
    const li = document.createElement('li');
    if (a.name === S.playingName) li.className = 'playing';
    const span = document.createElement('span'); span.textContent = a.name; span.title = a.name;
    const small = document.createElement('small'); small.textContent = a.frames + 'f';
    const mk = (txt, title, fn) => { const b = document.createElement('button'); b.textContent = txt; b.title = title; b.onclick = fn; return b; };
    li.append(span, small,
      mk('✎', 'Load into editor', async () => {
        try { loadData(await api('GET', '/api/animations/' + encodeURIComponent(a.name)), a.name); toast('Loaded ' + a.name); }
        catch (e) { toast(e.message, true); }
      }),
      mk('▶', 'Play on matrix', async () => {
        try { $('#live').checked = false; await api('POST', '/api/play', { name: a.name }); pollStatus(); toast('Playing ' + a.name); }
        catch (e) { toast(e.message, true); }
      }),
      mk('🗑', 'Delete', async () => {
        if (!confirm(`Delete "${a.name}"?`)) return;
        try { await api('DELETE', '/api/animations/' + encodeURIComponent(a.name)); refreshLibrary(); }
        catch (e) { toast(e.message, true); }
      }));
    ul.append(li);
  });
  fillPlaylistSources();
}

// ---------------------------------------------------------------- status
let draggingBrightness = false;
const CAT = { effects: [], views: [] };
function specLabel(sp) {
  const title = (list, id) => (list.find((x) => x.id === id) || {}).title || id;
  switch (sp.type) {
    case 'animation': return `Playing "${sp.name}"`;
    case 'unsaved': return 'Playing unsaved animation';
    case 'effect': return 'Effect: ' + title(CAT.effects, sp.name);
    case 'view': return title(CAT.views, sp.name);
    case 'playlist': return 'Playlist';
    case 'live': return 'Live editing';
    default: return 'Matrix off';
  }
}
async function pollStatus() {
  try {
    const s = await api('GET', '/api/status');
    const sp = s.spec || {};
    $('#statusText').textContent = specLabel(sp) + (s.hardware ? '' : ' · SIMULATOR');
    if (!draggingBrightness) { $('#brightness').value = s.brightness; $('#brightVal').textContent = s.brightness; }
    $$('#effects button').forEach((b) => b.classList.toggle('on', sp.type === 'effect' && sp.name === b.dataset.id));
    $$('#views button').forEach((b) => b.classList.toggle('on', sp.type === 'view' && sp.name === b.dataset.id));
    $('#plPlay').classList.toggle('on', sp.type === 'playlist');
    const playing = sp.type === 'animation' ? sp.name : null;
    if (playing !== S.playingName) { S.playingName = playing; refreshLibrary(); }
    if (!document.hidden) $('#screen').src = '/api/screen.png?t=' + Date.now();
  } catch (e) {
    $('#statusText').textContent = 'offline';
  }
}
async function showOnMatrix(spec) {
  try { $('#live').checked = false; await api('POST', '/api/show', spec); pollStatus(); }
  catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------ effects & views
async function loadCatalog() {
  try { Object.assign(CAT, await api('GET', '/api/catalog')); } catch (e) { return; }
  $('#effectsError').textContent = CAT.effects_error || '';
  const eg = $('#effects'); eg.innerHTML = '';
  const cs = $('#captureEffect'); cs.innerHTML = '';
  CAT.effects.forEach((e) => {
    const b = document.createElement('button'); b.textContent = e.title; b.dataset.id = e.id;
    b.onclick = () => showOnMatrix({ type: 'effect', name: e.id, speed: +$('#effectSpeed').value });
    eg.append(b);
    cs.append(new Option(e.title, e.id));
  });
  const vg = $('#views'); vg.innerHTML = '';
  CAT.views.forEach((v) => {
    const b = document.createElement('button'); b.textContent = v.title; b.dataset.id = v.id;
    b.onclick = () => showOnMatrix({ type: 'view', name: v.id, color: $('#clockColor').value });
    vg.append(b);
  });
  fillPlaylistSources();
}
async function loadWeather() {
  try {
    const w = await api('GET', '/api/weather');
    if (document.activeElement !== $('#city')) $('#city').value = w.city;
    $('#units').value = w.units;
    const d = w.data, loc = w.location;
    let txt;
    if (d) {
      txt = `${loc ? loc.name + (loc.country ? ' (' + loc.country + ')' : '') : w.city}: ${Math.round(d.temp)}°${d.temp_unit}, ` +
        `H ${Math.round(d.max)}° / L ${Math.round(d.min)}°, ${d.humidity}% hum, wind ${Math.round(d.wind)} ${d.wind_unit.toLowerCase()}` +
        ` · updated ${new Date(w.updated * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    } else txt = w.error ? '⚠ ' + w.error : 'Loading weather…';
    $('#weatherInfo').textContent = txt;
    $('#weatherInfo').classList.toggle('err', !d && !!w.error);
  } catch (e) { /* ignore */ }
}

// -------------------------------------------------------------- playlist
let PL = [];
function sourceLabel(it) {
  const f = (list) => (list.find((x) => x.id === it.name) || {}).title || it.name;
  if (it.type === 'effect') return '✨ ' + f(CAT.effects);
  if (it.type === 'view') return '🖥 ' + f(CAT.views);
  return '🎞 ' + it.name;
}
async function fillPlaylistSources() {
  const sel = $('#plSource'), keep = sel.value; sel.innerHTML = '';
  const group = (label, items) => {
    if (!items.length) return;
    const g = document.createElement('optgroup'); g.label = label;
    items.forEach(([val, txt]) => g.append(new Option(txt, val)));
    sel.append(g);
  };
  let anims = [];
  try { anims = await api('GET', '/api/animations'); } catch (e) { /* ignore */ }
  group('Views', CAT.views.map((v) => ['view:' + v.id, v.title]));
  group('Effects', CAT.effects.map((e) => ['effect:' + e.id, e.title]));
  group('Animations', anims.map((a) => ['animation:' + a.name, a.name]));
  if (keep) sel.value = keep;
}
function renderPlaylist() {
  const ul = $('#playlist'); ul.innerHTML = '';
  if (!PL.length) ul.innerHTML = '<li><small class="hint">Empty — add items below</small></li>';
  PL.forEach((it, i) => {
    const li = document.createElement('li');
    const span = document.createElement('span'); span.textContent = sourceLabel(it); span.title = span.textContent;
    const sec = document.createElement('input'); sec.type = 'number'; sec.min = 1; sec.max = 3600; sec.value = it.seconds;
    sec.title = 'seconds'; sec.onchange = () => (it.seconds = Math.max(1, +sec.value || 20));
    const mk = (t, title, fn) => { const b = document.createElement('button'); b.textContent = t; b.title = title; b.onclick = fn; return b; };
    li.append(span, sec,
      mk('↑', 'Move up', () => { if (i) { [PL[i - 1], PL[i]] = [PL[i], PL[i - 1]]; renderPlaylist(); } }),
      mk('✕', 'Remove', () => { PL.splice(i, 1); renderPlaylist(); }));
    ul.append(li);
  });
}
async function loadPlaylist() {
  try { PL = await api('GET', '/api/playlist'); } catch (e) { PL = []; }
  renderPlaylist();
}

// --------------------------------------------------------------- text gen
function textFrames() {
  const text = $('#text').value;
  if (!text) return [];
  const size = +$('#textSize').value || 16;
  const font = `${$('#textBold').checked ? 'bold ' : ''}${size}px ${$('#textFont').value}`;
  const col = hexToRgb($('#textColor').value);
  const m = document.createElement('canvas').getContext('2d');
  m.font = font;
  const tw = Math.ceil(m.measureText(text).width) + 2;
  const c = document.createElement('canvas'); c.width = tw; c.height = H;
  const ctx = c.getContext('2d');
  ctx.font = font; ctx.textBaseline = 'middle'; ctx.fillStyle = '#fff';
  ctx.fillText(text, 1, H / 2 + 1);
  const a = ctx.getImageData(0, 0, tw, H).data;
  const mask = (x, y) => a[(y * tw + x) * 4 + 3] >= 110;
  const stamp = (ox) => {
    const f = blankFrame(+$('#textSpeed').value || 40);
    for (let y = 0; y < H; y++) for (let x = 0; x < tw; x++)
      if (mask(x, y)) setPx(f.px, x + ox, y, col);
    return f;
  };
  if ($('#textMode').value === 'static') {
    const f = stamp(Math.floor((W - tw) / 2)); f.duration = 1000; return [f];
  }
  const out = [];
  for (let ox = W; ox >= -tw; ox--) out.push(stamp(ox));
  return out;
}

// ------------------------------------------------------------------ wire
function wire() {
  $$('#tools button').forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
  $('#color').oninput = (e) => setColor(hexToRgb(e.target.value));
  $('#undo').onclick = () => swapHistory(S.undo, S.redo);
  $('#redo').onclick = () => swapHistory(S.redo, S.undo);
  $('#clearFrame').onclick = () => { pushUndo(); frame().px.fill(0); render(); };
  $$('[data-shift]').forEach((b) => (b.onclick = () => { const [dx, dy] = b.dataset.shift.split(',').map(Number); shiftFrame(dx, dy); }));
  $('#grid').onchange = render;
  $('#onion').onchange = render;
  $('#live').onchange = () => { if ($('#live').checked) sendLive(); };

  $('#prevFrame').onclick = () => select(S.cur - 1);
  $('#nextFrame').onclick = () => select(S.cur + 1);
  $('#addFrame').onclick = () => { pushUndo(true); S.frames.splice(S.cur + 1, 0, blankFrame(frame().duration)); S.cur++; refreshAll(); };
  $('#dupFrame').onclick = () => { pushUndo(true); S.frames.splice(S.cur + 1, 0, cloneFrame(frame())); S.cur++; refreshAll(); };
  $('#delFrame').onclick = () => {
    pushUndo(true);
    if (S.frames.length === 1) S.frames[0] = blankFrame(); else S.frames.splice(S.cur, 1);
    S.cur = Math.min(S.cur, S.frames.length - 1); refreshAll();
  };
  const move = (d) => {
    const j = S.cur + d; if (j < 0 || j >= S.frames.length) return;
    pushUndo(true); [S.frames[S.cur], S.frames[j]] = [S.frames[j], S.frames[S.cur]]; S.cur = j; refreshAll();
  };
  $('#moveLeft').onclick = () => move(-1);
  $('#moveRight').onclick = () => move(1);
  $('#frameDur').onchange = (e) => { frame().duration = Math.max(10, +e.target.value || 100); buildThumbs(); updateFrameUi(); };
  $('#applyFps').onclick = () => {
    const ms = Math.round(1000 / Math.max(1, +$('#fps').value || 10));
    S.frames.forEach((f) => (f.duration = ms)); buildThumbs(); updateFrameUi(); toast(`All frames: ${ms} ms`);
  };
  $('#preview').onclick = () => (S.playing ? stopPreview() : startPreview());

  $('#newAnim').onclick = () => {
    if (!confirm('Start a new animation? Unsaved changes are lost.')) return;
    S.frames = [blankFrame()]; S.cur = 0; S.undo = []; S.redo = []; $('#animName').value = ''; refreshAll();
  };
  $('#save').onclick = async () => {
    const name = $('#animName').value.trim();
    if (!name) { toast('Enter a name first', true); $('#animName').focus(); return; }
    try { const r = await api('PUT', '/api/animations/' + encodeURIComponent(name), serialize()); $('#animName').value = r.name; toast('Saved ' + r.name); refreshLibrary(); }
    catch (e) { toast(e.message, true); }
  };
  $('#playCurrent').onclick = async () => {
    try { $('#live').checked = false; await api('POST', '/api/play', { animation: serialize() }); pollStatus(); toast('Playing on matrix'); }
    catch (e) { toast(e.message, true); }
  };
  $('#exportJson').onclick = () => {
    const blob = new Blob([JSON.stringify({ width: W, height: H, ...serialize() })], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = ($('#animName').value.trim() || 'animation') + '.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  $('#importJson').onchange = async (e) => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (data.width && (data.width !== W || data.height !== H)) throw new Error(`File is ${data.width}x${data.height}, matrix is ${W}x${H}`);
      loadData(data, f.name.replace(/\.json$/i, ''));
    } catch (err) { toast('Import failed: ' + err.message, true); }
  };

  $('#stop').onclick = () => showOnMatrix({ type: 'off' });
  $('#clockColor').onchange = () => {
    const on = document.querySelector('#views button.on');
    if (on) on.click();
  };
  $('#effectSpeed').oninput = () => ($('#speedVal').textContent = (+$('#effectSpeed').value).toFixed(1) + '×');
  $('#effectSpeed').onchange = () => {
    const on = document.querySelector('#effects button.on');
    if (on) on.click();
  };
  $('#capture').onclick = async () => {
    toast('Rendering…');
    try {
      const r = await api('POST', '/api/capture', { type: 'effect', name: $('#captureEffect').value,
        seconds: +$('#captureSec').value || 3, fps: 15, speed: +$('#effectSpeed').value });
      addFrames(r.frames.map((x) => ({ px: b64decode(x.data), duration: x.duration })));
      toast(`Added ${r.frames.length} frames`);
    } catch (e) { toast(e.message, true); }
  };
  $('#setCity').onclick = async () => {
    try {
      await api('POST', '/api/weather', { city: $('#city').value, units: $('#units').value });
      $('#weatherInfo').textContent = 'Loading weather…';
      setTimeout(loadWeather, 1500); setTimeout(loadWeather, 5000);
    } catch (e) { toast(e.message, true); }
  };
  $('#city').onkeydown = (e) => { if (e.key === 'Enter') $('#setCity').click(); };
  $('#units').onchange = () => $('#setCity').click();
  $('#plAdd').onclick = () => {
    const v = $('#plSource').value; if (!v) return;
    const [type, ...rest] = v.split(':');
    const it = { type, name: rest.join(':'), seconds: Math.max(1, +$('#plSec').value || 20) };
    if (type === 'effect') it.speed = +$('#effectSpeed').value;
    PL.push(it); renderPlaylist();
  };
  $('#plPlay').onclick = async () => {
    try { PL = await api('PUT', '/api/playlist', PL); renderPlaylist(); await showOnMatrix({ type: 'playlist' }); toast('Playlist running'); }
    catch (e) { toast(e.message, true); }
  };

  const br = $('#brightness');
  br.oninput = () => { draggingBrightness = true; $('#brightVal').textContent = br.value; };
  br.onchange = async () => { await api('POST', '/api/brightness', { value: +br.value }).catch((e) => toast(e.message, true)); draggingBrightness = false; };

  $('#imageFile').onchange = async (e) => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    const fd = new FormData(); fd.append('file', f); fd.append('fit', $('#fit').value);
    toast('Converting…');
    try {
      const r = await api('POST', '/api/import', fd);
      addFrames(r.frames.map((x) => ({ px: b64decode(x.data), duration: x.duration })));
      toast(`Added ${r.frames.length} frame(s)`);
    } catch (err) { toast(err.message, true); }
  };
  $('#makeText').onclick = () => {
    const fr = textFrames();
    if (!fr.length) { toast('Enter some text', true); return; }
    addFrames(fr); toast(`Added ${fr.length} frame(s)`);
  };

  document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, select, textarea')) return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); swapHistory(e.shiftKey ? S.redo : S.undo, e.shiftKey ? S.undo : S.redo); return; }
    if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); swapHistory(S.redo, S.undo); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const map = { p: 'pen', e: 'eraser', f: 'fill', l: 'line', i: 'picker' };
    if (map[k]) setTool(map[k]);
    else if (k === 'r') setTool(e.shiftKey ? 'rectf' : 'rect');
    else if (k === 'd') $('#dupFrame').click();
    else if (e.key === 'ArrowLeft') select(S.cur - 1);
    else if (e.key === 'ArrowRight') select(S.cur + 1);
    else if (e.key === ' ') { e.preventDefault(); $('#preview').click(); }
    else return;
  });
  window.addEventListener('resize', fit);
  window.addEventListener('beforeunload', (e) => { if (S.undo.length) { e.preventDefault(); e.returnValue = ''; } });
}
function setTool(t) {
  S.tool = t;
  $$('#tools button').forEach((b) => b.classList.toggle('active', b.dataset.tool === t));
}

// ------------------------------------------------------------------ init
(async function init() {
  try {
    const s = await api('GET', '/api/status');
    W = s.width; H = s.height;
  } catch (e) { toast('Server not reachable', true); }
  off.width = W; off.height = H;
  S.frames = [blankFrame()];
  buildPalette(); wire(); fit(); buildThumbs(); updateFrameUi();
  await loadCatalog();
  pollStatus(); refreshLibrary(); loadPlaylist(); loadWeather();
  setInterval(pollStatus, 1500);
  setInterval(loadWeather, 60000);
})();
