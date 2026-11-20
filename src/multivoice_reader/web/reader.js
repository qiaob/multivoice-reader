// The reader: shows a chapter, plays its lines in order as their audio becomes ready,
// and lets the listener change which voice a character has.
const $ = (id) => document.getElementById(id);
const POLL_MS = 1500;
const NARRATOR = '旁白';
const audio = new Audio();

let app = null;            // /api/state: the open book, known books, voice library
let chapter = 0;
let segments = [];
let analysed = false;
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

// ---- choosing a book ----
function showShelf() {
  stopAudio();
  $('reader').hidden = $('player').hidden = true;
  $('shelf').hidden = false;
  $('shelfBooks').hidden = !app.books.length;
  $('bookList').replaceChildren(...app.books.map((book) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.append(book.title, Object.assign(document.createElement('span'), { textContent: `${book.chapters} 章` }));
    button.addEventListener('click', () => openBook(() => post('/api/open', { id: book.id })));
    return Object.assign(document.createElement('li'), {}).appendChild(button).parentNode;
  }));
}
async function openBook(request) {
  $('shelfStatus').textContent = '正在打开，长篇小说切章需要几秒…';
  try {
    app = await request();
    $('shelfStatus').textContent = '';
    showReader();
  } catch (err) {
    $('shelfStatus').textContent = '没有打开：' + err.message;
  }
}
$('bookFile').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  openBook(() => api('/api/books?' + new URLSearchParams({ name: file.name }), {
    method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file }));
});
$('changeBook').addEventListener('click', showShelf);

// ---- the reading view ----
const placeKey = () => 'mvr-place-' + app.book.id;
function showReader() {
  $('shelf').hidden = true;
  $('reader').hidden = $('player').hidden = false;
  $('bookTitle').textContent = app.book.title;
  $('chapterList').replaceChildren(...app.book.chapters.map((title, index) => {
    const button = Object.assign(document.createElement('button'), { type: 'button', textContent: title });
    button.addEventListener('click', () => openChapter(index, 0, playing));
    return Object.assign(document.createElement('li'), {}).appendChild(button).parentNode;
  }));
  const place = JSON.parse(localStorage.getItem(placeKey()) || '{}');
  openChapter(Math.min(place.chapter || 0, app.book.chapters.length - 1), place.at || 0, false);
}
function openChapter(index, line, keepPlaying) {
  stopAudio();
  chapter = index; at = line; segments = []; analysed = false;
  playing = keepPlaying; waiting = keepPlaying;
  $('chapterTitle').textContent = app.book.chapters[index];
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
  post('/api/target', { chapter, segment: at }).catch(() => {});
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
    if (segment.kind === 'dialogue') {
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
  $('ready').textContent = analysed ? `本章已合成 ${done} / ${segments.length} 句` : '';
  $('where').textContent = analysed && segments.length ? `第 ${Math.min(at + 1, segments.length)} 句，共 ${segments.length} 句` : '';
  $('toggle').textContent = playing ? '暂停' : '播放';
  let note = '';
  if (status.state === 'error') note = '后台出错了：' + status.message;
  else if (!analysed) note = '正在分析这一章：分出旁白和对白，判断每句话是谁说的。第一次需要一两分钟，包含加载模型的时间。';
  else if (playing && waiting) note = '这一句还在合成，好了会自动接着读。';
  $('pageNote').textContent = note;
  const states = { analysing: '正在分析', speaking: '正在合成', idle: '这几章都准备好了', error: '后台出错了' };
  const which = status.chapter === undefined ? '' : `：${app.book.chapters[status.chapter]}`;
  $('status').textContent = (states[status.state] || '') + (status.state === 'idle' || status.state === 'error' ? '' : which);
  $('status').className = status.state === 'error' ? 'error' : '';
}

async function refresh() {
  if (!app || !app.book || !$('shelf').hidden) return;
  const asked = chapter;
  let data;
  try {
    data = await api(`/api/chapter?k=${asked}`);
  } catch (err) {
    $('pageNote').textContent = '页面服务没有响应：' + err.message;
    return;
  }
  if (asked !== chapter) return;
  // Re-render only when the script itself changed (first analysis, or a voice was changed).
  const changed = data.segments.length !== segments.length
    || data.segments.some((s, i) => s.speaker !== segments[i].speaker || s.emotion !== segments[i].emotion);
  segments = data.segments; analysed = data.analysed;
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
  if (!analysed) { waiting = true; return; }
  if (at >= segments.length) {
    if (chapter + 1 < app.book.chapters.length) return openChapter(chapter + 1, 0, true);
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
  try { rows = await api('/api/cast'); } catch { return; }
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
      await post('/api/cast', { name: row.name, voice: select.value });
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
api('/api/state').then((state) => {
  app = state;
  if (app.book) showReader(); else showShelf();
}).catch((err) => { $('shelf').hidden = false; $('shelfStatus').textContent = '页面服务没有响应：' + err.message; });
