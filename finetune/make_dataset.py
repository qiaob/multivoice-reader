"""Write synthetic training data for the "who says each line, and how" task.

Scenes are composed from pools.py by rule, so every label is known by construction rather
than guessed by another model. Each scene goes through the reader's own segmenter and
request builder, so the examples have exactly the shape the model sees when reading a book.

    PYTHONPATH=src python finetune/make_dataset.py            # 10000 train, 300 valid, 500 test

Output: finetune/data/{train,valid,test}.jsonl, one {"messages": [user, assistant]} per line.
Stdlib only.
"""

import argparse
import json
import random
from pathlib import Path

import pools

from multivoice_reader.analyze import EMOTIONS, NARRATOR, SHORT_LABEL_PROMPT, label_batches, label_request
from multivoice_reader.text import split_segments

OUT = Path(__file__).parent / "data"
NEUTRAL = "中性"
FEELINGS = [e for e in EMOTIONS if e != NEUTRAL]
SYSTEM = "系统"


class Scene:
    """A short scene under construction: its paragraphs, and who says each quote in order."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.open_quote, self.close_quote = rng.choices([("“", "”"), ("「", "」")], weights=[85, 15])[0]
        self.paragraphs: list[str] = []
        self.labels: list[tuple[str, str]] = []
        self.cast = [self.new_character() for _ in range(rng.choice([2, 2, 2, 3, 3, 4]))]
        self.names = [c["name"] for c in self.cast]

    # ---- people ----
    def new_character(self) -> dict:
        rng = self.rng
        male = rng.random() < 0.6
        surname = rng.choice(pools.COMPOUND_SURNAMES) if rng.random() < 0.06 else rng.choice(pools.SURNAMES)
        name = surname + rng.choice(pools.MALE_GIVEN if male else pools.FEMALE_GIVEN)
        return {"name": name, "pronoun": "他" if male else "她", "alias": None, "surname": surname}

    def ref(self, person: dict) -> str:
        """How the narration names someone: usually the name, sometimes an established title."""
        if person["alias"] and self.rng.random() < 0.6:
            return person["alias"]
        return person["name"]

    # ---- text ----
    def quote(self, text: str) -> str:
        return f"{self.open_quote}{text}{self.close_quote}"

    def line(self, emotion: str, address: dict | None = None) -> str:
        rng = self.rng
        text = rng.choice(pools.LINES[emotion])
        if emotion == NEUTRAL:
            text = rng.choice(pools.OPENERS) + text
        if address:  # a name inside the quote is who is spoken to, not who speaks
            text = f"{self.ref(address)}，{text}"
        return text

    def say(self, speaker: str, emotion: str, text: str) -> str:
        self.labels.append((speaker, emotion))
        return self.quote(text)

    def narration(self) -> str:
        rng = self.rng
        if rng.random() < 0.4:
            return f"{self.ref(rng.choice(self.cast))}{rng.choice(pools.ACTIONS)}。"
        return rng.choice(pools.NARRATION)

    # ---- one turn of talk, in one of the ways novels write it ----
    def tagged_turn(self, person: dict, other: dict) -> None:
        rng = self.rng
        emotion = rng.choice(FEELINGS) if rng.random() < 0.35 else NEUTRAL
        name, who = person["name"], self.ref(person)
        address = other if rng.random() < 0.15 else None
        text = self.line(emotion, address)
        pre = rng.choice(pools.EMOTION_PRE[emotion]) if emotion != NEUTRAL else rng.choice(pools.SAY)
        post = rng.choice(pools.EMOTION_POST[emotion]) if emotion != NEUTRAL else rng.choice(pools.SAY_POST)
        form = rng.choices(
            ["pre", "post", "mid", "action", "pronoun", "trap", "thought"], weights=[30, 24, 8, 12, 8, 8, 10]
        )[0]
        if form == "pre":
            para = f"{who}{pre}：{self.say(name, emotion, text)}"
            if rng.random() < 0.25:
                para += rng.choice(pools.NARRATION)
        elif form == "post":
            para = f"{self.say(name, emotion, text)}{who}{post}。"
        elif form == "mid":
            first, second = self.line(emotion, address).rstrip("。！？…") + "，", self.line(emotion)
            verb = pre.rstrip("，说问道")
            para = f"{self.say(name, emotion, first)}{who}{verb}，{self.say(name, emotion, second)}"
        elif form == "action":  # an action sentence, then the quote, no speech verb at all
            emotion, text = NEUTRAL, self.line(NEUTRAL, address)
            para = f"{who}{rng.choice(pools.ACTIONS)}。{self.say(name, emotion, text)}"
        elif form == "pronoun":
            para = (
                f"{who}{rng.choice(pools.ACTIONS)}，{person['pronoun']}{pre}：{self.say(name, emotion, text)}"
            )
        elif form == "trap":  # someone else is mentioned first; the tag after the quote decides
            para = (
                f"{self.ref(other)}{rng.choice(pools.ACTIONS)}。{self.say(name, emotion, text)}{who}{post}。"
            )
        else:  # a thought counts as that character speaking, neutrally
            text = self.line(NEUTRAL)
            if rng.random() < 0.5:
                para = f"{who}{rng.choice(pools.THOUGHT_PRE)}：{self.say(name, NEUTRAL, text)}"
            else:
                para = f"{self.say(name, NEUTRAL, text)}{who}{rng.choice(pools.THOUGHT_POST)}。"
        self.paragraphs.append(para)

    def bare_turn(self, person: dict) -> None:
        """A quote alone in its paragraph: the speakers are taking turns."""
        self.paragraphs.append(self.say(person["name"], NEUTRAL, self.line(NEUTRAL)))

    def interruption(self) -> None:
        """Something other than the main characters speaks; turn-taking starts over afterwards."""
        rng = self.rng
        kind = rng.choices(["group", "unnamed", "sound", "system"], weights=[35, 35, 20, 10])[0]
        if kind == "group":
            group = rng.choice(pools.GROUPS)
            self.paragraphs.append(f"{group}{rng.choice(pools.GROUP_VERBS)}。")
            for _ in range(rng.randint(2, 4)):
                emotion = rng.choice([NEUTRAL, NEUTRAL, "惊讶"])
                self.paragraphs.append(self.say(group, emotion, self.line(emotion)))
        elif kind == "unnamed":
            who = rng.choice(pools.UNNAMED)
            emotion = rng.choice(FEELINGS) if rng.random() < 0.3 else NEUTRAL
            tag = rng.choice(pools.EMOTION_PRE[emotion]) if emotion != NEUTRAL else rng.choice(pools.SAY)
            article = rng.choice(["一个", "一名", "那个", "旁边的", ""])
            self.paragraphs.append(f"{article}{who}{tag}：{self.say(who, emotion, self.line(emotion))}")
        elif kind == "sound":
            sound = self.say(NARRATOR, NEUTRAL, rng.choice(pools.SOUNDS))
            self.paragraphs.extend(rng.sample([sound, rng.choice(pools.SOUND_NARRATION)], 2))
        else:
            tag = rng.choice(["系统的提示音响起：", "系统冰冷的声音在脑海里响起：", "耳边传来系统的声音："])
            self.paragraphs.append(f"{tag}{self.say(SYSTEM, NEUTRAL, rng.choice(pools.SYSTEM_LINES))}")

    def write(self) -> None:
        rng = self.rng
        if rng.random() < 0.2:  # establish a title for one character, used in place of the name later
            person = rng.choice(self.cast)
            person["alias"] = person["surname"] + rng.choice(pools.TITLES)
            self.paragraphs.append(f"{person['alias']}{person['name']}{rng.choice(pools.ACTIONS)}。")
        for _ in range(rng.randint(0, 2)):
            self.paragraphs.append(self.narration())
        a, b = rng.sample(self.cast, 2)
        bare_run, tagged_since_reset = 0, 0
        for _ in range(rng.randint(5, 13)):
            roll = rng.random()
            if roll < 0.08:
                self.interruption()
                bare_run = tagged_since_reset = 0
            elif roll < 0.16 and len(self.cast) > 2:  # a third person joins; turn-taking starts over
                b = rng.choice([c for c in self.cast if c is not a])
                self.tagged_turn(b, a)
                a, b = b, a
                bare_run, tagged_since_reset = 0, 1
            elif tagged_since_reset >= 2 and bare_run < 3 and roll < 0.55:
                self.bare_turn(a)
                a, b = b, a
                bare_run += 1
            else:
                self.tagged_turn(a, b)
                a, b = b, a
                bare_run = 0
                tagged_since_reset += 1
            if rng.random() < 0.22:
                self.paragraphs.append(self.narration())


def examples(seed: int) -> list[dict]:
    rng = random.Random(seed)
    scene = Scene(rng)
    scene.write()
    segments = split_segments(scene.paragraphs)
    lines = [i for i, s in enumerate(segments) if s.kind == "dialogue"]
    if len(lines) != len(scene.labels):  # a quote was cut or merged differently than intended
        return []
    label_of = dict(zip(lines, scene.labels, strict=True))
    out = []
    for batch in label_batches(segments):
        roll = rng.random()
        known = (
            list(scene.names) if roll < 0.7 else rng.sample(scene.names, rng.randint(0, len(scene.names) - 1))
        )
        if any(c["alias"] for c in scene.cast):
            known = list(scene.names)  # a title can only be resolved to a name that is known
        known += [Scene(rng).names[0] for _ in range(rng.choice([0, 0, 1, 2]))]  # people not in this scene
        rng.shuffle(known)
        prompt, numbers = label_request(segments, batch, known, SHORT_LABEL_PROMPT)
        answer = [{"id": n, "speaker": label_of[i][0], "emotion": label_of[i][1]} for i, n in numbers.items()]
        out.append(
            {
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
                ]
            }
        )
    return out


def write_split(name: str, count: int, first_seed: int) -> int:
    rows, seen, seed = [], set(), first_seed
    while len(rows) < count:
        for row in examples(seed):
            if row["messages"][0]["content"] not in seen and len(rows) < count:
                seen.add(row["messages"][0]["content"])
                rows.append(row)
        seed += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return seed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=int, default=10000)
    parser.add_argument("--valid", type=int, default=300)
    parser.add_argument("--test", type=int, default=500)
    args = parser.parse_args()
    seed = 0
    for name, count in (("train", args.train), ("valid", args.valid), ("test", args.test)):
        seed = write_split(name, count, seed + 1_000_000)  # splits never share a scene
        print(f"{name}: {count} examples")


if __name__ == "__main__":
    main()
