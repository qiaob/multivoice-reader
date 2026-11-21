"""The page server. Four pages share it, each for one job:

    拆分        novels -> reading scripts (book.py, split.py)
    朗读        reading scripts -> speech, with a voice for each character (reading.py, worker.py)
    声音试听     the voice library (voices.py)
    声音复刻     a new voice from a recording (clone.py)

Many novels and many scripts are kept side by side; every request says which one it means.
The models do not fit in memory together, so one background process runs at a time, chosen
in this order: cloning a voice; speaking for the script someone is listening to; splitting
the novels that are waiting, in the order they were asked for; speaking whole scripts ahead
of time. All state lives in folders on disk, so the server itself remembers little.
"""

import json
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .analyze import DEFAULT_MODEL, MODELS
from .book import Book
from .reading import Reading, folder_of, whole_queue
from .script import NARRATOR, dumps, normalize
from .voices import REF_MAX_SECONDS, export_pack, import_pack, library, remove_voice
from .worker import caster, next_job, segment_audio_key

WEB = Path(__file__).parent / "web"
MAX_BOOK_BYTES = 200_000_000
MAX_JSON_BYTES = 100_000
MAX_AUDIO_BYTES = 50_000_000
MAX_PACK_BYTES = 50_000_000
CLONE_TIMEOUT_S = 1800
LISTENING_SECONDS = 8  # a script counts as being listened to this long after its page last asked
TICK_SECONDS = 2.0
COUNT_EVERY_SECONDS = 10  # how often a script's made lines are counted again while they change
COUNT_BUDGET_SECONDS = 0.25  # how long one request for the list may spend counting


def stop(process: subprocess.Popen | None) -> None:
    if process and process.poll() is None:
        process.terminate()
        process.wait(timeout=30)


