"""The voice library. A voice is a folder with voice.json and a short reference recording;
speaking with it means cloning that recording. Exported voice packs are the same thing zipped.
"""

import io
import json
import os
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

BUILTIN_DIR = Path(__file__).parent / "voices"
UNKNOWN = "未知"
PACK_FORMAT = "multivoice-reader.voice"
PACK_VERSION = 1
# Longest reference recording used for cloning; the page stops recording at this too.
REF_MAX_SECONDS = 20
# What a newly cloned voice reads so that it can be judged by ear: (id, label, emotion, text).
SAMPLES = [
    (
        "narration",
        "旁白",
        "中性",
        "夜色渐深，老街尽头的那盏路灯忽明忽暗。林晚收起伞，在门口站了很久，终于还是抬起手，轻轻敲了三下。",
    ),
    (
        "angry",
        "愤怒",
        "愤怒",
        "你到底还要骗我多久？三年了，整整三年！我把你当成最信任的人，你却一直在背后算计我！",
    ),
    ("sad", "悲伤", "悲伤", "对不起，我来晚了。要是我能早一点到，她就不会一个人走了。"),
    ("happy", "高兴", "高兴", "太好了！我就知道你一定行。走，今晚我请客，咱们好好庆祝一下！"),
    (
        "mixed",
        "中英混读",
        "中性",
        "老板刚在 meeting 上说，这个 project 的 deadline 提前到周五，让我们今晚把 demo 发到他的 email。",
    ),
]


@dataclass
class Voice:
    id: str
    name: str
    gender: str  # 男 / 女 / 未知
    age: str  # 儿童 / 少年 / 青年 / 中年 / 老年 / 未知
    # Built in: "narrator", "character", or "system" (what a novel's "system" announces with).
    # Made by the user and never assigned automatically: "clone" (from a recording of someone)
    # or "design" (from a description).
    kind: str
    desc: str
    ref_audio: Path
    ref_text: str
    own: bool = False  # in the user's library, so theirs to remove
    genre: str = ""  # made for one kind of story (see casting.GENRES); "" suits any

    def sample(self, sample_id: str) -> Path:
        return self.ref_audio.parent / "samples" / f"{sample_id}.mp3"

    def public(self) -> dict:
        """What the web page needs; paths stay on the server."""
        data = asdict(self)
        del data["ref_audio"], data["ref_text"]
        data["samples"] = [
            {"id": sample_id, "label": label}
            for sample_id, label, _, _ in SAMPLES
            if self.sample(sample_id).is_file()
        ]
        return data


def home() -> Path:
    return Path(os.environ.get("MVR_HOME") or Path.home() / ".multivoice-reader")


def voice_id_of(name: str) -> str:
    """The folder name for a voice called this; empty if the name has nothing usable in it."""
    return re.sub(r"[^\w-]+", "_", name).strip("_")


def load_voice(folder: Path, default_kind: str = "clone", own: bool = False) -> Voice | None:
    try:
        config = json.loads((folder / "voice.json").read_text(encoding="utf-8"))
        ref = folder / config["ref_audio"]
        if not ref.is_file():
            return None
        return Voice(
            id=folder.name,
            name=config.get("name") or folder.name,
            gender=config.get("gender") or UNKNOWN,
            age=config.get("age") or UNKNOWN,
            kind=config.get("kind") or default_kind,
            desc=config.get("desc") or "",
            ref_audio=ref,
            ref_text=config["ref_text"],
            own=own,
            genre=config.get("genre") or "",
        )
    except (OSError, ValueError, KeyError):
        return None


def library(extra_dirs: list[Path] = ()) -> dict[str, Voice]:
    """Built-in voices first, then the user's own; a later voice with the same id wins."""
    voices: dict[str, Voice] = {}
    for root, kind, own in [
        (BUILTIN_DIR, "character", False),
        (home() / "voices", "clone", True),
        *((d, "clone", False) for d in extra_dirs),
    ]:
        for folder in sorted(root.glob("*/")) if root.is_dir() else []:
            voice = load_voice(folder, kind, own)
            if voice:
                voices[voice.id] = voice
    return voices


def export_pack(voice: Voice) -> bytes:
    """The voice as one portable file: voice.json and the reference recording, zipped."""
    folder = voice.ref_audio.parent
    config = json.loads((folder / "voice.json").read_text(encoding="utf-8"))
    config = {"format": PACK_FORMAT, "version": PACK_VERSION, **config}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pack:
        pack.writestr("voice.json", json.dumps(config, ensure_ascii=False, indent=2))
        pack.write(voice.ref_audio, config["ref_audio"])
    return buffer.getvalue()


def import_pack(pack: Path) -> Voice:
    """Add an exported voice pack (a .voice.zip) to the user's library."""
    with zipfile.ZipFile(pack) as archive:
        config = json.loads(archive.read("voice.json"))
        voice_id = voice_id_of(str(config.get("name") or pack.stem.split(".")[0]))
        ref_name = Path(config["ref_audio"]).name  # never trust a path from inside an archive
        if not voice_id or ref_name != config["ref_audio"]:
            raise ValueError(f"{pack.name} 不是有效的声音包")
        folder = home() / "voices" / voice_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ref_name).write_bytes(archive.read(ref_name))
        (folder / "voice.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    voice = load_voice(folder, "clone", own=True)
    if voice is None:
        raise ValueError(f"{pack.name} 不是有效的声音包")
    return voice


def remove_voice(voice_id: str) -> None:
    """Delete one of the user's own voices; LookupError if it is not theirs or not there."""
    folder = home() / "voices" / voice_id
    # The id comes from a URL or the command line, so it must not be able to leave the library.
    if not re.fullmatch(r"[\w-]+", voice_id) or not (folder / "voice.json").is_file():
        raise LookupError(f"你的声音库里没有「{voice_id}」")
    shutil.rmtree(folder)
