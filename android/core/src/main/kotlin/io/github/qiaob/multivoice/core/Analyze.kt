package io.github.qiaob.multivoice.core

import io.github.qiaob.multivoice.core.ScriptFormat.AGES
import io.github.qiaob.multivoice.core.ScriptFormat.EMOTIONS
import io.github.qiaob.multivoice.core.ScriptFormat.GENDERS
import io.github.qiaob.multivoice.core.ScriptFormat.NARRATOR
import io.github.qiaob.multivoice.core.ScriptFormat.NEUTRAL
import io.github.qiaob.multivoice.core.ScriptFormat.SYSTEM
import io.github.qiaob.multivoice.core.ScriptFormat.UNKNOWN
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * The language model that labels the dialogue, however it is run on the phone.
 * [tuned] false asks the model as it was before fine-tuning (the LoRA weights switched off):
 * the fine-tuned one has learnt to answer everything as if it were asked to label lines.
 */
fun interface LanguageModel {
    fun ask(prompt: String, maxTokens: Int, tuned: Boolean): String
}

data class Label(val speaker: String, val emotion: String)

/**
 * Who says each line, and how. The model never rewrites the text: it only answers, per
 * numbered line of dialogue, with a speaker name and one emotion.
 * A port of src/multivoice_reader/analyze.py; the prompts must stay exactly as the models
 * were fine-tuned on (finetune/), down to the last character.
 */
object Analyze {
    const val LINES_PER_ASK = 8 // dialogue lines labelled in one request
    const val CONTEXT_PARAGRAPHS = 3 // narration shown before the first line of a request
    const val PROFILE_EXCERPT_CHARS = 3500

    /** What a model fine-tuned on this task is told: it has learnt the rules, so only the facts. */
    fun shortLabelPrompt(known: String, excerpt: String, emotions: String) =
        "已知角色：$known\n\n$excerpt\n\n标出每句带编号的对白是谁说的、带着什么情绪。可选的情绪：$emotions。"

    fun profilePrompt(excerpt: String, names: String, genders: String, ages: String) =
        "下面是一段小说。\n\n$excerpt\n\n请根据这段内容，判断这些角色的性别和年龄段：$names\n" +
            "- gender 只能是：$genders\n" +
            "- age 只能是：$ages（儿童 12 岁以下，少年 13 到 19 岁，青年 20 到 35 岁，中年 36 到 59 岁，老年 60 岁以上）\n" +
            "只输出 JSON 对象，不要解释。例如：\n" +
            "{\"张三\": {\"gender\": \"男\", \"age\": \"青年\"}}"

    /**
     * The prompt as Qwen3's chat template lays it out, with thinking switched off (as
     * analyze.chat_prompt asks for). Check it against the tokenizer of every model the app runs.
     */
    fun qwen3Chat(prompt: String) =
        "<|im_start|>user\n$prompt<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

    /** Indices of the dialogue segments, in the groups they are asked about. */
    fun labelBatches(segments: List<Segment>): List<List<Int>> =
        segments.indices.filter { segments[it].kind == "dialogue" }.chunked(LINES_PER_ASK)

    /** The prompt for one group of lines, and which number each segment index was given. */
    fun labelRequest(segments: List<Segment>, batch: List<Int>, known: List<String>): Pair<String, Map<Int, Int>> {
        val firstPara = segments[batch.first()].para - CONTEXT_PARAGRAPHS
        val lastPara = segments[batch.last()].para + 1
        val numbers = LinkedHashMap<Int, Int>()
        batch.forEachIndexed { n, index -> numbers[index] = n + 1 }
        val excerpt = StringBuilder()
        var para: Int? = null
        for ((i, seg) in segments.withIndex()) {
            if (seg.para < firstPara || seg.para > lastPara) continue
            if (seg.para != para) {
                excerpt.append("\n")
                para = seg.para
            }
            when {
                seg.kind != "dialogue" -> excerpt.append(seg.text) // narration, or the system: as written
                i in numbers -> excerpt.append("【${numbers[i]}】“${seg.text}”")
                else -> excerpt.append("“${seg.text}”")
            }
        }
        val prompt = shortLabelPrompt(
            known.joinToString("、").ifEmpty { "暂无" },
            Py.strip(excerpt.toString()),
            EMOTIONS.joinToString("、"),
        )
        return prompt to numbers
    }

    /** The model sometimes wraps its answer in prose or a code fence; take the JSON inside. */
    internal fun firstJson(text: String, opener: Char, closer: Char): JsonElement? {
        val start = text.indexOf(opener)
        val end = text.lastIndexOf(closer)
        if (start < 0 || end <= start) return null
        return try {
            PyJsonLoads.loads(text.substring(start, end + 1))
        } catch (_: Exception) {
            null
        }
    }

    /**
     * What the answer says about one character. Looked up by name, not parsed whole, because a
     * small model may write one object per line instead of a single one.
     */
    internal fun profileIn(answer: String, name: String): JsonObject {
        val found = Regex("\"" + Regex.escape(name) + "\"[${Py.SPACE}]*:[${Py.SPACE}]*(\\{[^{}]*\\})").find(answer)
            ?: return JsonObject(emptyMap())
        return try {
            PyJsonLoads.loads(found.groupValues[1]) as? JsonObject ?: JsonObject(emptyMap())
        } catch (_: Exception) {
            JsonObject(emptyMap())
        }
    }

