"""The reading script: what to say, in what order, who says it and how.

It is the one thing that passes from splitting a novel to reading it aloud, and it says
nothing about voices. Anything that writes this format can be read; a script need not come
from a novel at all.

    {"format": "multivoice-reader.script", "version": 1,
     "title": "书名",
     "characters": {"张三": {"gender": "男", "age": "青年"}},
     "chapters": [{"title": "第一章",
                   "lines": [{"text": "夜色渐深。"},
                             {"speaker": "张三", "emotion": "愤怒", "text": "你还要骗我多久？"}]}]}

Only `text` is required in a line: no speaker means the narrator, no emotion means neutral.
`para` may be given to say which lines are shown as one paragraph. `characters` is optional;
a character with a known gender and age gets a fitting voice by default.
"""

import json
import re
from pathlib import Path

FORMAT = "multivoice-reader.script"
VERSION = 1
NARRATOR = "旁白"
NEUTRAL = "中性"
UNKNOWN = "未知"
EMOTIONS = [NEUTRAL, "高兴", "悲伤", "愤怒", "恐惧", "厌恶", "惊讶"]
GENDERS = ["男", "女", UNKNOWN]
AGES = ["儿童", "少年", "青年", "中年", "老年", UNKNOWN]


def chapter_range(spec: str, count: int) -> range:
    """Indices for "3", "3-8", "3-" or "-8" (chapters counted from 1); ValueError if it makes no sense."""
    match = re.fullmatch(r"\s*(\d*)\s*(-?)\s*(\d*)\s*", spec)
    if not match or not (match[1] or match[3]):
        raise ValueError(f"看不懂章节范围「{spec}」，写成 5 或 3-8 这样")
    first = int(match[1]) if match[1] else 1
    last = int(match[3]) if match[3] else (count if match[2] else first)
    if not 1 <= first <= last <= count:
        raise ValueError(f"章节范围「{spec}」不在 1 到 {count} 之间")
    return range(first - 1, last)


def normalize(data) -> dict:
    """The script with every optional part filled in; ValueError says what is wrong with it."""
    if not isinstance(data, dict) or not isinstance(data.get("chapters"), list):
        raise ValueError("这不是一份朗读脚本：缺少 chapters")
    if data.get("format", FORMAT) != FORMAT or data.get("version", VERSION) > VERSION:
        raise ValueError("这份朗读脚本的格式或版本不认识")
    chapters = []
    for number, chapter in enumerate(data["chapters"], 1):
        if not isinstance(chapter, dict) or not isinstance(chapter.get("lines"), list):
            raise ValueError(f"第 {number} 章缺少 lines")
        lines = []
        for position, line in enumerate(chapter["lines"]):
            text = line.get("text") if isinstance(line, dict) else None
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"第 {number} 章第 {position + 1} 句没有 text")
            emotion = line.get("emotion")
            para = line.get("para")
            lines.append(
                {
                    "text": text.strip(),
                    "speaker": str(line.get("speaker") or NARRATOR).strip() or NARRATOR,
                    "emotion": emotion if emotion in EMOTIONS else NEUTRAL,
                    "para": para if isinstance(para, int) and para >= 0 else position,
                }
            )
        if lines:
            chapters.append({"title": str(chapter.get("title") or f"第 {number} 段").strip(), "lines": lines})
    if not chapters:
        raise ValueError("这份朗读脚本里没有可以读的内容")
    given = data.get("characters")
    if not isinstance(given, dict):
        given = {}
    characters = {}
    for chapter in chapters:
        for line in chapter["lines"]:
            name = line["speaker"]
            if name == NARRATOR or name in characters:
                continue
            about = given.get(name)
            if not isinstance(about, dict):
                about = {}
            characters[name] = {
                "gender": about.get("gender") if about.get("gender") in GENDERS else UNKNOWN,
                "age": about.get("age") if about.get("age") in AGES else UNKNOWN,
            }
    return {
        "format": FORMAT,
        "version": VERSION,
        "title": str(data.get("title") or "未命名").strip() or "未命名",
        "characters": characters,
        "chapters": chapters,
    }


def compact(script: dict) -> dict:
    """The script as it is written to a file: what a reader would fill in anyway is left out."""
    chapters = []
    for chapter in script["chapters"]:
        lines = []
        for position, line in enumerate(chapter["lines"]):
            out = {}
            if line["speaker"] != NARRATOR:
                out["speaker"] = line["speaker"]
            if line["emotion"] != NEUTRAL:
                out["emotion"] = line["emotion"]
            if line["para"] != position:
                out["para"] = line["para"]
            out["text"] = line["text"]
            lines.append(out)
        chapters.append({"title": chapter["title"], "lines": lines})
    return {**script, "chapters": chapters}


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as err:
        raise ValueError(f"{path.name} 读不出来，它应该是一个 JSON 文件") from err
    return normalize(data)


def dumps(script: dict) -> str:
    return json.dumps(compact(script), ensure_ascii=False, indent=1) + "\n"
