package io.github.qiaob.multivoice.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * The reading script: what to say, in what order, who says it and how. It is the one thing
 * that passes from splitting a novel to reading it aloud, and it says nothing about voices.
 * A port of src/multivoice_reader/script.py; files written by either side read on the other.
 */
object ScriptFormat {
    const val FORMAT = "multivoice-reader.script"
    const val VERSION = 1
    const val NARRATOR = "旁白"
    const val SYSTEM = "系统" // the game-like "system" of a web novel: what it announces has its own voice
    const val NEUTRAL = "中性"
    const val UNKNOWN = "未知"
    val EMOTIONS = listOf(NEUTRAL, "高兴", "悲伤", "愤怒", "恐惧", "厌恶", "惊讶")
    val GENDERS = listOf("男", "女", UNKNOWN)
    val AGES = listOf("儿童", "少年", "青年", "中年", "老年", UNKNOWN)
}

class ScriptError(message: String) : IllegalArgumentException(message)

data class Line(val text: String, val speaker: String, val emotion: String, val para: Int)

data class ScriptChapter(val title: String, val lines: List<Line>)

data class Profile(val gender: String = ScriptFormat.UNKNOWN, val age: String = ScriptFormat.UNKNOWN)

data class Script(val title: String, val characters: Map<String, Profile>, val chapters: List<ScriptChapter>) {
    companion object {
        private val CHAPTER_RANGE = Regex("[${Py.SPACE}]*(\\d*)[${Py.SPACE}]*(-?)[${Py.SPACE}]*(\\d*)[${Py.SPACE}]*")

        /** Indices for "3", "3-8", "3-" or "-8" (chapters counted from 1). */
        fun chapterRange(spec: String, count: Int): IntRange {
            val match = CHAPTER_RANGE.matchEntire(spec)
            val (a, dash, b) = match?.destructured ?: throw ScriptError("看不懂章节范围「$spec」，写成 5 或 3-8 这样")
            if (a.isEmpty() && b.isEmpty()) throw ScriptError("看不懂章节范围「$spec」，写成 5 或 3-8 这样")
            val first = a.toIntOrNull() ?: 1
            val last = b.toIntOrNull() ?: if (dash.isNotEmpty()) count else first
            if (!(1 <= first && first <= last && last <= count)) throw ScriptError("章节范围「$spec」不在 1 到 $count 之间")
            return (first - 1) until last
        }

        fun parse(text: String): Script {
            val data = try {
                PyJsonLoads.loads(text.removePrefix("﻿"))
            } catch (e: Exception) {
                throw ScriptError("这个文件读不出来，它应该是一个 JSON 文件")
            }
            return normalize(data)
        }

        /** The script with every optional part filled in; ScriptError says what is wrong with it. */
        fun normalize(data: JsonElement): Script {
            val obj = data as? JsonObject
            val chaptersIn = obj?.get("chapters") as? JsonArray ?: throw ScriptError("这不是一份朗读脚本：缺少 chapters")
            val format = obj["format"]
            val version = obj["version"]?.let { pyInt(it) ?: (it as? JsonPrimitive)?.content?.toDoubleOrNull()?.toLong() }
            if ((format != null && format.str() != ScriptFormat.FORMAT) || (obj["version"] != null && (version == null || version > ScriptFormat.VERSION))) {
                throw ScriptError("这份朗读脚本的格式或版本不认识")
            }
            val chapters = mutableListOf<ScriptChapter>()
            for ((at, chapter) in chaptersIn.withIndex()) {
                val number = at + 1
                val linesIn = (chapter as? JsonObject)?.get("lines") as? JsonArray ?: throw ScriptError("第 $number 章缺少 lines")
                val lines = linesIn.mapIndexed { position, line ->
                    val text = ((line as? JsonObject)?.get("text") as? JsonPrimitive)?.takeIf { it.isString }?.content
                    if (text == null || Py.strip(text).isEmpty()) throw ScriptError("第 $number 章第 ${position + 1} 句没有 text")
                    val emotion = line.jsonObjectOrNull()?.get("emotion")?.str()
                    val para = line.jsonObjectOrNull()?.get("para")?.let(::pyInt)
                    val speaker = Py.strip(line.jsonObjectOrNull()?.get("speaker").orIfFalsy(ScriptFormat.NARRATOR))
                    Line(
                        text = Py.strip(text),
                        speaker = speaker.ifEmpty { ScriptFormat.NARRATOR },
                        emotion = if (emotion in ScriptFormat.EMOTIONS) emotion!! else ScriptFormat.NEUTRAL,
                        para = if (para != null && para >= 0) para.toInt() else position,
                    )
                }
                if (lines.isNotEmpty()) {
                    chapters.add(ScriptChapter(Py.strip((chapter as JsonObject)["title"].orIfFalsy("第 $number 段")), lines))
                }
            }
            if (chapters.isEmpty()) throw ScriptError("这份朗读脚本里没有可以读的内容")
            val given = obj["characters"] as? JsonObject ?: JsonObject(emptyMap())
            val characters = LinkedHashMap<String, Profile>()
            for (line in chapters.flatMap { it.lines }) {
                val name = line.speaker
                if (name == ScriptFormat.NARRATOR || name in characters) continue
                val about = given[name] as? JsonObject ?: JsonObject(emptyMap())
                val gender = about["gender"]?.str()
                val age = about["age"]?.str()
                characters[name] = Profile(
                    if (gender in ScriptFormat.GENDERS) gender!! else ScriptFormat.UNKNOWN,
                    if (age in ScriptFormat.AGES) age!! else ScriptFormat.UNKNOWN,
                )
            }
            val title = Py.strip(obj["title"].orIfFalsy("未命名")).ifEmpty { "未命名" }
            return Script(title, characters, chapters)
        }

        private fun JsonElement.jsonObjectOrNull() = this as? JsonObject

        /** The string, if this is one. */
        private fun JsonElement.str(): String? = (this as? JsonPrimitive)?.takeIf { it.isString }?.content

        /** Python's isinstance(x, int): an integer, or a boolean (which Python counts as one). */
        internal fun pyInt(e: JsonElement): Long? {
            val p = e as? JsonPrimitive ?: return null
            if (p is JsonNull || p.isString) return null
            return when (p.content) {
                "true" -> 1
                "false" -> 0
                else -> if (p.content.all { it.isDigit() || it == '-' }) p.content.toLongOrNull() else null
            }
        }

        /** Python's `str(x or default)`. */
        internal fun JsonElement?.orIfFalsy(default: String): String {
            if (this == null || this is JsonNull) return default
            if (this is JsonPrimitive) {
                if (isString) return content.ifEmpty { default }
                return when (content) {
                    "true" -> "True"
                    "false" -> default
                    else -> if (content.toDoubleOrNull() == 0.0) default else content
                }
            }
            if (this is JsonArray && isEmpty() || this is JsonObject && isEmpty()) return default
            return toString()
        }
    }