    private val AFTER_NAME = Regex("[（(【\\[].*$")

    internal fun cleanName(name: JsonElement?): String {
        val raw = with(Script.Companion) { name.orIfFalsy("") }
        val cleaned = Py.strip(raw.replace(AFTER_NAME, ""), " 　\"“”'：:")
        return Py.head(cleaned, 12).ifEmpty { UNKNOWN }
    }

    private fun JsonElement?.string(): String? = (this as? JsonPrimitive)?.takeIf { it.isString }?.content
}

class Analyzer(private val model: LanguageModel) {
    /**
     * One label per segment. Only dialogue is asked about: narration is the narrator's and what
     * the system announces is the system's, both neutral.
     */
    fun label(segments: List<Segment>, knownBefore: List<String>): List<Label> {
        val labels = segments.map { Label(if (it.kind == "system") SYSTEM else NARRATOR, NEUTRAL) }.toMutableList()
        val known = knownBefore.toMutableList()
        for (batch in Analyze.labelBatches(segments)) {
            val (prompt, numbers) = Analyze.labelRequest(segments, batch, known)
            val answer = model.ask(prompt, maxTokens = 40 * batch.size + 40, tuned = true)
            val byNumber = HashMap<Long, JsonObject>()
            for (item in Analyze.firstJson(answer, '[', ']') as? JsonArray ?: JsonArray(emptyList())) {
                val id = (item as? JsonObject)?.get("id")?.let(Script::pyInt) ?: continue
                byNumber[id] = item
            }
            for ((index, number) in numbers) {
                val item = byNumber[number.toLong()]
                val speaker = Analyze.cleanName(item?.get("speaker"))
                val emotion = (item?.get("emotion") as? JsonPrimitive)?.takeIf { it.isString }?.content
                labels[index] = Label(speaker, if (emotion in EMOTIONS) emotion!! else NEUTRAL)
                if (speaker != UNKNOWN && speaker !in known) known.add(speaker)
            }
        }
        return labels
    }

    /** Gender and age band for characters met for the first time. */
    fun profiles(segments: List<Segment>, names: List<String>): Map<String, Profile> {
        if (names.isEmpty()) return emptyMap()
        val excerpt = segments.joinToString("\n") { if (it.kind == "narration") it.text else "“${it.text}”" }
        val answer = model.ask(
            Analyze.profilePrompt(
                Py.head(excerpt, Analyze.PROFILE_EXCERPT_CHARS),
                names.joinToString("、"),
                GENDERS.joinToString("、"),
                AGES.joinToString("、"),
            ),
            maxTokens = 30 * names.size + 40,
            tuned = false,
        )
        val out = LinkedHashMap<String, Profile>()
        for (name in names) {
            val item = Analyze.profileIn(answer, name)
            val gender = (item["gender"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val age = (item["age"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            out[name] = Profile(
                if (gender in GENDERS) gender!! else UNKNOWN,
                if (age in AGES) age!! else UNKNOWN,
            )
        }
        return out
    }
}

/** What is known of a character while a book is split: who they are and how often they speak. */
data class Role(val gender: String, val age: String, val lines: Int)

/** One labelled line of a chapter, as the split keeps it. */
data class SplitLine(val kind: String, val text: String, val para: Int, val speaker: String, val emotion: String)

object Split {
    /**
     * One chapter's lines, labelled. Characters met for the first time are added to
     * [characters], and everyone's count of lines goes up. A port of split.split_chapter.
     */
    fun splitChapter(
        paragraphs: List<String>, characters: LinkedHashMap<String, Role>, analyzer: Analyzer,
    ): List<SplitLine> {
        val segments = Text.splitSegments(paragraphs)
        val labels = analyzer.label(segments, characters.keys.toList())
        val spoken = LinkedHashMap<String, Int>()
        for (label in labels) if (label.speaker != NARRATOR) spoken.merge(label.speaker, 1, Int::plus)
        val new = spoken.keys.filter { it !in characters }
        val profiles = analyzer.profiles(segments, new.filter { it != SYSTEM })
        for (name in new) {
            val profile = profiles[name] ?: Profile() // the system is not a person
            characters[name] = Role(profile.gender, profile.age, 0)
        }
        for ((name, count) in spoken) characters[name] = characters.getValue(name).let { it.copy(lines = it.lines + count) }
        return segments.zip(labels) { s, l -> SplitLine(s.kind, s.text, s.para, l.speaker, l.emotion) }
    }

    /** The reading script made from what has been split so far. */
    fun script(title: String, characters: Map<String, Role>, chapters: List<Pair<String, List<SplitLine>>>): Script {
        val data = linkedMapOf(
            "title" to title,
            "characters" to characters.mapValues { (_, c) -> linkedMapOf("gender" to c.gender, "age" to c.age) },
            "chapters" to chapters.map { (chapterTitle, lines) ->
                linkedMapOf(
                    "title" to chapterTitle,
                    "lines" to lines.map {
                        linkedMapOf("text" to it.text, "speaker" to it.speaker, "emotion" to it.emotion, "para" to it.para)
                    },
                )
            },
        )
        return Script.normalize(PyJsonLoads.loads(PyJson.dumps(data)))
    }
}
