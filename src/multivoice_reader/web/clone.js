// Cloning a voice from a file, the microphone or the system's audio. Needs voices.js.
const cloneForm = $('clone');
const cloneStatus = $('cloneStatus');
const recBtn = $('recBtn');
const recInfo = $('recInfo');
const recLevel = $('recLevel');
const recPreview = $('recPreview');
const REC_IDLE = '点红色按钮开始录音';
let maxSeconds = 20;       // the server says how long a reference may be
let recorder = null;
let recStream = null;
let recTimer = null;
let recorded = null;
let meterCtx = null;
let meterFrame = 0;

const hints = () => ({
  file: `音频或视频文件都行。3 到 ${maxSeconds} 秒的清晰人声最好，超出的部分会被截掉。`,
  mic: `对着麦克风说 5 到 ${maxSeconds} 秒。第一次用时浏览器会询问麦克风权限。`,
  system: '在弹出的窗口里选正在播放声音的标签页或屏幕，并勾选分享音频。需要 Chrome 或 Edge。',
});

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
    recInfo.textContent = `正在录音，${seconds} / ${maxSeconds} 秒。再点一次停止`;
    if (seconds >= maxSeconds) stopRecording();
  }, 200);
}
function showSource() {
  const source = cloneForm.elements.source.value;
  cloneForm.querySelectorAll('[data-for]').forEach((part) => {
    part.hidden = !part.dataset.for.split(' ').includes(source);
  });
  $('sourceHint').textContent = hints()[source];
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
  const name = data.get('name').trim();
  const query = new URLSearchParams({ name, text: data.get('text') });
  const button = cloneForm.querySelector('button[type=submit]');
  button.disabled = true;
  cloneStatus.className = '';
  const started = Date.now();
  const progress = setInterval(() => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    cloneStatus.textContent = `正在复刻，已用 ${seconds} 秒。通常两三分钟，第一次还要下载模型`;
  }, 1000);
  try {
    await api('/api/clone?' + query, { method: 'POST', body: file, headers: {
      'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) } });
    cloneStatus.textContent = `「${name}」复刻好了，右边可以试听。`;
    cloneForm.reset();
    showSource();
    loadVoices();
  } catch (err) {
    cloneStatus.className = 'error';
    cloneStatus.textContent = '复刻没有成功：' + err.message;
  } finally {
    clearInterval(progress);
    button.disabled = false;
  }
});

voicesReady.then((data) => {
  if (!data) return;
  maxSeconds = data.ref_max_seconds;
  showSource();
  if (data.cloning) {
    cloneStatus.textContent = '有一个复刻任务正在进行，等它结束后刷新这个页面。';
  }
});
showSource();
