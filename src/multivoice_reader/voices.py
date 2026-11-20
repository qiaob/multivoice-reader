"""The voice library. A voice is a folder with voice.json and a short reference recording;
speaking with it means cloning that recording. Exported voice packs are the same thing zipped.
"""

import json
import os
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

BUILTIN_DIR = Path(__file__).parent / "voices"
UNKNOWN = "未知"


@dataclass
class Voice:
    id: str
    name: str
    gender: str  # 男 / 女 / 未知
    age: str  # 儿童 / 少年 / 青年 / 中年 / 老年 / 未知
    kind: str  # "narrator", "character", or "clone" (a voice the user made; never auto-assigned)
    desc: str
    ref_audio: Path
    ref_text: str

    def public(self) -> dict:
        """What the web page needs; paths stay on the server."""
        data = asdict(self)
        del data["ref_audio"], data["ref_text"]
        return data


def home() -> Path:
    return Path(os.environ.get("MVR_HOME") or Path.home() / ".multivoice-reader")


def _load(folder: Path, default_kind: str) -> Voice | None:
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
        )
    except (OSError, ValueError, KeyError):
        return None


def library(extra_dirs: list[Path] = ()) -> dict[str, Voice]:
    """Built-in voices first, then the user's own; a later voice with the same id wins."""
    voices: dict[str, Voice] = {}
    for root, kind in [
        (BUILTIN_DIR, "character"),
        (home() / "voices", "clone"),
        *((d, "clone") for d in extra_dirs),
    ]:
        for folder in sorted(root.glob("*/")) if root.is_dir() else []:
            voice = _load(folder, kind)
            if voice:
                voices[voice.id] = voice
    return voices


def import_pack(pack: Path) -> Voice:
    """Add an exported voice pack (a .voice.zip) to the user's library."""
    with zipfile.ZipFile(pack) as archive:
        config = json.loads(archive.read("voice.json"))
        voice_id = re.sub(r"[^\w-]+", "_", str(config.get("name") or pack.stem.split(".")[0])).strip("_")
        ref_name = Path(config["ref_audio"]).name  # never trust a path from inside an archive
        if not voice_id or ref_name != config["ref_audio"]:
            raise ValueError(f"{pack.name} 不是有效的声音包")
        folder = home() / "voices" / voice_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ref_name).write_bytes(archive.read(ref_name))
        (folder / "voice.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    voice = _load(folder, "clone")
    if voice is None:
        raise ValueError(f"{pack.name} 不是有效的声音包")
    return voice