    /** The script as it is written to a file: what a reader would fill in anyway is left out. */
    fun compact(): Map<String, Any?> = linkedMapOf(
        "format" to ScriptFormat.FORMAT,
        "version" to ScriptFormat.VERSION,
        "title" to title,
        "characters" to characters.mapValues { (_, p) -> linkedMapOf("gender" to p.gender, "age" to p.age) },
        "chapters" to chapters.map { chapter ->
            linkedMapOf(
                "title" to chapter.title,
                "lines" to chapter.lines.mapIndexed { position, line ->
                    val out = LinkedHashMap<String, Any?>()
                    if (line.speaker != ScriptFormat.NARRATOR) out["speaker"] = line.speaker
                    if (line.emotion != ScriptFormat.NEUTRAL) out["emotion"] = line.emotion
                    if (line.para != position) out["para"] = line.para
                    out["text"] = line.text
                    out
                },
            )
        },
    )

    /** The file, byte for byte as the Python reader writes it. */
    fun dumps(): String = PyJson.dumps(compact(), indent = 1) + "\n"
}

/** json.dumps(value, ensure_ascii=False, indent=...) as Python writes it. */
object PyJson {
    fun dumps(value: Any?, indent: Int? = null): String = StringBuilder().also { write(it, value, indent, 0) }.toString()

    private fun write(out: StringBuilder, value: Any?, indent: Int?, level: Int) {
        when (value) {
            null -> out.append("null")
            is Boolean -> out.append(if (value) "true" else "false")
            is Int, is Long -> out.append(value.toString())
            is String -> string(out, value)
            is Map<*, *> -> container(out, value.entries.toList(), '{', '}', indent, level) { e ->
                string(out, e.key as String)
                out.append(": ")
                write(out, e.value, indent, level + 1)
            }
            is List<*> -> container(out, value, '[', ']', indent, level) { write(out, it, indent, level + 1) }
            else -> throw IllegalArgumentException("cannot write ${value::class}")
        }
    }

    private fun <T> container(
        out: StringBuilder, items: List<T>, open: Char, close: Char, indent: Int?, level: Int, each: (T) -> Unit,
    ) {
        out.append(open)
        if (items.isEmpty()) {
            out.append(close)
            return
        }
        val inner = if (indent == null) "" else "\n" + " ".repeat(indent * (level + 1))
        items.forEachIndexed { i, item ->
            if (i > 0) out.append(if (indent == null) ", " else ",")
            out.append(inner)
            each(item)
        }
        if (indent != null) out.append("\n").append(" ".repeat(indent * level))
        out.append(close)
    }

    private fun string(out: StringBuilder, s: String) {
        out.append('"')
        for (c in s) {
            when (c) {
                '"' -> out.append("\\\"")
                '\\' -> out.append("\\\\")
                '\n' -> out.append("\\n")
                '\r' -> out.append("\\r")
                '\t' -> out.append("\\t")
                '\b' -> out.append("\\b")
                '\u000C' -> out.append("\\f")
                else -> if (c < ' ') out.append("\\u%04x".format(c.code)) else out.append(c)
            }
        }
        out.append('"')
    }
}
