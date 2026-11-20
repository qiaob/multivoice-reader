"""Build audition/out/index.html from every audition/out/<engine>/voices.json.

Stdlib only; page.css and page.js are inlined. Each engine's generator writes voices.json
plus <engine>/<voice>/<clip>.mp3; this page lists whatever is on disk, on two tabs:
auditioning voices (choices are saved by serve.py to out/feedback.json) and cloning one.
"""

import json
from html import escape
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent
OUT = ROOT / "out"
USES = ["旁白", "主角", "配角", "不要"]
# Longest reference recording used for cloning; also caps in-page recording.
REF_MAX_SECONDS = 20
# Folder under out/ -> heading and one-line explanation, in display order.
# A folder not listed here falls back to the engine name in its voices.json.
ENGINES = {
    "clone": ("复刻的声音", "从你提供的录音复刻出来的。"),
    "ming": ("带情绪的复刻", "朗读用的模型：同一段参考音，愤怒句用愤怒读，温柔句放慢，调侃句带笑。"),
    "qwen_bf16": ("本地设计的声音，未量化版", "按文字描述生成的原创音色。用未量化模型，生成比播放慢。"),
    "qwen": ("本地设计的声音，8bit 版", "同样的描述，用 8bit 量化模型，生成更快。"),
    "edge": ("微软预置声音", "edge-tts 自带的现成音色。需要联网，不能指定语气。"),
}


def load_engines() -> list[tuple[str, dict]]:
    found = {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in OUT.glob("*/voices.json")}
    order = [name for name in ENGINES if name in found] + sorted(set(found) - set(ENGINES))
    return [(name, found[name]) for name in order]


def play_button(src: str, label: str, clip_id: str = "") -> str:
    return (
        f'<button type=button class=clip data-src="{escape(src)}" data-clip="{escape(clip_id)}">'
        f"{escape(label)}</button>"
    )


def voice_row(engine: str, voice: dict, clips: list[dict], with_feedback: bool) -> str:
    base = f"{engine}/{voice['id']}"
    chips = "".join(
        play_button(f"{base}/{c['id']}.mp3", c["label"], c["id"])
        if (OUT / base / f"{c['id']}.mp3").exists()
        else f"<span class='clip none' title='这一句没有生成'>{escape(c['label'])}</span>"
        for c in clips
    )
    # Cloned voices carry their reference recordings so the cleanup can be checked by ear.
    refs = "".join(play_button(r["src"], r["label"]) for r in voice.get("refs", []))
    if engine == "clone" and not with_feedback:
        refs += f'<a class=export href="/export?voice={quote(voice["id"])}" download>导出配置</a>'
    refs = f"<div class=refs>{refs}</div>" if refs else ""
    gender = f"<span class=gender>{escape(voice['gender'])}</span>" if voice["gender"] in "男女" else ""
    feedback = key = ""
    if with_feedback:
        key = f' data-voice="{escape(base)}"'
        uses = "".join(f"<button type=button data-use={u} aria-pressed=false>{u}</button>" for u in USES)
        feedback = (
            f"<div class=use role=group aria-label=用途>{uses}</div>"
            "<input class=note aria-label=备注 placeholder=备注>"
        )
    return (
        f"<li class=voice{key}><div class=who><b class=name>{escape(voice['name'])}</b>{gender}"
        f"<p class=desc>{escape(voice['desc'])}</p>{refs}</div>"
        f"<div class=clips>{chips}</div>{feedback}</li>"
    )


def voice_group(engine: str, info: dict, clips: list[dict], with_feedback: bool = True) -> str:
    title, blurb = ENGINES.get(engine, (info["engine"], ""))
    # A voice with nothing generated yet has nothing to audition.
    voices = [v for v in info["voices"] if any((OUT / engine / v["id"]).glob("*.mp3"))]
    if not voices:
        return ""
    rows = "".join(voice_row(engine, v, clips, with_feedback) for v in voices)
    return (
        f"<div class=group><h2>{escape(title)}<small>{len(voices)} 个</small></h2>"
        f"<p>{escape(blurb)}</p><ul class=voices>{rows}</ul></div>"
    )


CLONE_FORM = """
<form id=clone><ol class=steps>
<li><h3>提供一段声音</h3>
  <div class=sources>
    <label><input type=radio name=source value=file checked>文件</label>
    <label><input type=radio name=source value=mic>麦克风</label>
    <label><input type=radio name=source value=system>系统声音</label>
  </div>
  <p class=hint id=sourceHint></p>
  <div class=source-body data-for=file><input type=file name=audio accept="audio/*,video/*"></div>
  <div class="source-body recorder" data-for="mic system" hidden>
    <button type=button class=rec id=recBtn aria-label=开始录音></button>
    <div><span id=recInfo></span><div class=meter><i id=recLevel></i></div></div>
    <audio id=recPreview controls hidden></audio>
  </div></li>
<li><h3>给它起个名字</h3>
  <input type=text name=name aria-label=名字 placeholder="比如：我的声音" required>
  <label class=field>声音里说的原话。不填会自动识别，人名和生僻词可能认错
    <input type=text name=text></label></li>
<li><h3>复刻</h3>
  <button type=submit class=primary>开始复刻</button>
  <p id=cloneStatus role=status></p>
  <p class=hint>全程在这台电脑上处理。只复刻你自己的声音，或已获得本人同意的声音。</p></li>
</ol></form>
"""


def main() -> None:
    clips = json.loads((ROOT / "texts.json").read_text(encoding="utf-8"))
    style = (ROOT / "page.css").read_text(encoding="utf-8")
    script = (ROOT / "page.js").read_text(encoding="utf-8")
    engines = load_engines()
    lines = "".join(
        f"<dt>{escape(c['label'])}</dt><dd data-line={escape(c['id'])}>{escape(c['text'])}</dd>"
        for c in clips
    )
    groups = "".join(voice_group(name, info, clips) for name, info in engines)
    cloned = "".join(
        voice_group(name, info, clips, with_feedback=False) for name, info in engines if name == "clone"
    )
    cloned = cloned or (
        "<div class=group><h2>复刻的声音</h2>"
        "<p class=empty>还没有。在左边提供一段声音，复刻好的会出现在这里。</p></div>"
    )
    page = (
        "<!doctype html><html lang=zh-CN><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        f"<title>选角台</title><style>{style}</style>"
        "<header class=top><div class=wrap><h1>选角台</h1><nav class=tabs>"
        "<a href={READER_URL}>朗读</a>"
        "<button type=button data-tab=audition>声音试听</button>"
        "<button type=button data-tab=clone>声音复刻</button></nav>"
        "<span id=status role=status></span></div></header>"
        "<main class=wrap>"
        "<section id=tab-audition>"
        f"<h2 class=sheet-title>每个声音都读这五句</h2><div class=sheet><dl>{lines}</dl></div>"
        f"{groups}"
        "<div class=group><h2>总体意见</h2><p>哪类问题最严重，想要什么样的声音，都可以写在这里。</p>"
        "<textarea id=general aria-label=总体意见></textarea></div>"
        "</section>"
        f"<section id=tab-clone hidden><div class=clone-layout>{CLONE_FORM}{cloned}</div></section>"
        "</main>"
        f"<script>const MAX_REC_SECONDS = {REF_MAX_SECONDS};\n{script}</script></html>"
    )
    (OUT / "index.html").write_text(page, encoding="utf-8")
    print(f"wrote {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
