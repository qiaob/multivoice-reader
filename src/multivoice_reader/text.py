"""Plain text in, chapters and speakable segments out. Rules only, no models."""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# "第12章 标题", "第十二回", "第12章：标题", optionally after a short volume name: "卷名 第12章 标题".
HEADING = re.compile(
    r"^\s*(?:[^\s，。！？：“”]{1,12}\s+)?第\s*[0-9０-９零〇一二三四五六七八九十百千两]+\s*[章回节卷]"
    r"(?:[\s：:、．.—-]+.{0,40})?\s*$"
)
# A line this long that recurs this often is not the story: it is a site's watermark.
WATERMARK_MIN_CHARS, WATERMARK_MAX_CHARS = 8, 40
WATERMARK_MIN_REPEATS = 10
# The ways dialogue is quoted: curly quotes, corner brackets, and straight quotes, which
# have no open and close forms and so are paired up in order within a paragraph.
QUOTED = re.compile(r"“([^“”]*)”|「([^「」]*)」|『([^『』]*)』|\"([^\"]*)\"")


def quoted_text(match: re.Match) -> str:
    """What is between the quotation marks, whichever kind they are."""
    return next(group for group in match.groups() if group is not None)


SENTENCE_END = "。！？…!?"
# What a quoted span ends with when it is speech rather than a quoted term in the narration.
SPEECH_END = SENTENCE_END + "，、；—～~.,"
FALLBACK_CHAPTER_CHARS = 3000
FRONT_MATTER_MAX_CHARS = 6000  # more than this before the first heading is story, not a blurb
NARRATION_CHARS = 70
DIALOGUE_CHARS = 120


@dataclass
class Chapter:
    title: str
    paragraphs: list[str]


@dataclass
class Segment:
    kind: str  # "narration", "dialogue", or "system": what a novel's "system" announces
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


def _by_size(lines: list[str], label: str) -> list[Chapter]:
    """Cut text that has no headings into pieces of roughly equal size at paragraph breaks."""
    chapters: list[Chapter] = []
    size = 0
    for line in lines:
        if not chapters or size >= FALLBACK_CHAPTER_CHARS:
            chapters.append(Chapter(f"{label}第 {len(chapters) + 1} 段", []))
            size = 0
        chapters[-1].paragraphs.append(line)
        size += len(line)
    return chapters


def split_chapters(text: str) -> list[Chapter]:
    """Split on chapter headings.

    A little text before the first heading is a blurb or credits and is dropped. A lot of it
    is story whose headings were not recognised, and is kept, cut by size. So is a text with
    no headings at all.
    """
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    repeats = Counter(
        line
        for line in lines
        if WATERMARK_MIN_CHARS <= len(line) <= WATERMARK_MAX_CHARS and not QUOTED.search(line)
    )
    watermarks = {line for line, count in repeats.items() if count >= WATERMARK_MIN_REPEATS}
    lines = [line for line in lines if line not in watermarks]
    front: list[str] = []
    chapters: list[Chapter] = []
    for line in lines:
        if HEADING.match(line):
            chapters.append(Chapter(re.sub(r"\s+", " ", line), []))
        elif chapters:
            chapters[-1].paragraphs.append(line)
        else:
            front.append(line)
    if not chapters:
        return _by_size(front, "")
    chapters = [c for c in chapters if c.paragraphs]
    if sum(map(len, front)) > FRONT_MATTER_MAX_CHARS:
        chapters = _by_size(front, "开头 ") + chapters
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


# A paragraph that is nothing but 【…】 is the system speaking: 【叮！获得能力：仙师天眼】.
SYSTEM_TEXT = re.compile(r"(?:【[^【】]+】\s*)+")
# Unless it is the author talking to the readers, which is set off the same way.
AUTHOR_NOTE = re.compile(r"求收藏|求推荐|求月票|求订阅|求打赏|新书|加更|更新|作者|[Pp][Ss][:：]")


def split_segments(paragraphs: list[str]) -> list[Segment]:
    """Cut paragraphs into narration, dialogue and system announcements, in reading order."""
    segments: list[Segment] = []
    for index, para in enumerate(paragraphs):
        if SYSTEM_TEXT.fullmatch(para) and not AUTHOR_NOTE.search(para):
            segments.extend(Segment("system", c, index) for c in _chunks(para, NARRATION_CHARS))
            continue
        narration = ""
        cursor = 0

        def flush(index: int = index) -> None:
            nonlocal narration
            if re.search(r"\w", narration):
                segments.extend(Segment("narration", c, index) for c in _chunks(narration, NARRATION_CHARS))
            narration = ""

        for match in QUOTED.finditer(para):
            inner = quoted_text(match)
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
