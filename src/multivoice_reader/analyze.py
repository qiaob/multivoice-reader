"""Who says each line, and how: a small local language model labels the dialogue.

The model never rewrites the text. It only answers, per numbered line of dialogue, with a
speaker name and one emotion, so a wrong answer costs a wrong voice and nothing else.
"""

import json
import re
from pathlib import Path

from .script import AGES, EMOTIONS, GENDERS, NARRATOR, UNKNOWN
from .text import Segment

# The models that can do the labelling, best first. `adapter` names a folder in models/: LoRA
# weights fine-tuned on this task, which only fit that base. How each one scores is in
# finetune/RESULTS.md.
MODELS = {
    "qwen3.5-4b": {
        "base": "mlx-community/Qwen3.5-4B-MLX-4bit",
        "adapter": "qwen3.5-4b",
        "about": "Qwen3.5-4B 微调版：最准，下载 2.9 GB",
    },
    "qwen3-1.7b": {
        "base": "mlx-community/Qwen3-1.7B-4bit",
        "adapter": "qwen3-1.7b",
        "about": "Qwen3-1.7B 微调版：最快最省内存，下载 0.9 GB",
    },
    "qwen3.5-9b": {
        "base": "mlx-community/Qwen3.5-9B-MLX-4bit",
        "adapter": None,
        "about": "Qwen3.5-9B 未微调：下载 5.6 GB",
    },
}
DEFAULT_MODEL = "qwen3.5-4b"
ADAPTERS = Path(__file__).parent / "models"
LINES_PER_ASK = 8  # dialogue lines labelled in one request
CONTEXT_PARAGRAPHS = 3  # narration shown before the first line of a request
PROFILE_EXCERPT_CHARS = 3500

LABEL_PROMPT = """下面是一段小说，对白前面标了编号【n】。

已知角色：{known}

片段：
{excerpt}

请判断每句带编号的对白是谁说的、带着什么情绪。

判断说话人的方法：
- 对白前后的叙述通常会点明说话人：前面有“张三说：”，或者后面紧跟“李四冷笑一声”，说话的就是张三、李四。
- 两个人对话时，通常一人一句轮流说。
- 同一个人可能有不同的叫法（名字、称号、外貌描述）。能确定是同一个人时，用已知角色里的那个名字。
- speaker 写角色的名字；心里想的话算这个角色说的；不是人说的声音（拟声词、兽吼、铃声）写“旁白”；实在判断不出来写“未知”。

判断情绪的方法：
- emotion 只能从这几个里选一个：{emotions}。
- 要保守。平常说话、提问、打招呼、一般的感叹都是“中性”。
- 只有叙述里明确写了情绪（怒喝、冷笑、哭着说、大笑、吓得发抖），或者这句话本身语气非常强烈时，才选别的。

只输出 JSON 数组，每个编号一项，不要解释。例如：
[{{"id": 1, "speaker": "张三", "emotion": "愤怒"}}]"""

# A model fine-tuned on this task (see finetune/) has learnt the rules, so it gets only the facts.
SHORT_LABEL_PROMPT = """已知角色：{known}

{excerpt}

标出每句带编号的对白是谁说的、带着什么情绪。可选的情绪：{emotions}。"""

PROFILE_PROMPT = """下面是一段小说。

{excerpt}

请根据这段内容，判断这些角色的性别和年龄段：{names}
- gender 只能是：{genders}
- age 只能是：{ages}（儿童 12 岁以下，少年 13 到 19 岁，青年 20 到 35 岁，中年 36 到 59 岁，老年 60 岁以上）
只输出 JSON 对象，不要解释。例如：
{{"张三": {{"gender": "男", "age": "青年"}}}}"""


def _first_json(text: str, opener: str, closer: str):
    """The model sometimes wraps its answer in prose or a code fence; take the JSON inside."""
    start, end = text.find(opener), text.rfind(closer)
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except ValueError:
        return None


def _profile_in(answer: str, name: str) -> dict:
    """What the answer says about one character. Looked up by name, not parsed whole, because
    a small model may write one object per line instead of a single one."""
    found = re.search(r'"%s"\s*:\s*(\{[^{}]*\})' % re.escape(name), answer)
    try:
        return json.loads(found.group(1)) if found else {}
    except ValueError:
        return {}


def _clean_name(name) -> str:
    name = re.sub(r"[（(【\[].*$", "", str(name or "")).strip(" 　\"“”'：:")
    return name[:12] or UNKNOWN


def label_batches(segments: list[Segment]) -> list[list[int]]:
    """Indices of the dialogue segments, in the groups they are asked about."""
    lines = [i for i, s in enumerate(segments) if s.kind == "dialogue"]
    return [lines[at : at + LINES_PER_ASK] for at in range(0, len(lines), LINES_PER_ASK)]


