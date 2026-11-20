"""Plain text in, chapters and speakable segments out. Rules only, no models."""

import re
from dataclasses import dataclass
from pathlib import Path

# "第12章 标题", "第十二回", optionally after a short volume name: "卷名 第12章 标题".
HEADING = re.compile(
    r"^\s*(?:[^\s，。！？：“”]{1,12}\s+)?第\s*[0-9０-９零〇一二三四五六七八九十百千两]+\s*[章回节卷](?:\s.{0,40})?\s*$"
)
QUOTED = re.compile(r"“([^“”]*)”|「([^「」]*)」")
SENTENCE_END = "。！？…!?"
# What a quoted span ends with when it is speech rather than a quoted term in the narration.
SPEECH_END = SENTENCE_END + "，、；—～~.,"
FALLBACK_CHAPTER_CHARS = 3000
NARRATION_CHARS = 70
DIALOGUE_CHARS = 120


@dataclass
class Chapter:
    title: str
    paragraphs: list[str]


@dataclass
class Segment:
    kind: str  # "narration" or "dialogue"
    text: str
    para: int  # index of the paragraph it came from


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"认不出 {path.name} 的文字编码")


def split_chapters(text: str) -> list[Chapter]:
    """Split on chapter headings; text before the first heading (blurb, credits) is dropped.

    A text without headings is cut into pieces of roughly equal size at paragraph breaks.
    """
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    chapters: list[Chapter] = []
    for line in lines:
        if HEADING.match(line):
            chapters.append(Chapter(re.sub(r"\s+", " ", line), []))
        elif chapters:
            chapters[-1].paragraphs.append(line)
    if chapters:
        return [c for c in chapters if c.paragraphs]
    size = 0
    for line in lines:
        if not chapters or size >= FALLBACK_CHAPTER_CHARS:
            chapters.append(Chapter(f"第 {len(chapters) + 1} 段", []))
            size = 0
        chapters[-1].paragraphs.append(line)
        size += len(line)
    return chapters


def _sentences(text: str) -> list[str]:
    parts = re.findall(rf"[^{SENTENCE_END}]*[{SENTENCE_END}]+[”」’』）)]*|[^{SENTENCE_END}]+$", text)
    return [p.strip() for p in parts if p.strip()]


def _chunks(text: str, limit: int) -> list[str]:
    """Group whole sentences into pieces of at most `limit` characters where possible."""
    out: list[str] = []
    for sentence in _sentences(text):
        if out and len(out[-1]) + len(sentence) <= limit:
            out[-1] += sentence
        else:
            out.append(sentence)
    return out


def _is_speech(inner: str) -> bool:
    inner = inner.strip()
    return len(inner) > 12 or (len(inner) >= 1 and inner[-1] in SPEECH_END)


def split_segments(paragraphs: list[str]) -> list[Segment]:
    """Cut paragraphs into narration and dialogue, in reading order."""
    segments: list[Segment] = []
    for index, para in enumerate(paragraphs):
        narration = ""
        cursor = 0

        def flush(index: int = index) -> None:
            nonlocal narration
            if re.search(r"\w", narration):
                segments.extend(Segment("narration", c, index) for c in _chunks(narration, NARRATION_CHARS))
            narration = ""

        for match in QUOTED.finditer(para):
            inner = match.group(1) if match.group(1) is not None else match.group(2)
            narration += para[cursor : match.start()]
            cursor = match.end()
            if _is_speech(inner):
                flush()
                segments.extend(Segment("dialogue", c, index) for c in _chunks(inner.strip(), DIALOGUE_CHARS))
            else:
                narration += match.group(0)  # a quoted term stays part of the narration
        narration += para[cursor:]
        flush()
    return segments


DIGITS = "零一二三四五六七八九"


def _integer_to_chinese(number: int) -> str:
    if number < 10:
        return DIGITS[number]
    if number >= 10**8:
        head, rest = divmod(number, 10**8)
        tail = _integer_to_chinese(rest) if rest else ""
        return _integer_to_chinese(head) + "亿" + ("零" if 0 < rest < 10**7 else "") + tail
    if number >= 10**4:
        head, rest = divmod(number, 10**4)
        tail = _integer_to_chinese(rest) if rest else ""
        return _integer_to_chinese(head) + "万" + ("零" if 0 < rest < 1000 else "") + tail
    out, zero_pending = "", False
    for unit, name in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit, number = divmod(number, unit)
        if digit:
            out += ("零" if zero_pending and out else "") + DIGITS[digit] + name
            zero_pending = False
        else:
            zero_pending = True
    return out[1:] if out.startswith("一十") else out


def _number_to_chinese(match: re.Match) -> str:
    whole, fraction, percent = match.group(1), match.group(2), match.group(3)
    if len(whole) > 12:  # an id or a phone number: read it digit by digit
        spoken = "".join(DIGITS[int(d)] for d in whole)
    else:
        spoken = _integer_to_chinese(int(whole))
    if fraction:
        spoken += "点" + "".join(DIGITS[int(d)] for d in fraction)
    return ("百分之" + spoken) if percent else spoken


def speakable(text: str) -> str:
    """Spell numbers out the way they are read aloud; speech models stumble on digits."""
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    text = re.sub(r"(?<!\d)(\d{4})(?=年)", lambda m: "".join(DIGITS[int(d)] for d in m.group(1)), text)
    return re.sub(r"(\d+)(?:\.(\d+))?(%?)", _number_to_chinese, text)
