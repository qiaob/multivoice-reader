# Labelling dialogue in Chinese novel passages (answer key for an evaluation set)

For every numbered line of dialogue in each passage file you are given, decide who says it and
with what emotion. These labels are the answer key that models are scored against, so they
must be right, and they must also list every other answer that would be equally correct.
Do the labelling yourself by reading. Do not write a program or call any model to do it, do
not delegate, and read only the files you were assigned.

## The input files

Each JSON file has:

- `id`: the passage id, e.g. "e03-007"
- `prompt`: starts with `已知角色：暂无`, then the passage. Each line of dialogue to label is
  prefixed with a number like 【3】. This is everything the model being scored will see.
- `lines`: the numbered dialogue lines (`id`, `text`). Label exactly these ids.
- `wider_text`: more of the chapter around the passage. Use it to work out who is speaking;
  the model being scored will not see it.

## Speaker

- The narration around a line usually says who speaks: “张三说：” before it, or “李四冷笑一声”
  right after it. When two people talk they usually alternate line by line.
- `speaker`: the speaker's name the way the passage in `prompt` writes it, preferring the full
  name used there over a nickname or title.
- If the passage never names the person but `wider_text` does, use the name from `wider_text`.
- In a novel told in the first person, the narrator's own lines are “我”, even if you know the
  narrator's name from elsewhere.
- Never use a name that appears neither in `prompt` nor in `wider_text` of the same file.
- For someone with no name anywhere, use the short description the narration itself uses
  (老者, 店小二, 众人). Do not invent labels such as 弟子甲 or 路人A.
- A thought counts as spoken by the character who thinks it.
- A sound not made by a person (onomatopoeia, animal roar, bell), or quoted text that nobody
  speaks (a sign, a book title, a quoted term inside narration), is “旁白”.
- A system or interface announcement in game-like novels is “系统”.

## Other answers that count as right: `accept`

A list of every other answer a careful reader of the passage alone could give for this line
and still be right:

- other ways the passage or the wider text refers to the same person: short name, surname
  with title, nickname, role, description (for 张三丰: 张真人, 老道, 师父 …);
- for a speaker with no name (a bystander, a crowd, a guard), the other generic words that fit
  (有人, 路人, 众人, 弟子 …) and “未知”;
- “未知” whenever the passage in `prompt` alone, without `wider_text`, does not let a reader
  tell who is speaking;
- “旁白” or “系统” when that reading is also defensible.

Do not put a different character in `accept`. Use [] when there is nothing to add.

## Emotion

- `emotion`: exactly one of 中性、高兴、悲伤、愤怒、恐惧、厌恶、惊讶.
- Be conservative. Ordinary talk, questions, greetings and mild exclamations are “中性”.
- Pick something else only when the narration states the emotion (怒喝、冷笑、哭着说、大笑、
  吓得发抖) or the line itself is very strong in tone.
- `emotion_accept`: any other emotion from the list that is equally defensible for this line,
  else []. When you chose a non-neutral emotion on tone alone, put “中性” here.

## Lines that cannot be decided: `unsure`

`unsure`: true when even with the wider text you cannot decide between two or more different
characters. Such lines are left out of scoring. Otherwise false.

## Output

Write one file at the path you were given, one JSON object per line, one per passage, UTF-8
with Chinese not escaped:

    {"id": "e03-007", "labels": [{"id": 1, "speaker": "张三", "accept": ["张师兄", "师兄"], "emotion": "中性", "emotion_accept": [], "unsure": false}]}

Every id in a file's `lines` must appear exactly once in that passage's labels, and every
passage you were assigned must be present.

## Your reply

Reply with only: how many passages and lines you labelled, how many lines have unsure=true,
and how many have “未知” in `accept`. Do not quote any text from the passages.
