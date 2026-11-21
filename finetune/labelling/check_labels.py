"""Check the labellers' answers for a batch, merge them, and write a page to read them on.

python check_labels.py train|eval <items dir> <answers dir> <out dir>
Prints counts only. The merged labels and the preview contain book text; keep them local.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

EMOTIONS = ["中性", "高兴", "悲伤", "愤怒", "恐惧", "厌恶", "惊讶"]
SPECIAL = {"旁白", "未知", "系统"}
mode = sys.argv[1]
items_dir, answers_dir, out_dir = map(Path, sys.argv[2:5])

answers, broken = {}, []
for path in sorted(answers_dir.glob(f"{mode}-*.jsonl")):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            answers[row["id"]] = row["labels"]
        except (ValueError, KeyError, TypeError):
            broken.append(f"{path.name} line {number}: not a valid row")

problems = list(broken)
where, emotions, kinds, per_book = Counter(), Counter(), Counter(), Counter()
flagged = unknown_ok = with_accept = invented = 0
merged = []
preview = ["# 标注数据（仅本机查看，含小说原文，不要提交）\n"]
for path in sorted(items_dir.glob("*.json")):
    item = json.loads(path.read_text(encoding="utf-8"))
    labels = answers.get(item["id"])
    if labels is None:
        problems.append(f"{item['id']}: no answer")
        continue
    want = [x["id"] for x in item["lines"]]
    try:
        by_id = {x["id"]: x for x in labels}
    except (KeyError, TypeError):
        problems.append(f"{item['id']}: labels malformed")
        continue
    if sorted(by_id) != sorted(want):
        problems.append(f"{item['id']}: line ids differ")
        continue
    passage = item["prompt"].split("\n\n", 1)[1].rsplit("\n\n", 1)[0]
    ok = True
    for n in want:
        got = by_id[n]
        speaker, emotion = got.get("speaker"), got.get("emotion")
        if not isinstance(speaker, str) or not speaker.strip() or emotion not in EMOTIONS:
            problems.append(f"{item['id']} line {n}: speaker or emotion not usable")
            ok = False
            continue
        if mode == "eval":
            got.setdefault("accept", [])
            got.setdefault("emotion_accept", [])
            got.setdefault("unsure", False)
            if not isinstance(got["accept"], list) or any(e not in EMOTIONS for e in got["emotion_accept"]):
                problems.append(f"{item['id']} line {n}: accept lists not usable")
                ok = False
                continue
            flagged += bool(got["unsure"])
            unknown_ok += "未知" in got["accept"]
            with_accept += bool(got["accept"])
        else:
            flagged += not got.get("sure", True)
        emotions[emotion] += 1
        per_book[item["book"]] += 1
        if speaker in SPECIAL:
            kinds[speaker] += 1
        else:
            kinds["有名字或称呼"] += 1
            if speaker in passage:
                where["称呼就在片段里"] += 1
            elif speaker in item["wider_text"]:
                where["只在前后文里"] += 1
            else:
                where["片段和前后文里都没有这个写法"] += 1
            invented += bool(re.search(r"[甲乙丙丁]$|[A-Z]$", speaker)) and speaker not in passage
    if not ok:
        continue
    merged.append({"id": item["id"], "book": item["book"], "labels": [by_id[n] for n in want]})

    def tag(match: re.Match, by_id: dict = by_id) -> str:
        got = by_id.get(int(match.group(1)))
        if not got:
            return match.group(0)
        extra = ""
        if mode == "eval":
            if got["accept"]:
                extra += " ｜也算对：" + "、".join(map(str, got["accept"]))
            if got["unsure"]:
                extra += " ❓不计分"
        elif not got.get("sure", True):
            extra = " ❓"
        return f"**【{match.group(1)} · {got['speaker']} · {got['emotion']}{extra}】**"

    preview.append(f"\n## {item['id']}　{item['book']}　{item['chapter']}\n")
    preview.append(re.sub(r"【(\d+)】", tag, passage).replace("\n", "\n\n"))

out_dir.mkdir(parents=True, exist_ok=True)
name = "gold.jsonl" if mode == "eval" else "labels.jsonl"
(out_dir / name).write_text(
    "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in merged), encoding="utf-8"
)
(out_dir / "preview.md").write_text("\n".join(preview) + "\n", encoding="utf-8")
total = sum(emotions.values())
print(f"{mode}: passages {len(merged)}  lines {total}  books {len(per_book)}  problems {len(problems)}")
for p in problems[:20]:
    print("  ", p)
print("lines per book: min", min(per_book.values()), "max", max(per_book.values()))
print("speaker kinds:", dict(kinds))
print("where the name is written:", dict(where))
print("names that look invented (甲/乙/A …, not in the passage):", invented)
print("emotions:", {e: emotions[e] for e in EMOTIONS})
if mode == "eval":
    print(
        f"left out of scoring (unsure): {flagged}   "
        f"lines with other accepted answers: {with_accept}   accepting 未知: {unknown_ok}"
    )
else:
    print("lines the labeller was not sure of:", flagged)
