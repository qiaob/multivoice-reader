// ---- tabs ----
const tabButtons = [...document.querySelectorAll('.tabs button')];
function showTab(name) {
  tabButtons.forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === name));
  document.querySelectorAll('main > section').forEach((s) => { s.hidden = s.id !== 'tab-' + name; });
}
tabButtons.forEach((b) => b.addEventListener('click', () => {
  history.replaceState(null, '', '#' + b.dataset.tab);
  showTab(b.dataset.tab);
}));
showTab(location.hash === '#clone' ? 'clone' : 'audition');

// ---- playback ----
const audio = new Audio();
let current = null;
function markLine(clip, on) {
  document.querySelectorAll('.sheet dd').forEach((dd) =>
    dd.classList.toggle('speaking', on && dd.dataset.line === clip));
}
function stop() {
  audio.pause();
  if (current) { current.classList.remove('playing'); markLine(current.dataset.clip, false); }
  current = null;
}
audio.addEventListener('ended', stop);
async function play(btn) {
  const same = btn === current;
  stop();
  if (same) return;
  current = btn; btn.classList.add('playing'); markLine(btn.dataset.clip, true);
  // Load as a blob: Safari refuses to stream audio from servers without Range support.
  const blob = await (await fetch(btn.dataset.src)).blob();
  if (current !== btn) return;
  if (audio.src) URL.revokeObjectURL(audio.src);
  audio.src = URL.createObjectURL(blob); audio.play();
}

