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
# Longer examples would be cut off in training and lose their answer (--max-seq-length in train.py).
MAX_EXAMPLE_CHARS = 1500


# Layout habits seen across real novels (finetune/profile_layout.py), as families a scene is
# drawn from.
#   lone       how often a quote is a paragraph by itself, the speaker named above or below
#   forms      when it is not, how the turn is written (weights for FORMS)
#   bare       how often speakers simply take turns, with nothing naming them
#   merge      how often a turn continues the previous paragraph
#   before, after   narration sentences put in the turn's own paragraph (fewest, most)
#   narration  sentences in a paragraph of pure narration (fewest, most)
FORMS = ["pre", "post", "mid", "action", "pronoun", "trap", "thought"]
STYLES = {
    # Most quotes stand alone; otherwise 他说："……". Short paragraphs.
    "web_lone": {
        "lone": 0.75,
        "forms": [60, 8, 4, 14, 6, 4, 4],
        "bare": 0.45,
        "merge": 0.0,
        "before": (0, 0),
        "after": (0, 0),
        "narration": (1, 2),
    },  # fmt: skip
    # An even mix of all placements.
    "web_mixed": {
        "lone": 0.40,
        "forms": [30, 30, 10, 10, 8, 6, 6],
        "bare": 0.35,
        "merge": 0.2,
        "before": (0, 0),
        "after": (0, 1),
        "narration": (1, 2),
    },  # fmt: skip
    # Long paragraphs that open with the quote: "……"他说。然后……
    "quote_first": {
        "lone": 0.05,
        "forms": [8, 70, 8, 4, 2, 4, 4],
        "bare": 0.08,
        "merge": 0.1,
        "before": (0, 0),
        "after": (1, 3),
        "narration": (1, 3),
    },  # fmt: skip
    # Long paragraphs that end with the quote: ……他说："……"
    "quote_last": {
        "lone": 0.10,
        "forms": [55, 6, 5, 18, 8, 2, 6],
        "bare": 0.10,
        "merge": 0.15,
        "before": (1, 2),
        "after": (0, 0),
        "narration": (1, 3),
    },  # fmt: skip
    # Several quotes to a paragraph.
    "several": {
        "lone": 0.12,
        "forms": [30, 25, 15, 10, 8, 6, 6],
        "bare": 0.15,
        "merge": 0.75,
        "before": (0, 0),
        "after": (0, 1),
        "narration": (1, 3),
    },  # fmt: skip
}
STYLE_WEIGHTS = [25, 20, 18, 17, 20]


