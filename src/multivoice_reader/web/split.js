// The split page: novels in, reading scripts out. Without ?book= it lists every novel and
// lets them queue up to be split; with it, it shows one novel: how far the splitting has got,
// what each chapter was split into, and which characters were found.
const $ = (id) => document.getElementById(id);
const POLL_MS = 1500;
const NARRATOR = '旁白';
const bookId = new URLSearchParams(location.search).get('book');

async function api(path, options) {
  const response = await fetch(path, options);
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((data && data.error) || `页面服务返回 ${response.status}`);
  return data;
}
const post = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const el = (tag, props, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};
function say(where, text, isError, link) {
  where.className = isError ? 'error' : '';
  where.replaceChildren(text, ...(link ? [' ', link] : []));
}
// Which model does the splitting: chosen once, in the header, and sent with every start.
const MODEL_KEY = 'mvr.splitModel';
async function loadModels() {
  let data;
  try { data = await api('/api/split/models'); } catch { return; }
  const saved = localStorage.getItem(MODEL_KEY);
  $('model').replaceChildren(...data.models.map((model) => el('option', { value: model.id, textContent: model.about })));
  $('model').value = data.models.some((model) => model.id === saved) ? saved : data.default;
}
$('model').addEventListener('change', () => localStorage.setItem(MODEL_KEY, $('model').value));
const STATES = {
  running: (book) => (book.now ? `正在拆：${book.now}` : '正在加载模型'),
  waiting: (book) => `排队中，第 ${book.place} 位`,
  done: () => '全部拆完',
  idle: (book) => (book.done ? '已停' : '还没拆'),
  error: (book) => '出错了：' + book.message,
};
async function send(book, where) {
  try {
    const made = await post('/api/split/send', { id: book.id });
    say(where, `《${book.title}》已拆的部分已经送到朗读页。`, false,
      el('a', { href: '/?id=' + encodeURIComponent(made.id), textContent: '去听' }));
  } catch (err) { say(where, err.message, true); }
}

