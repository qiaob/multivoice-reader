// The reading page. Without ?id= it lists every script; with it, it is the reader for one:
// shows a chapter, plays its lines in order as their audio becomes ready, and lets the
// listener change which voice a character has.
const $ = (id) => document.getElementById(id);
const POLL_MS = 1500;
const NARRATOR = '旁白';
const audio = new Audio();
const readingId = new URLSearchParams(location.search).get('id');
const withId = 'id=' + encodeURIComponent(readingId || '');

let app = null;            // { reading: the script on this page, voices: the voice library }
let chapter = 0;
let segments = [];
let at = 0;                // index of the current line
let playing = false;       // the listener wants playback
let waiting = false;       // ...but the current line is not ready yet
let playToken = 0;
let castJson = '';

async function api(path, options) {
  const response = await fetch(path, options);
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((data && data.error) || `页面服务返回 ${response.status}`);
  return data;
}
const post = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

// ---- the list of scripts ----
const el = (tag, props, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};
function tell(text, isError) {
  $('shelfStatus').textContent = text;
  $('shelfStatus').className = isError ? 'error' : '';
}
const STATES = {
  speaking: () => '正在合成',
  waiting: (item) => `等着整份合成，第 ${item.place} 位`,
  done: () => '全部合成好了',
  idle: () => '',
  error: (item) => '出错了：' + item.message,
};
const rows = new Map();    // reading id -> the row and the parts of it that change
function makeRow(item) {
  const made = el('td', { className: 'num' });
  const chapters = el('td', { className: 'num' });
  const state = el('td', { className: 'state' });
  const whole = el('button', { type: 'button' });
  whole.addEventListener('click', async () => {
    try {
      await post('/api/readings/whole', { id: item.id, on: whole.dataset.on !== '1' });
      refreshList();
    } catch (err) { tell(err.message, true); }
  });
  const remove = el('button', { type: 'button', className: 'remove', textContent: '删除' });
  remove.addEventListener('click', async () => {
    if (!confirm(`删除「${item.title}」？它的选角和已经合成的音频会一起删掉。`)) return;
    try { await post('/api/readings/remove', { id: item.id }); refreshList(); } catch (err) { tell(err.message, true); }
  });
  const link = '/?id=' + encodeURIComponent(item.id);
  const row = el('tr', {},
    el('td', { className: 'title' }, el('a', { href: link, textContent: item.title })), chapters, made, state,
    el('td', { className: 'acts' }, el('a', { className: 'button', href: link, textContent: '听' }), whole, remove));
  return { row, made, chapters, state, whole };
}
function paintRow(parts, item) {
  parts.chapters.textContent = `${item.chapters} 章`;
  parts.made.textContent = item.made === null ? `… / ${item.lines} 句` : `${item.made} / ${item.lines} 句`;
  parts.state.textContent = STATES[item.state](item);
  parts.state.className = 'state' + (item.state === 'error' ? ' error' : item.state === 'speaking' ? ' busy' : '');
  parts.whole.dataset.on = item.whole ? '1' : '';
  parts.whole.textContent = item.whole ? '不提前合成了' : '整份提前合成';
  parts.whole.hidden = item.state === 'done';
}
async function refreshList() {
  let data;
  try { data = await api('/api/readings'); } catch (err) { tell('页面服务没有响应：' + err.message, true); return; }
  const seen = new Set();
  for (const item of data.readings) {
    seen.add(item.id);
    if (!rows.has(item.id)) {
      rows.set(item.id, makeRow(item));
      $('bookRows').append(rows.get(item.id).row);
    }
    paintRow(rows.get(item.id), item);
  }
  for (const [id, parts] of rows) if (!seen.has(id)) { parts.row.remove(); rows.delete(id); }
  $('bookTable').hidden = data.readings.length === 0;
  $('shelfEmpty').hidden = data.readings.length > 0;
  $('status').textContent = data.cloning ? '正在复刻声音，合成先停一下' : '';
}
$('bookFile').addEventListener('change', async (e) => {
  const files = [...e.target.files];
  e.target.value = '';
  const failed = [];
  for (const [index, file] of files.entries()) {
    tell(`正在添加 ${index + 1} / ${files.length}：${file.name}`);
    try {
      await api('/api/readings', { method: 'POST', body: file, headers: {
        'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) } });
    } catch (err) { failed.push(`${file.name}（${err.message}）`); }
    await refreshList();
  }
  if (failed.length) tell('没有加上：' + failed.join('；'), true);
  else tell(`已添加 ${files.length} 份。`);
});

// ---- the reading view ----
const placeKey = () => 'mvr-place-' + app.reading.id;
function showReader() {
  $('shelf').hidden = true;
  $('reader').hidden = $('player').hidden = false;
  $('bookTitle').textContent = app.reading.title;
  $('chapterList').replaceChildren(...app.reading.chapters.map((title, index) => {
    const button = Object.assign(document.createElement('button'), { type: 'button', textContent: title });
    button.addEventListener('click', () => openChapter(index, 0, playing));
    return Object.assign(document.createElement('li'), {}).appendChild(button).parentNode;
  }));
  const place = JSON.parse(localStorage.getItem(placeKey()) || '{}');
  openChapter(Math.min(place.chapter || 0, app.reading.chapters.length - 1), place.at || 0, false);
}
function openChapter(index, line, keepPlaying) {
  stopAudio();
  chapter = index; at = line; segments = [];
  playing = keepPlaying; waiting = keepPlaying;
  $('chapterTitle').textContent = app.reading.chapters[index];
  $('text').replaceChildren();
  $('page').scrollTop = 0;
  document.querySelectorAll('#chapterList button').forEach((button, i) => {
    if (i === index) { button.setAttribute('aria-current', 'true'); button.scrollIntoView({ block: 'nearest' }); }
    else button.removeAttribute('aria-current');
  });
  tellWorker();
  refresh();
}
function tellWorker() {
  localStorage.setItem(placeKey(), JSON.stringify({ chapter, at }));
  post('/api/target', { id: readingId, chapter, segment: at }).catch(() => {});
}

function renderText() {
  const paragraphs = [];
  let paragraph = null;
  let lastPara = null;
  segments.forEach((segment, index) => {
    if (segment.para < 0) return;  // the chapter title is spoken but shown as the heading
    if (segment.para !== lastPara) { paragraph = document.createElement('p'); paragraphs.push(paragraph); lastPara = segment.para; }
    const span = Object.assign(document.createElement('span'), { className: 'seg' });
    span.dataset.index = index;
    if (segment.speaker !== NARRATOR) {
      const feeling = segment.emotion === '中性' ? '' : `（${segment.emotion}）`;
      paragraph.append(Object.assign(document.createElement('span'), {
        className: 'who', textContent: segment.speaker + feeling }));
      span.textContent = `“${segment.text}”`;
    } else {
      span.textContent = segment.text;
    }
    paragraph.append(span);
  });
  $('text').replaceChildren(...paragraphs);
}
function paintText() {
  document.querySelectorAll('#text .seg').forEach((span) => {
    const index = Number(span.dataset.index);
    span.classList.toggle('ready', Boolean(segments[index].audio));
    span.classList.toggle('now', index === at);
  });
}
$('text').addEventListener('click', (e) => {
  const span = e.target.closest('.seg');
  if (!span) return;
  at = Number(span.dataset.index);
  playing = true;
  tellWorker(); playCurrent();
});

function describe(status) {
  const done = segments.filter((s) => s.audio).length;
  $('ready').textContent = segments.length ? `本章已合成 ${done} / ${segments.length} 句` : '';
  $('where').textContent = segments.length ? `第 ${Math.min(at + 1, segments.length)} 句，共 ${segments.length} 句` : '';
  $('toggle').textContent = playing ? '暂停' : '播放';
  let note = '';
  if (status.state === 'error') note = '后台出错了：' + status.message;
  else if (status.state === 'paused') note = '正在复刻声音，合成先停一下，复刻完自动继续。';
  else if (playing && waiting) note = '这一句还在合成，好了会自动接着读。';
  $('pageNote').textContent = note;
  const states = { speaking: '正在合成', idle: '这几章都准备好了', error: '后台出错了', paused: '合成暂停中' };
  const which = status.chapter === undefined ? '' : `：${app.reading.chapters[status.chapter]}`;
  $('status').textContent = (states[status.state] || '') + (status.chapter === undefined || status.state === 'error' ? '' : which);
  $('status').className = status.state === 'error' ? 'error' : '';
}

async function refresh() {
  if (!app) return;
  const asked = chapter;
  let data;
  try {
    data = await api(`/api/chapter?${withId}&k=${asked}`);
  } catch (err) {
    $('pageNote').textContent = '页面服务没有响应：' + err.message;
    return;
  }
  if (asked !== chapter) return;
  // Re-render only when the script itself changed (first analysis, or a voice was changed).
  const changed = data.segments.length !== segments.length
    || data.segments.some((s, i) => s.text !== segments[i].text || s.speaker !== segments[i].speaker
      || s.emotion !== segments[i].emotion);
  segments = data.segments;
  if (changed) { at = Math.min(at, Math.max(segments.length - 1, 0)); renderText(); }
  paintText();
  describe(data.status);
  if (playing && waiting) playCurrent();
  refreshCast();
}
setInterval(refresh, POLL_MS);

// ---- playback ----
function stopAudio() { playToken++; audio.pause(); }
async function playCurrent() {
  if (at >= segments.length) {
    if (chapter + 1 < app.reading.chapters.length) return openChapter(chapter + 1, 0, true);
    playing = false; return;
  }
  const segment = segments[at];
  paintText();
  const now = document.querySelector('#text .seg.now');
  if (now) now.scrollIntoView({ block: 'center', behavior: 'smooth' });
  if (!segment.audio) { stopAudio(); waiting = true; describe({ state: '' }); return; }
  waiting = false;
  const token = ++playToken;
  // Load as a blob: Safari refuses to stream audio from servers without Range support.
  const blob = await (await fetch(segment.audio)).blob();
  if (token !== playToken) return;
  if (audio.src) URL.revokeObjectURL(audio.src);
  audio.src = URL.createObjectURL(blob);
  audio.playbackRate = Number($('rate').value);
  audio.play().catch(() => {});
  describe({ state: '' });
}
audio.addEventListener('ended', () => { if (playing) step(1); });
function step(by) {
  at = Math.max(0, at + by);
  tellWorker();
  if (playing) playCurrent(); else { paintText(); describe({ state: '' }); }
}
$('toggle').addEventListener('click', () => {
  playing = !playing;
  if (playing) playCurrent(); else { stopAudio(); waiting = false; describe({ state: '' }); }
});
$('prev').addEventListener('click', () => step(-1));
$('next').addEventListener('click', () => step(1));
$('rate').addEventListener('change', () => { audio.playbackRate = Number($('rate').value); });

// ---- casting ----
const preview = new Audio();
let previewing = null;
preview.addEventListener('ended', () => { if (previewing) previewing.classList.remove('playing'); previewing = null; });
function voiceOptions(selected, chosen) {
  const groups = [['内置的声音', (v) => v.kind !== 'clone'], ['我的声音', (v) => v.kind === 'clone']];
  const select = document.createElement('select');
  select.setAttribute('aria-label', '声音');
  if (chosen) select.append(new Option('恢复自动选择', ''));
  for (const [label, test] of groups) {
    const voices = app.voices.filter(test);
    if (!voices.length) continue;
    const group = Object.assign(document.createElement('optgroup'), { label });
    for (const voice of voices) {
      const about = [voice.gender, voice.age].filter((x) => x && x !== '未知').join('，');
      group.append(new Option(about ? `${voice.name}（${about}）` : voice.name, voice.id, false, voice.id === selected));
    }
    select.append(group);
  }
  return select;
}
async function refreshCast() {
  if (document.activeElement && document.activeElement.closest('#castList')) return;  // mid-choice
  let rows;
  try { rows = await api('/api/cast?' + withId); } catch { return; }
  const json = JSON.stringify(rows);
  if (json === castJson) return;
  castJson = json;
  $('castList').replaceChildren(...rows.map((row) => {
    const item = document.createElement('li');
    const about = [row.gender, row.age].filter((x) => x && x !== '未知');
    if (row.lines) about.push(`${row.lines} 句`);
    item.append(Object.assign(document.createElement('b'), { textContent: row.name }),
      Object.assign(document.createElement('small'), { textContent: about.join('，') }));
    const select = voiceOptions(row.voice, row.chosen);
    select.addEventListener('change', async () => {
      await post('/api/cast', { id: readingId, name: row.name, voice: select.value });
      select.blur(); castJson = ''; refresh();
    });
    const listen = Object.assign(document.createElement('button'), { type: 'button', textContent: '试听' });
    listen.addEventListener('click', () => {
      const same = previewing === listen;
      preview.pause();
      if (previewing) previewing.classList.remove('playing');
      previewing = null;
      if (same) return;
      previewing = listen; listen.classList.add('playing');
      preview.src = '/voice-ref/' + encodeURIComponent(select.value || row.voice);
      preview.play().catch(() => {});
    });
    const pick = Object.assign(document.createElement('div'), { className: 'pick' });
    pick.append(select, listen);
    item.append(pick);
    return item;
  }));
}

// ---- start ----
if (readingId) {
  Promise.all([api('/api/reading?' + withId), api('/api/voices')]).then(([reading, library]) => {
    app = { reading, voices: library.voices };
    document.title = reading.title + ' · 朗读 · multivoice-reader';
    showReader();
  }).catch(() => location.replace('/'));
} else {
  $('shelf').hidden = false;
  refreshList();
  setInterval(refreshList, POLL_MS);
}
