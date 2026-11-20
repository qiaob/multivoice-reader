"""Serve the audition page, persist feedback from it, and clone voices on request.

GET  /*          static files from audition/out
GET  /export     ?voice=...; a cloned voice as a downloadable zip
POST /feedback   JSON body, written to audition/out/feedback.json
POST /clone      audio file body, ?name=...&text=...; runs clone_voice.py

Cloning needs MLX, so start the server on the macOS host for that:

    uv run --no-project --python 3.11 --with mlx-audio python audition/serve.py
"""

import importlib.util
import json
import subprocess
import sys
import threading
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from voice_pack import pack_voice

ROOT = Path(__file__).parent
OUT = ROOT / "out"
FEEDBACK = OUT / "feedback.json"
UPLOADS = OUT / "clone" / "_uploads"
PORT = 8765
MAX_FEEDBACK_BYTES = 1_000_000
MAX_AUDIO_BYTES = 50_000_000
CLONE_TIMEOUT_S = 1800
clone_lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUT), **kwargs)

    def reply(self, status: int, payload: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, content_type: str, limit: int) -> bytes | None:
        # Non-form content types force a CORS preflight, so other sites can't post here.
        if self.headers.get("Content-Type") != content_type:
            self.reply(415, {"error": f"需要 Content-Type: {content_type}"})
            return None
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= limit:
            self.reply(413, {"error": "内容为空或太大"})
            return None
        return self.rfile.read(length)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/export":
            return self.export(parse_qs(url.query).get("voice", [""])[0])
        super().do_GET()

    def export(self, voice_id: str) -> None:
        try:
            body = pack_voice(voice_id)
        except LookupError as err:
            return self.reply(404, {"error": str(err)})
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(voice_id)}.voice.zip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/feedback":
            self.save_feedback()
        elif url.path == "/clone":
            self.clone(parse_qs(url.query))
        else:
            self.reply(404, {"error": "not found"})

    def save_feedback(self) -> None:
        body = self.read_body("application/json", MAX_FEEDBACK_BYTES)
        if body is None:
            return
        try:
            data = json.loads(body)
        except ValueError:
            return self.reply(400, {"error": "不是合法的 JSON"})
        tmp = FEEDBACK.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(FEEDBACK)
        self.reply(204)

    def clone(self, query: dict[str, list[str]]) -> None:
        name = query.get("name", [""])[0].strip()
        text = query.get("text", [""])[0].strip()
        if not name:
            return self.reply(400, {"error": "请给声音起个名字"})
        if importlib.util.find_spec("mlx_audio") is None:
            return self.reply(503, {"error": "当前服务不带本地模型，请按 serve.py 开头的命令在本机启动"})
        body = self.read_body("application/octet-stream", MAX_AUDIO_BYTES)
        if body is None:
            return
        if not clone_lock.acquire(blocking=False):
            return self.reply(409, {"error": "已经有一个复刻任务在进行，请等它结束"})
        suffix = Path(unquote(self.headers.get("X-Filename", ""))).suffix[:10]
        UPLOADS.mkdir(parents=True, exist_ok=True)
        upload = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
        try:
            upload.write_bytes(body)
            cmd = [sys.executable, str(ROOT / "clone_voice.py"), str(upload), "--name", name]
            if text:
                cmd += ["--text", text]
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=CLONE_TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            return self.reply(500, {"error": "复刻超时"})
        finally:
            upload.unlink(missing_ok=True)
            clone_lock.release()
        if done.returncode != 0:
            lines = (done.stderr.strip() or done.stdout.strip()).splitlines()
            return self.reply(500, {"error": lines[-1] if lines else "复刻失败"})
        self.reply(200, {"ok": True})


if __name__ == "__main__":
    print(f"serving {OUT} on port {PORT}", flush=True)
    ThreadingHTTPServer(
        ("127.0.0.1" if sys.platform == "darwin" else "0.0.0.0", PORT), Handler
    ).serve_forever()
