"""Export a cloned voice as one portable file.

    python audition/voice_pack.py 我的声音               # writes 我的声音.voice.zip here
    python audition/voice_pack.py 我的声音 -o ~/Desktop

The zip holds voice.json (the name, the reference text, the model the voice was made for)
and the cleaned reference recording: everything needed to speak with this voice again.
Stdlib only.
"""

import argparse
import io
import json
import re
import zipfile
from pathlib import Path

CLONES = Path(__file__).parent / "out" / "clone"
FORMAT = "multivoice-reader.voice"
VERSION = 1


def pack_voice(voice_id: str) -> bytes:
    """Zip bytes for a cloned voice; LookupError if there is no such voice."""
    voice_dir = CLONES / voice_id
    # The id comes from a URL or the command line, so it must not be able to leave CLONES.
    if not re.fullmatch(r"[\w-]+", voice_id) or not (voice_dir / "voice.json").is_file():
        raise LookupError(f"没有叫「{voice_id}」的复刻声音")
    config = json.loads((voice_dir / "voice.json").read_text(encoding="utf-8"))
    config = {"format": FORMAT, "version": VERSION, **config}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pack:
        pack.writestr("voice.json", json.dumps(config, ensure_ascii=False, indent=2))
        pack.write(voice_dir / config["ref_audio"], config["ref_audio"])
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="把一个复刻的声音导出成一个文件")
    parser.add_argument("voice", help="复刻时起的名字")
    parser.add_argument("-o", "--out-dir", type=Path, default=Path.cwd(), help="导出到哪个目录，默认当前目录")
    args = parser.parse_args()
    try:
        data = pack_voice(args.voice)
    except LookupError as err:
        known = sorted(p.parent.name for p in CLONES.glob("*/voice.json"))
        raise SystemExit(f"{err}。现有的声音：{'、'.join(known) or '还没有'}") from err
    target = args.out_dir.expanduser() / f"{args.voice}.voice.zip"
    target.write_bytes(data)
    print(f"已导出：{target}")


if __name__ == "__main__":
    main()