// ---- the list of novels ----
const rows = new Map();    // book id -> the row and the parts of it that change
function makeRow(book) {
  const title = el('td', { className: 'title' },
    el('a', { href: '?book=' + encodeURIComponent(book.id), textContent: book.title }));
  const done = el('td', { className: 'num' });
  const state = el('td', { className: 'state' });
  const until = el('input', { type: 'number', min: 1, max: book.chapters, step: 1,
    value: book.until || book.chapters, ariaLabel: '拆到第几章' });
  const toggle = el('button', { type: 'button', className: 'go' });
  toggle.addEventListener('click', async () => {
    const busy = ['running', 'waiting'].includes(toggle.dataset.state);
    try {
      await post(busy ? '/api/split/stop' : '/api/split/start',
        { id: book.id, until: Number(until.value), model: $('model').value });
      refreshList();
    } catch (err) { say($('shelfStatus'), err.message, true); }
  });
  const exportLink = el('a', { className: 'button', textContent: '导出脚本', download: '',
    href: '/api/split/script?id=' + encodeURIComponent(book.id) });
  const sendButton = el('button', { type: 'button', textContent: '送去朗读' });
  sendButton.addEventListener('click', () => send(book, $('shelfStatus')));
  const remove = el('button', { type: 'button', className: 'remove', textContent: '删除' });
  remove.addEventListener('click', async () => {
    if (!confirm(`删除《${book.title}》和它已经拆好的结果？已经送到朗读页的脚本不受影响。`)) return;
    try { await post('/api/split/remove', { id: book.id }); refreshList(); } catch (err) { say($('shelfStatus'), err.message, true); }
  });
  const row = el('tr', {}, title, done, state, el('td', {}, until),
    el('td', { className: 'acts' }, toggle, exportLink, sendButton, remove));
  return { row, done, state, until, toggle, exportLink, sendButton };
}
function paintRow(parts, book) {
  parts.done.textContent = `${book.done} / ${book.chapters} 章`;
  parts.state.textContent = STATES[book.state](book);
  parts.state.className = 'state' + (book.state === 'error' ? ' error' : book.state === 'running' ? ' busy' : '');
  parts.toggle.dataset.state = book.state;
  parts.toggle.textContent = book.state === 'running' ? '停止' : book.state === 'waiting' ? '取消排队' : '拆分';
  parts.until.disabled = ['running', 'waiting'].includes(book.state);
  parts.exportLink.hidden = parts.sendButton.hidden = book.done === 0;
}
async function refreshList() {
  let data;
  try { data = await api('/api/split/books'); } catch (err) { say($('shelfStatus'), '页面服务没有响应：' + err.message, true); return; }
  const seen = new Set();
  for (const book of data.books) {
    seen.add(book.id);
    if (!rows.has(book.id)) {
      rows.set(book.id, makeRow(book));
      $('bookRows').append(rows.get(book.id).row);
    }
    paintRow(rows.get(book.id), book);
  }
  for (const [id, parts] of rows) if (!seen.has(id)) { parts.row.remove(); rows.delete(id); }
  $('bookTable').hidden = data.books.length === 0;
  $('shelfEmpty').hidden = data.books.length > 0;
  $('status').textContent = data.cloning ? '正在设计或复刻声音，拆分先停一下' : '';
}
$('bookFile').addEventListener('change', async (e) => {
  const files = [...e.target.files];
  e.target.value = '';
  const failed = [];
  for (const [index, file] of files.entries()) {
    say($('shelfStatus'), `正在添加 ${index + 1} / ${files.length}：${file.name}`);
    try {
      await api('/api/split/books', { method: 'POST', body: file, headers: {
        'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) } });
    } catch (err) { failed.push(`${file.name}（${err.message}）`); }
    await refreshList();
  }
  if (failed.length) say($('shelfStatus'), '没有加上：' + failed.join('；'), true);
  else say($('shelfStatus'), `已添加 ${files.length} 本。填好拆到第几章，点「拆分」开始。`);
});

// ---- one novel ----
let book = null;
let chapter = 0;
let shownDone = null;      // whether the chapter on screen was split when it was drawn
let castKey = '';

function paintBook() {
  const done = book.done.filter(Boolean).length;
  const busy = ['running', 'waiting'].includes(book.state);
  document.querySelectorAll('#chapterList button').forEach((button, index) => {
    button.className = book.done[index] ? 'done' : 'todo';
    if (index === chapter) button.setAttribute('aria-current', 'true'); else button.removeAttribute('aria-current');
  });
  $('toggle').textContent = book.state === 'running' ? '停止' : book.state === 'waiting' ? '取消排队' : '拆分';
  $('until').disabled = busy;
  $('progress').textContent = `已拆 ${done} / ${book.chapters.length} 章`;
  $('export').setAttribute('aria-disabled', String(done === 0));
  $('send').disabled = done === 0;
  const text = busy || book.state === 'error' ? STATES[book.state](book) : '';
  if (!$('status').dataset.kept) say($('status'), text, book.state === 'error');
}
async function drawChapter() {
  const asked = chapter;
  let data;
  try { data = await api(`/api/split/chapter?id=${encodeURIComponent(bookId)}&k=${asked}`); } catch (err) { $('pageNote').textContent = err.message; return; }
  if (asked !== chapter) return;
  shownDone = data.lines !== null;
  $('pageNote').textContent = shownDone ? '' : '这一章还没有拆。';
  const paragraphs = [];
  let paragraph = null;
  let lastPara = null;
  for (const line of data.lines || []) {
    if (line.para < 0) continue;  // a chapter title that an older version stored as a line
    if (line.para !== lastPara) { paragraph = el('p', {}); paragraphs.push(paragraph); lastPara = line.para; }
    if (line.speaker !== NARRATOR) {
      const feeling = line.emotion === '中性' ? '' : `（${line.emotion}）`;
      paragraph.append(el('span', { className: 'who', textContent: line.speaker + feeling }),
        el('span', { className: 'seg ready', textContent: line.kind === 'system' ? line.text : `“${line.text}”` }));
    } else {
      paragraph.append(el('span', { className: 'seg ready', textContent: line.text }));
    }
  }
  $('text').replaceChildren(...paragraphs);
}
function openChapter(index) {
  chapter = index;
  shownDone = null;
  $('chapterTitle').textContent = book.chapters[index];
  $('text').replaceChildren();
  $('page').scrollTop = 0;
  const current = document.querySelectorAll('#chapterList button')[index];
  if (current) current.scrollIntoView({ block: 'nearest' });
  paintBook();
  drawChapter();
}
async function drawCharacters() {
  const key = String(book.done.filter(Boolean).length);
  if (key === castKey) return;
  castKey = key;
  let people;
  try { people = await api('/api/split/characters?id=' + encodeURIComponent(bookId)); } catch { castKey = ''; return; }
  $('castList').replaceChildren(...people.map((person) => {
    const about = [person.gender, person.age].filter((x) => x && x !== '未知');
    about.push(`${person.lines} 句`);
    return el('li', {}, el('b', { textContent: person.name }), el('small', { textContent: about.join('，') }));
  }));
}
async function refreshBook() {
  let fresh;
  try { fresh = await api('/api/split/book?id=' + encodeURIComponent(bookId)); } catch (err) {
    if (!book) { location.replace('/split.html'); }
    return;
  }
  const first = book === null;
  book = fresh;
  if (first) {
    $('reader').hidden = $('player').hidden = false;
    document.title = book.title + ' · 拆分 · multivoice-reader';
    $('bookTitle').textContent = book.title;
    $('until').max = book.chapters.length;
    $('until').value = book.until || book.chapters.length;
    $('export').href = '/api/split/script?id=' + encodeURIComponent(bookId);
    $('chapterList').replaceChildren(...book.chapters.map((title, index) => {
      const button = el('button', { type: 'button', textContent: title });
      button.addEventListener('click', () => openChapter(index));
      return el('li', {}, button);
    }));
    const firstTodo = book.done.indexOf(false);
    openChapter(firstTodo > 0 ? firstTodo - 1 : 0);
  }
  paintBook();
  if (shownDone === false && book.done[chapter]) drawChapter();
  drawCharacters();
}
$('toggle').addEventListener('click', async () => {
  delete $('status').dataset.kept;
  const busy = ['running', 'waiting'].includes(book.state);
  try {
    await post(busy ? '/api/split/stop' : '/api/split/start',
      { id: bookId, until: Number($('until').value), model: $('model').value });
    refreshBook();
  } catch (err) { say($('status'), err.message, true); }
});
$('send').addEventListener('click', async () => {
  $('status').dataset.kept = '1';  // keep the link on screen instead of the next progress line
  await send(book, $('status'));
});

// ---- start ----
loadModels();
if (bookId) {
  refreshBook();
  setInterval(refreshBook, POLL_MS);
} else {
  $('shelf').hidden = false;
  refreshList();
  setInterval(refreshList, POLL_MS);
}