class Scene:
    """A short scene under construction: its paragraphs, and who says each quote in order.

    Books differ a great deal in how they lay dialogue out (see profile_layout.py): in some
    web novels four quotes in five stand alone as a paragraph, in others most sit inside a
    longer paragraph, several to a paragraph. So each scene draws its own habits.
    """

    def __init__(self, rng: random.Random):
        self.rng = rng
        marks = [("“", "”"), ('"', '"'), ("「", "」"), ("『", "』")]
        self.open_quote, self.close_quote = rng.choices(marks, weights=[55, 30, 12, 3])[0]
        self.style = STYLES[rng.choices(list(STYLES), weights=STYLE_WEIGHTS)[0]]
        # Narration paragraphs between turns, on average.
        self.narration_rate = rng.choice([0.3, 1.0, 2.0])
        self.paragraphs: list[str] = []
        self.labels: list[tuple[str, str]] = []
        self.mergeable = False  # the last paragraph is a turn and may take another
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

    def narrate(self) -> None:
        """A paragraph of narration that names nobody, so it cannot be read as naming a speaker."""
        rng = self.rng
        self.paragraphs.append("".join(rng.sample(pools.NARRATION, rng.randint(*self.style["narration"]))))
        self.mergeable = False

    def paragraph(self, text: str, mergeable: bool = False) -> None:
        self.paragraphs.append(text)
        self.mergeable = mergeable

    # ---- one turn of talk, in one of the ways novels write it ----
    def tagged_turn(self, person: dict, other: dict) -> None:
        rng = self.rng
        emotion = rng.choice(FEELINGS) if rng.random() < 0.35 else NEUTRAL
        name, who = person["name"], self.ref(person)
        address = other if rng.random() < 0.15 else None
        # Usually the words match the emotion; sometimes an ordinary sentence is shouted or
        # sobbed, and then the narration alone carries it. So the words cannot be memorised.
        text = self.line(NEUTRAL if rng.random() < 0.3 else emotion, address)
        pre = rng.choice(pools.EMOTION_PRE[emotion]) if emotion != NEUTRAL else rng.choice(pools.SAY)
        post = rng.choice(pools.EMOTION_POST[emotion]) if emotion != NEUTRAL else rng.choice(pools.SAY_POST)
        action = rng.choice(pools.ACTIONS)
        if rng.random() < self.style["lone"]:
            # The quote is a paragraph by itself; a sentence above or below says whose it is.
            form = rng.choices(["above", "below", "trap", "colon"], weights=[42, 42, 12, 4])[0]
            if form == "above":
                cue = post if emotion != NEUTRAL else action
                self.paragraph(f"{who}{cue}。")
                self.paragraph(self.say(name, emotion, text))
            elif form == "below":
                self.paragraph(self.say(name, emotion, text))
                self.paragraph(f"{who}{post}。")
            elif form == "trap":  # someone else acts first; the sentence after the quote decides
                self.paragraph(f"{self.ref(other)}{action}。")
                self.paragraph(self.say(name, emotion, text))
                self.paragraph(f"{who}{post}。")
            else:
                self.paragraph(f"{who}{pre}：")
                self.paragraph(self.say(name, emotion, text))
            return
        form = rng.choices(FORMS, weights=self.style["forms"])[0]
        if form == "pre":
            turn = f"{who}{pre}：{self.say(name, emotion, text)}"
            if rng.random() < 0.25:
                turn += rng.choice(pools.NARRATION)
        elif form == "post":
            turn = f"{self.say(name, emotion, text)}{who}{post}。"
        elif form == "mid":
            first, second = self.line(emotion, address).rstrip("。！？…") + "，", self.line(emotion)
            verb = pre.rstrip("，说问道")
            turn = f"{self.say(name, emotion, first)}{who}{verb}，{self.say(name, emotion, second)}"
        elif form == "action":  # an action sentence, then the quote, no speech verb at all
            emotion, text = NEUTRAL, self.line(NEUTRAL, address)
            turn = f"{who}{action}。{self.say(name, emotion, text)}"
        elif form == "pronoun":
            turn = f"{who}{action}，{person['pronoun']}{pre}：{self.say(name, emotion, text)}"
        elif form == "trap":  # someone else is mentioned first; the tag after the quote decides
            turn = f"{self.ref(other)}{action}。{self.say(name, emotion, text)}{who}{post}。"
        else:  # a thought counts as that character speaking, neutrally
            text = self.line(NEUTRAL)
            if rng.random() < 0.5:
                turn = f"{who}{rng.choice(pools.THOUGHT_PRE)}：{self.say(name, NEUTRAL, text)}"
            else:
                turn = f"{self.say(name, NEUTRAL, text)}{who}{rng.choice(pools.THOUGHT_POST)}。"
        turn = "".join(rng.sample(pools.NARRATION, rng.randint(*self.style["before"]))) + turn
        turn += "".join(rng.sample(pools.NARRATION, rng.randint(*self.style["after"])))
        # Two quotes may share a paragraph only with narration between them; touching, they
        # would read as one speaker carrying on.
        touching = self.paragraphs and self.paragraphs[-1].endswith(self.close_quote)
        touching = touching and turn.startswith(self.open_quote)
        if self.mergeable and not touching and rng.random() < self.style["merge"]:
            self.paragraphs[-1] += turn
        else:
            self.paragraph(turn, mergeable=True)

    def bare_turn(self, person: dict) -> None:
        """A quote alone in its paragraph: the speakers are taking turns."""
        self.paragraph(self.say(person["name"], NEUTRAL, self.line(NEUTRAL)))

    def interruption(self) -> None:
        """Something other than the main characters speaks; turn-taking starts over afterwards."""
        rng = self.rng
        kind = rng.choices(["group", "unnamed", "sound", "system"], weights=[35, 35, 20, 10])[0]
        if kind == "group":
            group = rng.choice(pools.GROUPS)
            self.paragraph(f"{group}{rng.choice(pools.GROUP_VERBS)}。")
            for _ in range(rng.randint(2, 4)):
                emotion = rng.choice([NEUTRAL, NEUTRAL, "惊讶"])
                self.paragraph(self.say(group, emotion, self.line(emotion)))
        elif kind == "unnamed":
            who = rng.choice(pools.UNNAMED)
            emotion = rng.choice(FEELINGS) if rng.random() < 0.3 else NEUTRAL
            tag = rng.choice(pools.EMOTION_PRE[emotion]) if emotion != NEUTRAL else rng.choice(pools.SAY)
            article = rng.choice(["一个", "一名", "那个", "旁边的", ""])
            self.paragraph(f"{article}{who}{tag}：{self.say(who, emotion, self.line(emotion))}")
        elif kind == "sound":
            sound = self.say(NARRATOR, NEUTRAL, rng.choice(pools.SOUNDS))
            for text in rng.sample([sound, rng.choice(pools.SOUND_NARRATION)], 2):
                self.paragraph(text)
        else:
            tag = rng.choice(["系统的提示音响起：", "系统冰冷的声音在脑海里响起：", "耳边传来系统的声音："])
            self.paragraph(f"{tag}{self.say(SYSTEM, NEUTRAL, rng.choice(pools.SYSTEM_LINES))}")

    def between_turns(self) -> None:
        rate = self.narration_rate
        for _ in range(int(rate) + (self.rng.random() < rate - int(rate))):
            self.narrate()

    def write(self) -> None:
        rng = self.rng
        if rng.random() < 0.2:  # establish a title for one character, used in place of the name later
            person = rng.choice(self.cast)
            person["alias"] = person["surname"] + rng.choice(pools.TITLES)
            self.paragraph(f"{person['alias']}{person['name']}{rng.choice(pools.ACTIONS)}。")
        self.narrate()
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
            elif tagged_since_reset >= 2 and bare_run < 3 and rng.random() < self.style["bare"]:
                self.bare_turn(a)
                a, b = b, a
                bare_run += 1
                continue  # turn-taking only reads as such when nothing comes between the quotes
            else:
                self.tagged_turn(a, b)
                a, b = b, a
                bare_run = 0
                tagged_since_reset += 1
            self.between_turns()


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
        # The list must not give the answer away: at the start of a book it is empty.
        if roll < 0.4:
            known = list(scene.names)
        elif roll < 0.7:
            known = rng.sample(scene.names, rng.randint(1, len(scene.names) - 1))
        else:
            known = []
        if any(c["alias"] for c in scene.cast):
            known = list(scene.names)  # a title can only be resolved to a name that is known
        known += [Scene(rng).names[0] for _ in range(rng.choice([0, 0, 1, 2, 3]))]  # people not in this scene
        rng.shuffle(known)
        prompt, numbers = label_request(segments, batch, known, SHORT_LABEL_PROMPT)
        answer = [{"id": n, "speaker": label_of[i][0], "emotion": label_of[i][1]} for i, n in numbers.items()]
        reply = json.dumps(answer, ensure_ascii=False)
        if len(prompt) + len(reply) > MAX_EXAMPLE_CHARS:
            continue
        out.append(
            {"messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]}
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
