// The voice library: listen to every voice, and add, export or remove your own.
// The cloning page loads this too, for the list of your own voices.
const $ = (id) => document.getElementById(id);
const el = (tag, props, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};
function say(text, isError) {
  $('status').textContent = text;
  $('status').className = isError ? 'error' : '';
}
async function api(path, options) {
  const response = await fetch(path, options);
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((data && data.error) || `页面服务返回 ${response.status}`);
  return data;
}

// ---- playback: one clip at a time; pressing the playing one stops it ----
const audio = new Audio();
let current = null;
function stop() {
  audio.pause();
  if (current) current.classList.remove('playing');
  current = null;
}
audio.addEventListener('ended', stop);
async function play(button) {
  const same = button === current;
  stop();
  if (same) return;
  current = button;
  button.classList.add('playing');
  // Load as a blob: Safari refuses to stream audio from servers without Range support.
  const blob = await (await fetch(button.dataset.src)).blob();
  if (current !== button) return;
  if (audio.src) URL.revokeObjectURL(audio.src);
  audio.src = URL.createObjectURL(blob);
  audio.play().catch(stop);
}
const clip = (label, src) => {
  const button = el('button', { type: 'button', className: 'clip', textContent: label });
  button.dataset.src = src;
  return button;
};
document.addEventListener('click', (e) => {
  const button = e.target.closest('button.clip');
  if (button) play(button);
});

// ---- the lists ----
function voiceRow(voice) {
  const id = encodeURIComponent(voice.id);
  const about = [voice.kind === 'narrator' ? '旁白' : '', voice.gender, voice.age].filter((x) => x && x !== '未知');
  const who = el('div', {},
    el('b', { className: 'name', textContent: voice.name }),
    el('span', { className: 'about', textContent: about.join('，') }),
    el('p', { className: 'desc', textContent: voice.desc }));
  const clips = el('div', { className: 'clips' },
    clip('参考录音', `/voice-ref/${id}`),
    ...voice.samples.map((s) => clip(s.label, `/voice-sample/${id}/${s.id}.mp3`)));
  const manage = el('div', { className: 'manage' });
  if (voice.own) {
    const remove = el('button', { type: 'button', textContent: '删除' });
    remove.addEventListener('click', async () => {
      if (!confirm(`删除「${voice.name}」？用了它的角色会回到自动选的声音。`)) return;
      try {
        await api('/api/voices/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: voice.id }) });
        say(`已删除「${voice.name}」`);
        loadVoices();
      } catch (err) { say('没有删掉：' + err.message, true); }
    });
    manage.append(
      el('a', { href: `/api/voices/export?id=${id}`, download: '', textContent: '导出' }), remove);
  }
  return el('li', { className: 'voice' }, who, clips, manage);
}
function fill(listId, countId, voices) {
  if (!$(listId)) return;
  stop();
  $(listId).replaceChildren(...voices.map(voiceRow));
  if ($(countId)) $(countId).textContent = `${voices.length} 个`;
}
async function loadVoices() {
  let data;
  try {
    data = await api('/api/voices');
  } catch (err) {
    say('页面服务没有响应：' + err.message, true);
    return null;
  }
  const mine = data.voices.filter((v) => v.own);
  fill('mineList', 'mineCount', mine);
  fill('builtinList', 'builtinCount', data.voices.filter((v) => !v.own));
  if ($('mineEmpty')) $('mineEmpty').hidden = mine.length > 0;
  if ($('mineList')) $('mineList').hidden = mine.length === 0;
  return data;
}

// ---- adding a voice pack ----
if ($('packFile')) {
  $('packFile').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      const voice = await api('/api/voices/import', { method: 'POST', body: file, headers: {
        'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) } });
      say(`已添加「${voice.name}」`);
      loadVoices();
    } catch (err) { say('没有添加成功：' + err.message, true); }
  });
}

const voicesReady = loadVoices();
