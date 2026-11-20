"""Generate audition clips for every Mandarin-capable edge-tts voice.

Output: audition/out/edge/<voice>/<clip>.mp3 and audition/out/edge/voices.json.
Existing clips are skipped, so re-running retries only the failures.
"""

import asyncio
import json
from pathlib import Path

import edge_tts

ROOT = Path(__file__).parent
OUT = ROOT / "out" / "edge"
CONCURRENCY = 4


def is_mandarin_capable(voice: dict) -> bool:
    name = voice["ShortName"]
    if "Multilingual" in name:
        return True
    # zh-CN-liaoning-XiaobeiNeural style names are dialects; zh-HK is Cantonese.
    return voice["Locale"] in ("zh-CN", "zh-TW") and name.count("-") == 2


async def synth(sem: asyncio.Semaphore, voice: str, clip: dict) -> str | None:
    path = OUT / voice / f"{clip['id']}.mp3"
    if path.exists() and path.stat().st_size > 0:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    async with sem:
        try:
            await edge_tts.Communicate(clip["text"], voice).save(str(path))
        except Exception as exc:  # report and continue; a re-run retries it
            path.unlink(missing_ok=True)
            return f"{voice}/{clip['id']}: {exc}"
    return None


async def main() -> None:
    clips = json.loads((ROOT / "texts.json").read_text(encoding="utf-8"))
    voices = sorted(
        (v for v in await edge_tts.list_voices() if is_mandarin_capable(v)),
        key=lambda v: (not v["Locale"].startswith("zh"), v["ShortName"]),
    )
    OUT.mkdir(parents=True, exist_ok=True)
    meta = [
        {
            "id": v["ShortName"],
            "name": v["ShortName"].split("-")[-1].removesuffix("Neural"),
            "gender": "女" if v["Gender"] == "Female" else "男",
            "desc": f"{v['Locale']} · " + "、".join(v["VoiceTag"]["VoicePersonalities"]),
        }
        for v in voices
    ]
    (OUT / "voices.json").write_text(
        json.dumps({"engine": "edge-tts", "voices": meta}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*(synth(sem, v["ShortName"], c) for v in voices for c in clips))
    failures = [r for r in results if r]
    print(f"voices={len(voices)} clips={len(results)} failed={len(failures)}")
    for failure in failures:
        print("FAILED", failure)


if __name__ == "__main__":
    asyncio.run(main())
