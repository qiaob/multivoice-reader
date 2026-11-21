# Labelling dialogue in Chinese novel passages (training data)

For every numbered line of dialogue in each passage file you are given, decide who says it and
with what emotion. The labels train a small model, so accuracy matters; work carefully but
don't over-deliberate. Do the labelling yourself by reading. Do not write a program or call
any model to do it, do not delegate, and read only the files you were assigned.

## The input files

Each JSON file has:

- `id`: the passage id, e.g. "t03-007"
- `prompt`: starts with `已知角色：暂无`, then the passage. Each line of dialogue to label is
  prefixed with a number like 【3】. This is everything the small model will see.
- `lines`: the numbered dialogue lines (`id`, `text`). Label exactly these ids.
- `wider_text`: more of the chapter around the passage. Use it to work out who is speaking;
  the small model will not see it.

## Speaker

- The narration around a line usually says who speaks: “张三说：” before it, or “李四冷笑一声”
  right after it. When two people talk they usually alternate line by line.
- Write the speaker's name the way the passage in `prompt` writes it, preferring the full name
  used there over a nickname or title. Use the same spelling for the same person throughout
  one passage.
- If the passage never names the person but `wider_text` does, use the name from `wider_text`.
- In a novel told in the first person, the narrator's own lines are “我”, even if you know the
  narrator's name from elsewhere. Use the narrator's name only when the narration of this very
  passage attributes the line to that name.
- Never use a name that appears neither in `prompt` nor in `wider_text` of the same file, even
  if another file of the same book told you who the person is.
- For someone with no name anywhere, use the short description the narration itself uses
  (老者, 店小二, 众人). Do not invent labels such as 弟子甲 or 路人A.
- A thought counts as spoken by the character who thinks it.
- A sound not made by a person (onomatopoeia, animal roar, bell), or quoted text that nobody
  speaks (a sign, a book title, a quoted term inside narration), is “旁白”.
- A system or interface announcement in game-like novels is “系统”.
- “未知” only when it really cannot be decided even with the wider text.

## Emotion

- Exactly one of: 中性、高兴、悲伤、愤怒、恐惧、厌恶、惊讶.
- Be conservative. Ordinary talk, questions, greetings and mild exclamations are “中性”.
- Pick something else only when the narration states the emotion (怒喝、冷笑、哭着说、大笑、
  吓得发抖) or the line itself is very strong in tone.

## Sure or not

For each line give `sure`: true if you are confident of the speaker, false if it was a
judgement call between two or more candidates.

## Output

Write one file at the path you were given, one JSON object per line, one per passage, UTF-8
with Chinese not escaped:

    {"id": "t03-007", "labels": [{"id": 1, "speaker": "张三", "emotion": "中性", "sure": true}, {"id": 2, "speaker": "李四", "emotion": "愤怒", "sure": false}]}

Every id in a file's `lines` must appear exactly once in that passage's labels, and every
passage you were assigned must be present.

## Your reply

Reply with only: how many passages and lines you labelled, how many lines are “未知”, and how
many have sure=false. Do not quote any text from the passages.
