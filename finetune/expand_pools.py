"""Have a local language model write original sentences for the scene pools.

The hand-written pools.py is small: a few hundred lines recombined ten thousand times. This
asks a model for many more lines of dialogue (by emotion), narration and actions, across
genres and situations, and saves them next to pools.py, which picks them up on import.

    uv run --no-project --python 3.11 --with mlx-lm python finetune/expand_pools.py

Safe to stop and run again: it continues from what is already saved.
Output: finetune/pools_generated.json
"""

import json
import random
import re
import time
from pathlib import Path

from mlx_lm import generate, load
from mlx_lm.sample_utils import make_sampler

OUT = Path(__file__).with_name("pools_generated.json")
MODEL = "mlx-community/Qwen3.5-4B-MLX-4bit"
PER_ASK = 25
MAX_ASKS = 700

GENRES = (
    "修仙玄幻 都市职场 历史古风 悬疑推理 科幻 校园青春 武侠江湖 乡村生活 末世求生 军旅 宫廷权谋 游戏电竞"
).split()
SITUATIONS = (
    "争吵 告别 谈判 求助 闲聊 审问 表白 庆功 逃亡 探病 交易 训话 "
    "重逢 对峙 安慰 密谋 道歉 拜师 比试 赶路 吃饭 开会 报信 搜查"
).split()
TONES = {
    "中性": "平常说话，不带明显情绪",
    "高兴": "高兴、兴奋或得意",
    "悲伤": "悲伤、难过或绝望",
    "愤怒": "愤怒、暴躁或威胁",
    "恐惧": "害怕、慌张或求饶",
    "厌恶": "嫌弃、讥讽或不屑",
    "惊讶": "惊讶、难以置信",
}
TARGETS = {"中性": 2400, "高兴": 450, "悲伤": 450, "愤怒": 450, "恐惧": 450, "厌恶": 450, "惊讶": 450}
NARRATION_TARGET, ACTION_TARGET = 700, 450
RULES = (
    '全部原创，不要引用任何已有的作品。句子之间不要重复，长短要有变化。只输出 JSON 数组，例如 ["……", "……"]。'
)

DIALOGUE = """你在为小说写对白素材。题材：{genre}。情境：{situation}。
请写 {n} 句人物说的话，语气是：{tone}。
要求：每句 4 到 30 个字；不要出现任何人名；不要带引号；每句以句号、问号、感叹号或省略号结尾。
{rules}"""
NARRATION = """你在为小说写旁白素材。题材：{genre}。情境：{situation}。
请写 {n} 句叙述句，描写环境、气氛、时间或场面。
要求：每句 8 到 40 个字；不要出现任何人物、人名和对白；每句以句号结尾。
{rules}"""
ACTION = """你在为小说写动作素材。题材：{genre}。情境：{situation}。
请写 {n} 个人物的动作短语，前面可以直接接人名，比如“放下手里的茶杯”“往门口看了一眼”。
要求：每个 4 到 12 个字；没有主语；不带任何标点；不要是说话的动作。
{rules}"""

BANNED = re.compile(r"[“”\"「」『』\n【】（）()《》]")


def keep_dialogue(text: str) -> bool:
    return 4 <= len(text) <= 32 and text[-1] in "。？！…" and not BANNED.search(text)


def keep_narration(text: str) -> bool:
    return 8 <= len(text) <= 42 and text.endswith("。") and not BANNED.search(text) and "：" not in text


def keep_action(text: str) -> bool:
    return (
        4 <= len(text) <= 12
        and not re.search(r"[，。！？…：；、\s说道问喊叫]", text)
        and not BANNED.search(text)
    )


def main() -> None:
    saved = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    lines = {tone: set(saved.get("lines", {}).get(tone, [])) for tone in TONES}
    narration, actions = set(saved.get("narration", [])), set(saved.get("actions", []))
    model, tokenizer = load(MODEL)
    sampler = make_sampler(temp=0.9, top_p=0.95)
    rng = random.Random(len(narration) + sum(map(len, lines.values())))
    for ask in range(MAX_ASKS):
        # Work on whatever is furthest from its target.
        wanted = {tone: 1 - len(lines[tone]) / TARGETS[tone] for tone in TONES}
        wanted["narration"] = 1 - len(narration) / NARRATION_TARGET
        wanted["action"] = 1 - len(actions) / ACTION_TARGET
        kind = max(wanted, key=wanted.get)
        if wanted[kind] <= 0:
            break
        fill = {
            "genre": rng.choice(GENRES),
            "situation": rng.choice(SITUATIONS),
            "n": PER_ASK,
            "rules": RULES,
        }
        if kind == "narration":
            prompt, keep, bucket = NARRATION.format(**fill), keep_narration, narration
        elif kind == "action":
            prompt, keep, bucket = ACTION.format(**fill), keep_action, actions
        else:
            prompt, keep, bucket = DIALOGUE.format(tone=TONES[kind], **fill), keep_dialogue, lines[kind]
        text = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            add_generation_prompt=True,
            tokenize=False,
            enable_thinking=False,
        )
        started = time.time()
        answer = generate(model, tokenizer, prompt=text, max_tokens=1100, sampler=sampler, verbose=False)
        try:
            items = json.loads(answer[answer.find("[") : answer.rfind("]") + 1])
        except ValueError:
            items = re.findall(r'"([^"\n]+)"', answer)  # a cut-off array still has usable items
        before = len(bucket)
        bucket.update(t.strip() for t in items if isinstance(t, str) and keep(t.strip()))
        OUT.write_text(
            json.dumps(
                {
                    "lines": {tone: sorted(lines[tone]) for tone in TONES},
                    "narration": sorted(narration),
                    "actions": sorted(actions),
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        have = " ".join(f"{tone}{len(lines[tone])}" for tone in TONES)
        print(
            f"{ask + 1:>3} {kind:<9} +{len(bucket) - before:<3} in {time.time() - started:4.0f}s | {have} "
            f"旁白{len(narration)} 动作{len(actions)}",
            flush=True,
        )


if __name__ == "__main__":
    main()