// ---- feedback ----
let fb = { general: '', voices: {} };
const statusEl = document.getElementById('status');
const generalEl = document.getElementById('general');
let saveTimer;
const entry = (key) => (fb.voices[key] ??= { use: '', note: '' });
function save() {
  clearTimeout(saveTimer);
  statusEl.textContent = '保存中…';
  saveTimer = setTimeout(async () => {
    try {
      const r = await fetch('/feedback', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fb) });
      if (!r.ok) throw new Error(r.status);
      statusEl.textContent = '反馈已保存 ' + new Date().toLocaleTimeString();
    } catch { statusEl.textContent = '没保存上：页面服务没有响应'; }
  }, 400);
}
function paint(row) {
  const e = fb.voices[row.dataset.voice] || {};
  row.querySelectorAll('.use button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.use === e.use));
  row.classList.toggle('rejected', e.use === '不要');
  const note = row.querySelector('.note');
  if (document.activeElement !== note) note.value = e.note || '';
}
document.addEventListener('click', (e) => {
  const playBtn = e.target.closest('button[data-src]');
  if (playBtn) return play(playBtn);
  const useBtn = e.target.closest('.use button');
  if (!useBtn) return;
  const row = useBtn.closest('[data-voice]');
  const en = entry(row.dataset.voice);
  en.use = en.use === useBtn.dataset.use ? '' : useBtn.dataset.use;
  paint(row); save();
});
document.addEventListener('input', (e) => {
  if (e.target === generalEl) { fb.general = generalEl.value; return save(); }
  if (!e.target.classList.contains('note')) return;
  entry(e.target.closest('[data-voice]').dataset.voice).note = e.target.value;
  save();
});
fetch('/feedback.json', { cache: 'no-store' })
  .then((r) => (r.ok ? r.json() : null))
  .then((d) => {
    if (d) fb = Object.assign({ general: '', voices: {} }, d);
    generalEl.value = fb.general || '';
    document.querySelectorAll('[data-voice]').forEach(paint);
    statusEl.textContent = '你的选择会自动保存';
  })
  .catch(() => { statusEl.textContent = '页面服务没有响应，选择不会保存'; });

// ---- voice cloning: file, microphone or system audio ----
const cloneForm = document.getElementById('clone');
const cloneStatus = document.getElementById('cloneStatus');
const sourceHint = document.getElementById('sourceHint');
const recBtn = document.getElementById('recBtn');
const recInfo = document.getElementById('recInfo');
const recLevel = document.getElementById('recLevel');
const recPreview = document.getElementById('recPreview');
const HINTS = {
  file: `音频或视频文件都行。3 到 ${MAX_REC_SECONDS} 秒的清晰人声最好，超出的部分会被截掉。`,
  mic: `对着麦克风说 5 到 ${MAX_REC_SECONDS} 秒。第一次用时浏览器会询问麦克风权限。`,
  system: '在弹出的窗口里选正在播放声音的标签页或屏幕，并勾选分享音频。需要 Chrome 或 Edge。',
};
const REC_IDLE = '点红色按钮开始录音';
let recorder = null;
let recStream = null;
let recTimer = null;
let recorded = null;
let meterCtx = null;
let meterFrame = 0;

async function openStream(source) {
  if (source === 'mic') return navigator.mediaDevices.getUserMedia({ audio: true });
  // Screen capture is the only browser route to system audio; the video track is ignored.
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: true, systemAudio: 'include',
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  });
  if (!stream.getAudioTracks().length) {
    stream.getTracks().forEach((t) => t.stop());
    throw new Error('没有拿到声音。请在分享窗口里勾选分享音频，并使用 Chrome 或 Edge');
  }
  return stream;
}
function startMeter(stream) {
  meterCtx = new AudioContext();
  const analyser = meterCtx.createAnalyser();
  analyser.fftSize = 512;
  meterCtx.createMediaStreamSource(stream).connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  (function tick() {
    analyser.getFloatTimeDomainData(samples);
    const peak = samples.reduce((max, v) => Math.max(max, Math.abs(v)), 0);
    recLevel.style.width = Math.min(100, peak * 100) + '%';
    meterFrame = requestAnimationFrame(tick);
  })();
}
function releaseRecorder() {
  clearInterval(recTimer);
  cancelAnimationFrame(meterFrame);
  if (meterCtx) meterCtx.close();
  if (recStream) recStream.getTracks().forEach((t) => t.stop());
  meterCtx = null; recStream = null; recorder = null;
  recLevel.style.width = '0';
  recBtn.classList.remove('recording');
  recBtn.setAttribute('aria-label', '开始录音');
}
function discardRecording() {
  if (recorder) { recorder.onstop = null; recorder.stop(); releaseRecorder(); }
  recorded = null;
  if (recPreview.src) URL.revokeObjectURL(recPreview.src);
  recPreview.removeAttribute('src'); recPreview.hidden = true;
  recInfo.textContent = REC_IDLE;
}
function stopRecording() { if (recorder && recorder.state === 'recording') recorder.stop(); }
async function startRecording() {
  discardRecording();
  try {
    recStream = await openStream(cloneForm.elements.source.value);
  } catch (err) {
    recInfo.textContent = '没能开始录音：' + err.message;
    return;
  }
  const audioOnly = new MediaStream(recStream.getAudioTracks());
  const chunks = [];
  recorder = new MediaRecorder(audioOnly);
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.onstop = () => {
    const type = recorder.mimeType;
    recorded = new File(chunks, 'recording.' + (type.includes('mp4') ? 'm4a' : 'webm'), { type });
    releaseRecorder();
    recPreview.src = URL.createObjectURL(recorded); recPreview.hidden = false;
    recInfo.textContent = '录好了。可以先听一遍，不满意就再点红色按钮重录';
  };
  // Fires when sharing is ended from the browser's own controls.
  audioOnly.getAudioTracks()[0].addEventListener('ended', stopRecording);
  recorder.start();
  startMeter(audioOnly);
  const started = Date.now();
  recBtn.classList.add('recording');
  recBtn.setAttribute('aria-label', '停止录音');
  recTimer = setInterval(() => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    recInfo.textContent = `正在录音，${seconds} / ${MAX_REC_SECONDS} 秒。再点一次停止`;
    if (seconds >= MAX_REC_SECONDS) stopRecording();
  }, 200);
}
function showSource() {
  const source = cloneForm.elements.source.value;
  cloneForm.querySelectorAll('[data-for]').forEach((el) => {
    el.hidden = !el.dataset.for.split(' ').includes(source);
  });
  sourceHint.textContent = HINTS[source];
  discardRecording();
}
cloneForm.querySelectorAll('input[name=source]').forEach((r) => r.addEventListener('change', showSource));
recBtn.addEventListener('click', () => (recorder ? stopRecording() : startRecording()));
cloneForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = new FormData(cloneForm);
  const fromFile = data.get('source') === 'file';
  const file = fromFile ? cloneForm.elements.audio.files[0] : recorded;
  cloneStatus.className = 'error';
  if (!file) { cloneStatus.textContent = fromFile ? '还没有选文件' : '还没有录音'; return; }
  const query = new URLSearchParams({ name: data.get('name'), text: data.get('text') });
  const btn = cloneForm.querySelector('button[type=submit]');
  btn.disabled = true;
  cloneStatus.className = '';
  const started = Date.now();
  const progress = setInterval(() => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    cloneStatus.textContent = `正在复刻，已用 ${seconds} 秒。通常一两分钟`;
  }, 1000);
  try {
    const r = await fetch('/clone?' + query, { method: 'POST', body: file, headers: {
      'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) } });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || `页面服务返回 ${r.status}`);
    location.hash = '#clone';
    location.reload();
  } catch (err) {
    cloneStatus.className = 'error';
    cloneStatus.textContent = '复刻没有成功：' + err.message;
    btn.disabled = false;
  } finally {
    clearInterval(progress);
  }
});
showSource();
