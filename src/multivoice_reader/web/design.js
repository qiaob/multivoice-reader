// The design page: describe a voice, hear what the model makes of it, keep the ones you like.
// A voice that is kept joins your own voices and can be chosen on the reading page.
const $ = (id) => document.getElementById(id);
const form = $('design');
const statusLine = $('designStatus');

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
function say(text, isError) {
  statusLine.className = isError ? 'error' : '';
  statusLine.textContent = text;
}

// ---- what has been designed and not kept yet ----
function draftRow(draft) {
  const id = encodeURIComponent(draft.id);
  const about = [draft.gender, draft.age].filter((x) => x && x !== '未知').join('，');
  const name = el('input', { type: 'text', placeholder: '起个名字', ariaLabel: '名字' });
  const keep = el('button', { type: 'button', className: 'secondary', textContent: '收藏' });
  const note = el('span', { className: 'note' });
  keep.addEventListener('click', async () => {
    if (!name.value.trim()) { note.textContent = '先起个名字'; name.focus(); return; }
    try {
      await post('/api/designs/keep', { id: draft.id, name: name.value.trim() });
      say(`「${name.value.trim()}」已收藏，到朗读页的「谁用哪个声音」里就能选它。`);
      loadDrafts();
    } catch (err) { note.textContent = err.message; }
  });
  const again = el('button', { type: 'button', textContent: '用这段描述再做' });
  again.addEventListener('click', () => {
    form.elements.desc.value = draft.desc;
    form.elements.gender.value = draft.gender;
    form.elements.age.value = draft.age;
    form.elements.text.value = draft.text;
    form.elements.desc.focus();
  });
  const remove = el('button', { type: 'button', className: 'drop', textContent: '删除' });
  remove.addEventListener('click', async () => {
    try { await post('/api/designs/remove', { id: draft.id }); loadDrafts(); } catch (err) { note.textContent = err.message; }
  });
  return el('li', { className: 'voice draft' },
    el('div', {},
      el('p', { className: 'desc', textContent: draft.desc + (about ? `（${about}）` : '') }),
      el('audio', { controls: true, preload: 'none', src: `/design-ref/${id}` })),
    el('div', { className: 'keep' }, name, keep, again, remove, note));
}
let shown = '';
async function loadDrafts() {
  let data;
  try { data = await api('/api/designs'); } catch { return; }
  if (!form.elements.text.value) {
    form.elements.text.value = data.sample_text;
    $('textHint').textContent = `它读这段话的录音就是这个声音本身：朗读时会照着录音的音色和语速读。`
      + `${data.text_chars[0]} 到 ${data.text_chars[1]} 个字，可以换成更能体现这个声音的话；语速很慢的声音，话短一些。`;
    for (const [field, values] of [['gender', data.genders], ['age', data.ages]]) {
      form.elements[field].replaceChildren(...values.map((value) => new Option(value, value)));
      form.elements[field].value = '未知';
    }
  }
  const json = JSON.stringify(data.designs);
  if (json === shown) return;  // leave a name that is being typed alone
  shown = json;
  $('draftList').replaceChildren(...data.designs.map(draftRow));
  $('draftCount').textContent = data.designs.length ? `${data.designs.length} 个` : '';
  $('draftEmpty').hidden = data.designs.length > 0;
}

// ---- make one ----
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const fields = form.elements;
  const button = form.querySelector('button[type=submit]');
  button.disabled = true;
  const started = Date.now();
  const tick = () => say(`正在生成，已用 ${Math.round((Date.now() - started) / 1000)} 秒。通常半分钟左右，第一次还要下载模型`);
  tick();
  const timer = setInterval(tick, 1000);
  try {
    await post('/api/design', { desc: fields.desc.value, gender: fields.gender.value, age: fields.age.value, text: fields.text.value });
    say('生成好了，右边第一个就是，可以听一下。不满意就再点一次。');
    await loadDrafts();
  } catch (err) {
    say('没有生成出来：' + err.message, true);
  } finally {
    clearInterval(timer);
    button.disabled = false;
  }
});

loadDrafts();