class App:
    def __init__(self, voice_dirs: list[Path]):
        self.voice_dirs = voice_dirs
        self.process: subprocess.Popen | None = None
        self.job: tuple[str, str] | None = None  # ("split", book id), ("listen" or "whole", reading id)
        self.cloning = threading.Lock()  # held while a voice is being cloned
        self.lock = threading.RLock()  # choosing, starting and stopping the background process
        self.heard: tuple[str, float] = ("", 0.0)  # the script last asked for by its page, and when
        self.broken: dict[str, str] = {}  # reading id -> why speaking for it stopped
        self.opened: dict[str, tuple[float, Reading]] = {}  # scripts are big: loaded once
        self.counted: dict[str, tuple[tuple, float, int]] = {}  # reading id -> (state then, when, lines made)

    def voices(self):
        return library(self.voice_dirs)

    def reading(self, reading_id: str) -> Reading | None:
        folder = folder_of(reading_id)
        if folder is None:
            self.opened.pop(reading_id, None)
            return None
        changed = (folder / "script.json").stat().st_mtime
        if self.opened.get(reading_id, (0.0, None))[0] != changed:
            self.opened[reading_id] = (changed, Reading(folder))
        return self.opened[reading_id][1]

    # ---- one background process at a time ----
    def wanted(self) -> tuple[str, str] | None:
        """What should be running now."""
        if self.cloning.locked():
            return None
        reading_id, when = self.heard
        if time.time() - when < LISTENING_SECONDS and reading_id not in self.broken:
            reading = self.reading(reading_id)
            if reading and next_job(reading, self.voices(), set()) is not None:
                return ("listen", reading_id)
        waiting = sorted((book for book in Book.all() if book.waiting()), key=lambda book: book.asked_at())
        if waiting:
            return ("split", waiting[0].id)
        for reading_id in whole_queue():
            if reading_id not in self.broken:
                return ("whole", reading_id)
        return None

    def settle(self) -> None:
        """Start, stop or change the background process so that it is the one wanted."""
        with self.lock:
            if self.process and self.process.poll() is not None:
                self.ended(self.job, self.process.returncode)
                self.process = self.job = None
            want = self.wanted()
            if want == self.job:
                return
            stop(self.process)
            self.process = self.job = None
            if want is None:
                return
            kind, which = want
            if kind == "split":
                folder = Book.open(which).dir
                command = [sys.executable, "-m", "multivoice_reader.split", str(folder)]
            else:
                folder = self.reading(which).dir
                command = [sys.executable, "-m", "multivoice_reader.worker", kind, str(folder)]
                command += [str(d) for d in self.voice_dirs]
            log = open(folder / "worker.log", "ab")
            self.process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            self.job = want

    def ended(self, job: tuple[str, str], code: int) -> None:
        """A process that ended by itself: one that failed must not be started again and again."""
        kind, which = job
        if kind == "split":
            book = Book.open(which)
            if book and (code != 0 or book.status().get("state") == "error"):
                status = book.status()
                book.save_until(0)
                message = status.get("message") or "拆分进程退出了，详情见这本书目录下的 worker.log"
                book.save_status(state="error", message=message)
        elif code != 0:
            self.broken[which] = "合成进程退出了，详情见这份脚本目录下的 worker.log"
            reading = self.reading(which)
            if reading and kind == "whole":
                reading.want_whole(False)

    def close(self) -> None:
        with self.lock:
            stop(self.process)
            self.process = self.job = None

    def running(self, kind: str, which: str) -> bool:
        return self.job == (kind, which) and self.process is not None and self.process.poll() is None

    def clone(self, audio: Path, name: str, text: str) -> str:
        """Clone a voice in a process of its own; returns what went wrong, or nothing.
        The caller holds self.cloning, which keeps every other background process from starting."""
        self.close()
        command = [sys.executable, "-m", "multivoice_reader.clone", str(audio), "--name", name]
        try:
            done = subprocess.run(
                command + (["--text", text] if text else []),
                capture_output=True,
                text=True,
                timeout=CLONE_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "复刻超时"
        if done.returncode == 0:
            return ""
        lines = (done.stderr.strip() or done.stdout.strip()).splitlines()
        return lines[-1] if lines else "复刻失败"

    # ---- the split page ----
    def book_view(self, book: Book, queue: list[str]) -> dict:
        done = book.done()
        status = book.status()
        if self.running("split", book.id):
            state = "running"
        elif book.id in queue:
            state = "waiting"
        elif status.get("state") == "error":
            state = "error"
        else:
            state = "done" if all(done) else "idle"
        return {
            "id": book.id,
            "title": book.title,
            "chapters": len(done),
            "done": sum(done),
            "until": book.until(),
            "model": book.model() or DEFAULT_MODEL,
            "state": state,
            "place": queue.index(book.id) + 1 if book.id in queue else 0,
            "now": book.chapters[status["chapter"]] if state == "running" and "chapter" in status else "",
            "message": status.get("message", "") if state == "error" else "",
        }

    def books(self) -> list[dict]:
        books = Book.all()
        waiting = sorted((book for book in books if book.waiting()), key=lambda book: book.asked_at())
        queue = [book.id for book in waiting]
        return [self.book_view(book, queue) for book in books]

    def book(self, book: Book) -> dict:
        view = next(item for item in self.books() if item["id"] == book.id)
        return {**view, "chapters": book.chapters, "done": book.done()}

    def split_characters(self, book: Book) -> list[dict]:
        people = [{"name": name, **about} for name, about in book.characters().items()]
        return sorted(people, key=lambda person: -person.get("lines", 0))

    def remove_book(self, book: Book) -> None:
        with self.lock:
            if self.job == ("split", book.id):
                self.close()
            book.remove()

    # ---- the reading page ----
    def made(self, reading_id: str, may_count: bool) -> int | None:
        """How many of a script's lines have audio in the voices they have now; None if not
        known yet. Counting means loading the whole script, so the answer is kept until the
        script, its voices or its audio change, and while audio is being made it is refreshed
        only now and then."""
        folder = folder_of(reading_id)
        if folder is None:
            return None

        def stamp() -> tuple:
            names = ("script.json", "cast.json", "assigned.json", "audio")
            return tuple((folder / n).stat().st_mtime if (folder / n).exists() else 0 for n in names)

        kept = self.counted.get(reading_id)
        fresh = kept is not None and (kept[0] == stamp() or time.time() - kept[1] < COUNT_EVERY_SECONDS)
        if fresh or not may_count:
            return kept[2] if kept else None
        reading = self.opened[reading_id][1] if reading_id in self.opened else Reading(folder)
        voice_of = caster(reading, self.voices())
        there = {p.stem for p in (folder / "audio").glob("*.mp3")}
        made = sum(
            segment_audio_key(segment, voice_of)[1] in there
            for chapter in range(len(reading.chapters))
            for segment in reading.segments(chapter)
        )
        self.counted[reading_id] = (stamp(), time.time(), made)
        return made

    def readings(self) -> list[dict]:
        queue = [reading_id for reading_id in whole_queue() if reading_id not in self.broken]
        rows = []
        enough = time.time() + COUNT_BUDGET_SECONDS  # the rest are counted on later requests
        for item in Reading.shelf():
            reading_id = item["id"]
            made = self.made(reading_id, time.time() < enough)
            lines = item.get("lines", 0)
            if self.running("listen", reading_id) or self.running("whole", reading_id):
                state = "speaking"
            elif reading_id in self.broken:
                state = "error"
            elif reading_id in queue:
                state = "waiting"
            else:
                state = "done" if lines and made is not None and made >= lines else "idle"
            rows.append(
                {
                    **item,
                    "made": made,
                    "whole": reading_id in queue,
                    "state": state,
                    "place": queue.index(reading_id) + 1 if reading_id in queue else 0,
                    "message": self.broken.get(reading_id, ""),
                }
            )
        return rows

    def chapter(self, reading: Reading, index: int) -> dict:
        voices = self.voices()
        voice_of = caster(reading, voices)
        segments = []
        for segment in reading.segments(index):
            voice_id, key = segment_audio_key(segment, voice_of)
            ready = reading.audio_path(key).exists()
            audio = f"/audio/{quote(reading.id)}/{key}.mp3" if ready else None
            segments.append({**segment, "voice": voice_id, "audio": audio})
        self.heard = (reading.id, time.time())
        self.settle()
        if self.cloning.locked():
            status = {"state": "paused"}
        elif reading.id in self.broken:
            status = {"state": "error", "message": self.broken[reading.id]}
        elif self.running("listen", reading.id) or self.running("whole", reading.id):
            status = reading.status()
        else:
            status = {"state": "idle"}
        return {"chapter": index, "segments": segments, "status": status}

    def cast(self, reading: Reading) -> list[dict]:
        voices = self.voices()
        voice_of, chosen = caster(reading, voices), reading.cast()
        rows = [{"name": NARRATOR, "voice": voice_of(NARRATOR), "chosen": NARRATOR in chosen}]
        for name, about in reading.characters().items():
            rows.append({"name": name, **about, "voice": voice_of(name), "chosen": name in chosen})
        return rows

    def remove_reading(self, reading: Reading) -> None:
        with self.lock:
            if self.job in (("listen", reading.id), ("whole", reading.id)):
                self.close()
            self.opened.pop(reading.id, None)
            self.broken.pop(reading.id, None)
            self.counted.pop(reading.id, None)
            reading.remove()


class Handler(SimpleHTTPRequestHandler):
    app: App

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, *args) -> None:  # the pages poll; one line per request is noise
        pass

    def end_headers(self) -> None:
        # Always ask again: a page kept from an earlier version would talk to this one wrongly.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def reply(self, status: int, payload=None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str) -> None:
        self.send_bytes(path.read_bytes(), content_type)

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

    def upload_name(self, default: str) -> str:
        return Path(unquote(self.headers.get("X-Filename", "")) or default).name

    def the_book(self, book_id) -> Book | None:
        book = Book.open(str(book_id))
        if book is None:
            self.reply(404, {"error": "没有这本书"})
        return book

    def the_reading(self, reading_id) -> Reading | None:
        reading = self.app.reading(str(reading_id))
        if reading is None:
            self.reply(404, {"error": "没有这份脚本"})
        return reading

    # ---- GET ----
    def do_GET(self) -> None:
        url = urlsplit(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        app = self.app
        route = url.path
        if route == "/api/voices":
            voices = [v.public() for v in app.voices().values()]
            return self.reply(
                200, {"voices": voices, "ref_max_seconds": REF_MAX_SECONDS, "cloning": app.cloning.locked()}
            )
        if route == "/api/voices/export":
            voice = app.voices().get(query.get("id", ""))
            if voice is None:
                return self.reply(404, {"error": "没有这个声音"})
            name = f"attachment; filename*=UTF-8''{quote(voice.id)}.voice.zip"
            return self.send_bytes(export_pack(voice), "application/zip", {"Content-Disposition": name})
        if route.startswith("/voice-ref/"):
            voice = app.voices().get(unquote(route.removeprefix("/voice-ref/")))
            if voice is None:
                return self.reply(404, {"error": "没有这个声音"})
            return self.send_file(voice.ref_audio, "audio/wav")
        if route.startswith("/voice-sample/"):
            voice_id, _, sample_id = unquote(route.removeprefix("/voice-sample/")).partition("/")
            voice = app.voices().get(voice_id)
            path = voice.sample(sample_id.removesuffix(".mp3")) if voice else None
            if path is None or not sample_id.removesuffix(".mp3").isalnum() or not path.is_file():
                return self.reply(404, {"error": "没有这段试读"})
            return self.send_file(path, "audio/mpeg")
        if route == "/api/split/books":
            app.settle()
            return self.reply(200, {"books": app.books(), "cloning": app.cloning.locked()})
        if route == "/api/split/models":
            models = [{"id": name, "about": about["about"]} for name, about in MODELS.items()]
            return self.reply(200, {"models": models, "default": DEFAULT_MODEL})
        if route.startswith("/api/split/"):
            book = self.the_book(query.get("id"))
            return self.get_split(route.removeprefix("/api/split/"), book, query) if book else None
        if route == "/api/readings":
            app.settle()
            return self.reply(200, {"readings": app.readings(), "cloning": app.cloning.locked()})
        if route.startswith("/audio/"):
            reading_id, _, name = unquote(route.removeprefix("/audio/")).partition("/")
            reading = app.reading(reading_id)
            name = name.removesuffix(".mp3")
            if reading is None or not name.isalnum() or not reading.audio_path(name).is_file():
                return self.reply(404, {"error": "这一句还没有合成"})
            return self.send_file(reading.audio_path(name), "audio/mpeg")
        if not route.startswith("/api/"):
            return super().do_GET()
        reading = self.the_reading(query.get("id"))
        if reading is None:
            return
        if route == "/api/reading":
            return self.reply(200, {"id": reading.id, "title": reading.title, "chapters": reading.chapters})
        if route == "/api/chapter":
            index = int(query.get("k", "0"))
            if not 0 <= index < len(reading.chapters):
                return self.reply(404, {"error": "没有这一章"})
            return self.reply(200, app.chapter(reading, index))
        if route == "/api/cast":
            return self.reply(200, app.cast(reading))
        self.reply(404, {"error": "not found"})

    def get_split(self, what: str, book: Book, query: dict[str, str]) -> None:
        if what == "book":
            return self.reply(200, self.app.book(book))
        if what == "chapter":
            index = int(query.get("k", "0"))
            if not 0 <= index < len(book.chapters):
                return self.reply(404, {"error": "没有这一章"})
            return self.reply(200, {"chapter": index, "lines": book.lines(index)})
        if what == "characters":
            return self.reply(200, self.app.split_characters(book))
        if what == "script":
            try:
                body = dumps(book.script()).encode()
            except ValueError as err:
                return self.reply(409, {"error": str(err)})
            name = f"attachment; filename*=UTF-8''{quote(book.title)}.json"
            return self.send_bytes(body, "application/json; charset=utf-8", {"Content-Disposition": name})
        self.reply(404, {"error": "not found"})

    # ---- POST ----
    def do_POST(self) -> None:
        url = urlsplit(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        app = self.app
        route = url.path
        if route == "/api/split/books":
            return self.new_book()
        if route == "/api/readings":
            return self.new_reading()
        if route == "/api/clone":
            return self.clone_voice(query)
        if route == "/api/voices/import":
            return self.import_voice()
        body = self.read_body("application/json", MAX_JSON_BYTES)
        if body is None:
            return
        try:
            data = json.loads(body)
        except ValueError:
            return self.reply(400, {"error": "不是合法的 JSON"})
        if not isinstance(data, dict):
            return self.reply(400, {"error": "不是合法的请求"})
        if route == "/api/voices/remove":
            try:
                remove_voice(str(data.get("id")))
            except LookupError as err:
                return self.reply(404, {"error": str(err)})
            return self.reply(204)
        if route.startswith("/api/split/"):
            book = self.the_book(data.get("id"))
            return self.post_split(route.removeprefix("/api/split/"), book, data) if book else None
        reading = self.the_reading(data.get("id"))
        if reading is None:
            return
        if route == "/api/readings/remove":
            app.remove_reading(reading)
            return self.reply(204)
        if route == "/api/readings/whole":  # speak all of it ahead of time, or stop doing so
            reading.want_whole(bool(data.get("on")))
            app.broken.pop(reading.id, None)
            app.settle()
            return self.reply(204)
        if route == "/api/target":
            reading.save_target(int(data["chapter"]), int(data["segment"]))
            app.heard = (reading.id, time.time())
            return self.reply(204)
        if route == "/api/cast":
            cast = reading.cast()
            if data.get("voice") in app.voices():
                cast[str(data["name"])] = data["voice"]
            else:  # no voice given: back to the automatic choice
                cast.pop(str(data.get("name")), None)
            reading.save_cast(cast)
            return self.reply(200, app.cast(reading))
        self.reply(404, {"error": "not found"})

    def post_split(self, what: str, book: Book, data: dict) -> None:
        app = self.app
        if what == "start":  # join the queue, to be split as far as asked
            until = int(data.get("until") or len(book.chapters))
            model = data.get("model") or DEFAULT_MODEL
            if model not in MODELS:
                return self.reply(400, {"error": f"没有「{model}」这个模型"})
            book.save_until(max(1, min(until, len(book.chapters))), model)
            book.save_status(state="idle")
        elif what == "stop":  # leave the queue, or stop if it is this one's turn
            book.save_until(0)
            book.save_status(state="idle")
        elif what == "remove":
            app.remove_book(book)
        elif what == "send":  # hand what has been split so far to the reading page
            try:
                reading = Reading.create(book.script())
            except ValueError as err:
                return self.reply(409, {"error": str(err)})
            app.broken.pop(reading.id, None)
            return self.reply(200, {"id": reading.id})
        else:
            return self.reply(404, {"error": "not found"})
        app.settle()
        self.reply(204)

    def new_book(self) -> None:
        body = self.read_body("application/octet-stream", MAX_BOOK_BYTES)
        if body is None:
            return
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / self.upload_name("小说.txt")
            source.write_bytes(body)
            try:
                book = Book.create(source)
            except ValueError as err:
                return self.reply(400, {"error": str(err)})
        self.reply(200, {"id": book.id})

    def new_reading(self) -> None:
        body = self.read_body("application/octet-stream", MAX_BOOK_BYTES)
        if body is None:
            return
        try:
            data = json.loads(body.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            return self.reply(400, {"error": "这个文件不能读：它应该是一个 JSON 格式的朗读脚本"})
        try:
            reading = Reading.create(normalize(data))
        except ValueError as err:
            return self.reply(400, {"error": str(err)})
        self.app.broken.pop(reading.id, None)
        self.reply(200, {"id": reading.id})

    def clone_voice(self, query: dict[str, str]) -> None:
        name = query.get("name", "").strip()
        if not name:
            return self.reply(400, {"error": "请给声音起个名字"})
        body = self.read_body("application/octet-stream", MAX_AUDIO_BYTES)
        if body is None:
            return
        if not self.app.cloning.acquire(blocking=False):
            return self.reply(409, {"error": "已经有一个复刻任务在进行，请等它结束"})
        try:
            with tempfile.TemporaryDirectory() as folder:
                upload = Path(folder) / f"recording{Path(self.upload_name('x')).suffix[:10]}"
                upload.write_bytes(body)
                error = self.app.clone(upload, name, query.get("text", "").strip())
        finally:
            self.app.cloning.release()
            self.app.settle()
        if error:
            return self.reply(500, {"error": error})
        self.reply(200, {"ok": True})

    def import_voice(self) -> None:
        body = self.read_body("application/octet-stream", MAX_PACK_BYTES)
        if body is None:
            return
        with tempfile.TemporaryDirectory() as folder:
            pack = Path(folder) / self.upload_name("声音.voice.zip")
            pack.write_bytes(body)
            try:
                voice = import_pack(pack)
            except (ValueError, KeyError, OSError, zipfile.BadZipFile):
                return self.reply(400, {"error": "这不是一个有效的声音包"})
        self.reply(200, voice.public())


def serve(app: App, port: int) -> None:
    Handler.app = app
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    ticking = threading.Event()

    def tick() -> None:  # the queues move on even when no page is open
        while not ticking.wait(TICK_SECONDS):
            try:
                app.settle()
            except Exception:
                pass

    threading.Thread(target=tick, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ticking.set()
        app.close()
