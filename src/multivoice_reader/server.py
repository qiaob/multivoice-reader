"""The reader's page server: the book as text, its audio as it becomes ready, and the casting.

It owns the worker process for the open book. All state lives in the book's folder, so the
server itself remembers nothing between requests.
"""

import json
import subprocess
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .analyze import NARRATOR
from .book import Book
from .voices import library
from .worker import segment_audio_key, voice_of

WEB = Path(__file__).parent / "web"
MAX_BOOK_BYTES = 200_000_000
MAX_JSON_BYTES = 100_000


class App:
    def __init__(self, voice_dirs: list[Path]):
        self.voice_dirs = voice_dirs
        self.book: Book | None = None
        self.worker: subprocess.Popen | None = None

    def voices(self):
        return library(self.voice_dirs)

    def open(self, book: Book) -> None:
        self.close()
        self.book = book
        log = open(book.dir / "worker.log", "ab")
        self.worker = subprocess.Popen(
            [sys.executable, "-m", "multivoice_reader.worker", str(book.dir), *map(str, self.voice_dirs)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    def close(self) -> None:
        if self.worker:
            self.worker.terminate()
            self.worker.wait(timeout=30)
        self.worker = None

    # ---- views ----
    def state(self) -> dict:
        book = self.book
        return {
            "book": {"id": book.id, "title": book.title, "chapters": book.chapters} if book else None,
            "books": [{"id": b.id, "title": b.title, "chapters": len(b.chapters)} for b in Book.all()],
            "voices": [v.public() for v in self.voices().values()],
        }

    def chapter(self, index: int) -> dict:
        book, voices = self.book, self.voices()
        script = book.script(index)
        segments = []
        for segment in script or []:
            voice_id, key = segment_audio_key(segment, book, voices)
            ready = book.audio_path(key).exists()
            segments.append({**segment, "voice": voice_id, "audio": f"/audio/{key}.mp3" if ready else None})
        status = book.status()
        if self.worker and self.worker.poll() is not None:
            status = {"state": "error", "message": "后台进程退出了，详情见这本书目录下的 worker.log"}
        return {"chapter": index, "analysed": script is not None, "segments": segments, "status": status}

    def cast(self) -> list[dict]:
        book, voices = self.book, self.voices()
        chosen = book.cast()
        rows = [{"name": NARRATOR, "voice": voice_of(NARRATOR, book, voices), "chosen": NARRATOR in chosen}]
        characters = sorted(book.characters().items(), key=lambda item: -item[1]["lines"])
        for name, info in characters:
            rows.append(
                {
                    "name": name,
                    "gender": info["gender"],
                    "age": info["age"],
                    "lines": info["lines"],
                    "voice": voice_of(name, book, voices),
                    "chosen": name in chosen,
                }
            )
        return rows


class Handler(SimpleHTTPRequestHandler):
    app: App

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, *args) -> None:  # the page polls; one line per request is noise
        pass

    def reply(self, status: int, payload=None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
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
        query = parse_qs(url.query)
        app = self.app
        if url.path == "/api/state":
            return self.reply(200, app.state())
        if url.path.startswith("/voice-ref/"):
            voice = app.voices().get(unquote(url.path.removeprefix("/voice-ref/")))
            return (
                self.send_file(voice.ref_audio, "audio/wav")
                if voice
                else self.reply(404, {"error": "没有这个声音"})
            )
        if not url.path.startswith(("/api/", "/audio/")):
            return super().do_GET()
        if app.book is None:
            return self.reply(409, {"error": "还没有打开小说"})
        if url.path == "/api/chapter":
            index = int(query.get("k", ["0"])[0])
            if not 0 <= index < len(app.book.chapters):
                return self.reply(404, {"error": "没有这一章"})
            return self.reply(200, app.chapter(index))
        if url.path == "/api/cast":
            return self.reply(200, app.cast())
        if url.path.startswith("/audio/"):
            name = url.path.removeprefix("/audio/").removesuffix(".mp3")
            path = app.book.audio_path(name)
            if not name.isalnum() or not path.is_file():
                return self.reply(404, {"error": "这一句还没有合成"})
            return self.send_file(path, "audio/mpeg")
        self.reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        app = self.app
        if url.path == "/api/books":
            body = self.read_body("application/octet-stream", MAX_BOOK_BYTES)
            if body is None:
                return
            name = Path(parse_qs(url.query).get("name", ["小说.txt"])[0]).name
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / name
                source.write_bytes(body)
                try:
                    app.open(Book.create(source))
                except ValueError as err:
                    return self.reply(400, {"error": str(err)})
            return self.reply(200, app.state())
        body = self.read_body("application/json", MAX_JSON_BYTES)
        if body is None:
            return
        try:
            data = json.loads(body)
        except ValueError:
            return self.reply(400, {"error": "不是合法的 JSON"})
        if url.path == "/api/open":
            book = next((b for b in Book.all() if b.id == data.get("id")), None)
            if book is None:
                return self.reply(404, {"error": "没有这本书"})
            app.open(book)
            return self.reply(200, app.state())
        if app.book is None:
            return self.reply(409, {"error": "还没有打开小说"})
        if url.path == "/api/target":
            app.book.save_target(int(data["chapter"]), int(data["segment"]))
            return self.reply(204)
        if url.path == "/api/cast":
            cast = app.book.cast()
            if data.get("voice") in app.voices():
                cast[str(data["name"])] = data["voice"]
            else:  # no voice given: back to the automatic choice
                cast.pop(str(data.get("name")), None)
            app.book.save_cast(cast)
            return self.reply(200, app.cast())
        self.reply(404, {"error": "not found"})


def serve(app: App, port: int) -> None:
    Handler.app = app
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