def label_request(
    segments: list[Segment], batch: list[int], known: list[str], template: str = LABEL_PROMPT
) -> tuple[str, dict[int, int]]:
    """The prompt for one group of lines, and which number each segment index was given.

    Training data is built with this same function, so a fine-tuned model sees at inference
    exactly what it was trained on.
    """
    first_para = segments[batch[0]].para - CONTEXT_PARAGRAPHS
    last_para = segments[batch[-1]].para + 1
    numbers = {index: n + 1 for n, index in enumerate(batch)}
    excerpt, para = [], None
    for i, seg in enumerate(segments):
        if not first_para <= seg.para <= last_para:
            continue
        if seg.para != para:
            excerpt.append("\n")
            para = seg.para
        if seg.kind == "narration":
            excerpt.append(seg.text)
        elif i in numbers:
            excerpt.append(f"【{numbers[i]}】“{seg.text}”")
        else:
            excerpt.append(f"“{seg.text}”")
    prompt = template.format(
        known="、".join(known) or "暂无", excerpt="".join(excerpt).strip(), emotions="、".join(EMOTIONS)
    )
    return prompt, numbers


def chat_prompt(tokenizer, prompt: str) -> str:
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        add_generation_prompt=True,
        tokenize=False,
        enable_thinking=False,  # models that can deliberate first would spend the budget on it
    )


class Analyzer:
    def __init__(self, name: str = DEFAULT_MODEL):
        """`name` is one of MODELS; ValueError if it is not."""
        if name not in MODELS:
            raise ValueError(f"没有「{name}」这个模型，可以用的有：{'、'.join(MODELS)}")
        from mlx_lm import load
        from mlx_lm.tuner.lora import LoRALinear

        about = MODELS[name]
        adapter = str(ADAPTERS / about["adapter"]) if about["adapter"] else None
        self.model, self.tokenizer = load(about["base"], adapter_path=adapter)
        # An adapter means the model was fine-tuned on the short prompt; see finetune/.
        self.template = SHORT_LABEL_PROMPT if adapter else LABEL_PROMPT
        self.tuned = [(m, m.scale) for _, m in self.model.named_modules() if isinstance(m, LoRALinear)]

    def ask(self, prompt: str, max_tokens: int, tuned: bool = True) -> str:
        """The model's answer. `tuned=False` asks the model as it was before fine-tuning: the
        fine-tuned one has learnt to answer everything as if it were asked to label lines."""
        from mlx_lm import generate

        text = chat_prompt(self.tokenizer, prompt)
        for layer, scale in self.tuned:
            layer.scale = scale if tuned else 0.0
        try:
            return generate(self.model, self.tokenizer, prompt=text, max_tokens=max_tokens, verbose=False)
        finally:
            for layer, scale in self.tuned:
                layer.scale = scale

    def label(self, segments: list[Segment], known: list[str]) -> list[dict]:
        """One {"speaker", "emotion"} per segment; narration is the narrator, neutral."""
        labels = [{"speaker": NARRATOR, "emotion": "中性"} for _ in segments]
        known = list(known)
        for batch in label_batches(segments):
            prompt, numbers = label_request(segments, batch, known, self.template)
            answer = self.ask(prompt, max_tokens=40 * len(batch) + 40)
            by_number = {}
            for item in _first_json(answer, "[", "]") or []:
                if isinstance(item, dict) and isinstance(item.get("id"), int):
                    by_number[item["id"]] = item
            for index, number in numbers.items():
                item = by_number.get(number, {})
                speaker = _clean_name(item.get("speaker"))
                emotion = item.get("emotion") if item.get("emotion") in EMOTIONS else "中性"
                labels[index] = {"speaker": speaker, "emotion": emotion}
                if speaker != UNKNOWN and speaker not in known:
                    known.append(speaker)
        return labels

    def profiles(self, segments: list[Segment], names: list[str]) -> dict[str, dict]:
        """Gender and age band for characters met for the first time."""
        if not names:
            return {}
        excerpt = "\n".join(s.text if s.kind == "narration" else f"“{s.text}”" for s in segments)
        answer = self.ask(
            PROFILE_PROMPT.format(
                excerpt=excerpt[:PROFILE_EXCERPT_CHARS],
                names="、".join(names),
                genders="、".join(GENDERS),
                ages="、".join(AGES),
            ),
            max_tokens=30 * len(names) + 40,
            tuned=False,
        )
        out = {}
        for name in names:
            item = _profile_in(answer, name)
            out[name] = {
                "gender": item.get("gender") if item.get("gender") in GENDERS else UNKNOWN,
                "age": item.get("age") if item.get("age") in AGES else UNKNOWN,
            }
        return out
