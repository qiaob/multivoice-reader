"""Write what the Python reader does with a batch of inputs, for the Kotlin port to match.

    PYTHONPATH=src python3 android/tools/make_golden.py

The inputs are the raw text around the real-novel test passages (finetune/data/real), plus
the cases in tests/. The language model is replaced by `fake_model`, which the Kotlin tests
copy line for line, so the prompts asked and everything done with the answers can be
compared exactly. Run it again whenever the Python side changes.
"""

import json
import re
from pathlib import Path

from multivoice_reader import analyze, split
from multivoice_reader.casting import GENRES, assign, narrator_voice
from multivoice_reader.script import AGES, EMOTIONS, GENDERS, dumps, normalize
from multivoice_reader.text import speakable, split_chapters, split_segments
from multivoice_reader.voices import Voice

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "android" / "core" / "src" / "test" / "resources" / "golden"
NAMES = ["张三", "李四（冷笑）", '"王五"', "", None, "某个名字特别特别长的角色啊真的很长", "系统"]


def fake_model(prompt: str, max_tokens: int, tuned: bool) -> str:
    size = len(prompt)
    if tuned:
        items = []
        for n in (int(x) for x in re.findall(r"【(\d+)】“", prompt)):
            if n % 9 == 8:
                continue  # an answer that leaves a line out
            items.append(
                {
                    "id": n,
                    "speaker": NAMES[(n + size) % len(NAMES)],
                    "emotion": (EMOTIONS + ["狂喜"])[(n * 3 + size) % 8],
                }
            )
        body = json.dumps(items, ensure_ascii=False)
        return ["", "好的：\n", "```json\n"][size % 3] + body + ["", "\n```", "\n以上。"][size % 3]
    names = re.search(r"判断这些角色的性别和年龄段：(.*)\n", prompt).group(1).split("、")
    about = {
        name: {"gender": (GENDERS + ["x"])[(i + size) % 4], "age": AGES[(i * 2 + size) % 6]}
        for i, name in enumerate(names)
    }
    if size % 2 == 0:
        return json.dumps(about, ensure_ascii=False)
    return "\n".join(json.dumps({name: value}, ensure_ascii=False) for name, value in about.items())


class FakeAnalyzer(analyze.Analyzer):
    def __init__(self):  # no model is loaded
        self.asked = []

    def ask(self, prompt: str, max_tokens: int, tuned: bool = True) -> str:
        answer = fake_model(prompt, max_tokens, tuned)
        self.asked.append({"prompt": prompt, "max_tokens": max_tokens, "tuned": tuned, "answer": answer})
        return answer


def passages() -> list[dict]:
    found = []
    for name in ("test.jsonl", "test_old.jsonl", "valid.jsonl"):
        for line in (ROOT / "finetune" / "data" / "real" / name).read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            found.append({"id": item["id"], "chapter": item["chapter"], "text": item["wider_text"]})
    return found[::4][:50]  # a spread over the books, small enough to keep in git


def main(out: Path = OUT) -> None:
    def write(name: str, data) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    texts = passages()

    # Cutting text: segments of each passage, and every segment as it is spoken.
    segment_cases = []
    for item in texts:
        paragraphs = [p.strip() for p in item["text"].splitlines() if p.strip()]
        segments = split_segments(paragraphs)
        segment_cases.append(
            {
                "paragraphs": paragraphs,
                "segments": [
                    {"kind": s.kind, "text": s.text, "para": s.para, "spoken": speakable(s.text)}
                    for s in segments
                ],
            }
        )
    write("segments.json", segment_cases)

    # Cutting a novel into chapters: the passages as one book, and a few awkward ones.
    names = [re.sub(r"^第.*?章\s*", "", item["chapter"]) for item in texts]
    novel = "书名：测试\n作者：某人\n简介一行\n\n" + "\n".join(
        f"第{i + 1}章 {name}\n{item['text']}" for i, (name, item) in enumerate(zip(names, texts, strict=True))
    )
    awkward = [
        "书名\n简介一行\n\n卷一 第1章 开端\n  第一段。\n第二段。\n第2章 这家伙是谁？\n第三段。\n",
        "\n".join(["这是一段没有章节标题的文字。" * 20] * 30),
        "第1章：迁徙\r\n第一段。\r\n第二章、归来 第二段。\x0c第三段\n",
        "\n".join(f"第{i}章 标题\n本站推荐各位书友阅读这本书\n这是第{i}章的正文。" for i in range(1, 15)),
        "\n".join(f"这是没有被认出标题的前几章里的第{i}段正文，讲了很多事情。" for i in range(400))
        + "\n第181章 后来\n最后一段。\n",
        "　　第十二回　　大闹天宫　\n　　正文 \n",
    ]
    write(
        "chapters.json",
        [
            {
                "text": text,
                "chapters": [{"title": c.title, "paragraphs": c.paragraphs} for c in split_chapters(text)],
            }
            for text in [novel, *awkward]
        ],
    )

    # Numbers as they are read.
    numbers = [
        "第1章",
        "第12章 第105章 第3253章",
        "涨了3.5%，共20000人，1010次",
        "2024年的10个徒弟",
        "一共100000001块",
        "电话13800138000123",
        "０１２３年",
        "100010000",
        "第٣章",
        "3.14159",
        "10.%",
    ]
    write("speakable.json", [{"text": t, "spoken": speakable(t)} for t in numbers])

    # Splitting: every chapter of the passages through the labelling, one book's characters.
    analyzer, characters, chapters = FakeAnalyzer(), {}, []
    for case in segment_cases:
        lines = split.split_chapter(case["paragraphs"], characters, analyzer)
        chapters.append({"title": f"第 {len(chapters) + 1} 章", "lines": lines})
    write("split.json", {"asked": analyzer.asked, "chapters": chapters, "characters": characters})

    # The reading script made from it, as written to a file.
    script = normalize({"title": " 测试书 ", "characters": characters, "chapters": chapters})
    write("script.json", {"title": " 测试书 ", "dumps": dumps(script)})  # input: split.json

    # Casting with the voices that come with the reader.
    voices = {}
    for path in sorted((ROOT / "src" / "multivoice_reader" / "voices").glob("*/voice.json")):
        about = json.loads(path.read_text(encoding="utf-8"))
        voices[path.parent.name] = Voice(
            path.parent.name,
            about["name"],
            about["gender"],
            about["age"],
            about["kind"],
            about.get("desc", ""),
            path.parent / about["ref_audio"],
            about["ref_text"],
            genre=about.get("genre", ""),
        )
    voices["mine"] = Voice("mine", "我的", "男", "青年", "clone", "", Path("x.wav"), "x", own=True)
    profiles = {name: {"gender": a["gender"], "age": a["age"]} for name, a in script["characters"].items()}
    extra = {f"路人{i}": {"gender": GENDERS[i % 3], "age": AGES[i % 6]} for i in range(40)}
    casting = []
    for genre in ["", *GENRES]:
        casting.append(
            {
                "genre": genre,
                "narrator": narrator_voice(voices, genre),
                "assigned": assign({**profiles, **extra}, voices, {}, None, genre),
                "kept": assign(
                    {**profiles, **extra}, voices, {"路人3": "mine", "路人4": "gone"}, "m_cold", genre
                ),
            }
        )
    write(
        "casting.json",
        {
            "voices": [
                {k: getattr(v, k) for k in ("id", "name", "gender", "age", "kind", "genre")}
                for v in voices.values()
            ],
            "characters": {**profiles, **extra},
            "cases": casting,
        },
    )


if __name__ == "__main__":
    main()
