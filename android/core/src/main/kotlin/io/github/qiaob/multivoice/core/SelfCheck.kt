package io.github.qiaob.multivoice.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Does this port do what the Python reader does, on this machine? The expected results are
 * written by android/tools/make_golden.py. The JVM tests run it, and so does the app on the
 * phone: Android's regular expressions are not the JVM's, so passing on one says little about
 * the other.
 */
object SelfCheck {
    /** What differs, in a few words each; empty if nothing does. [read] gives a golden file's text. */
    fun run(read: (String) -> String): List<String> {
        val failures = mutableListOf<String>()
        fun check(what: String, block: () -> Unit) {
            try {
                block()
            } catch (e: Throwable) {
                failures.add("$what：${e.message ?: e}")
            }
        }
        fun golden(name: String): JsonElement = Json.parseToJsonElement(read(name))
        check("切句") { segments(golden("segments.json")) }
        check("切章") { chapters(golden("chapters.json")) }
        check("数字读法") { numbers(golden("speakable.json")) }
        check("拆分") { split(golden("split.json"), golden("segments.json"), golden("script.json")) }
        check("配声音") { casting(golden("casting.json")) }
        return failures
    }

    private fun <T> same(what: String, want: T, got: T) {
        if (want != got) throw AssertionError("$what 不一样\n  应为：${clip(want)}\n  实为：${clip(got)}")
    }

    private fun clip(x: Any?) = x.toString().let { if (it.length > 300) it.take(300) + "…" else it }

    private val JsonElement.str get() = jsonPrimitive.content
    private fun JsonElement.strings() = jsonArray.map { it.str }

    private fun segments(data: JsonElement) {
        for ((n, case) in data.jsonArray.withIndex()) {
            val got = Text.splitSegments(case.jsonObject["paragraphs"]!!.strings())
            val want = case.jsonObject["segments"]!!.jsonArray.map { it.jsonObject }
            same("第 ${n + 1} 段的切句", want.map { Segment(it["kind"]!!.str, it["text"]!!.str, it["para"]!!.jsonPrimitive.int) }, got)
            same("第 ${n + 1} 段的读法", want.map { it["spoken"]!!.str }, got.map { Text.speakable(it.text) })
        }
    }

    private fun chapters(data: JsonElement) {
        for ((n, case) in data.jsonArray.withIndex()) {
            val want = case.jsonObject["chapters"]!!.jsonArray.map {
                Chapter(it.jsonObject["title"]!!.str, it.jsonObject["paragraphs"]!!.strings())
            }
            same("第 ${n + 1} 份文字的切章", want, Text.splitChapters(case.jsonObject["text"]!!.str))
        }
    }

    private fun numbers(data: JsonElement) {
        for (case in data.jsonArray) {
            same(case.jsonObject["text"]!!.str, case.jsonObject["spoken"]!!.str, Text.speakable(case.jsonObject["text"]!!.str))
        }
    }

    /** android/tools/make_golden.py's fake_model, line for line. */
    fun fakeModel(prompt: String, maxTokens: Int, tuned: Boolean): String {
        val size = Py.len(prompt)
        if (tuned) {
            val names = listOf("张三", "李四（冷笑）", "\"王五\"", "", null, "某个名字特别特别长的角色啊真的很长", "系统")
            val emotions = ScriptFormat.EMOTIONS + "狂喜"
            val items = Regex("【(\\p{Nd}+)】“").findAll(prompt).map { it.groupValues[1].toInt() }
                .filter { it % 9 != 8 }
                .map { n ->
                    linkedMapOf("id" to n, "speaker" to names[(n + size) % names.size], "emotion" to emotions[(n * 3 + size) % 8])
                }.toList()
            return listOf("", "好的：\n", "```json\n")[size % 3] + PyJson.dumps(items) + listOf("", "\n```", "\n以上。")[size % 3]
        }
        val names = Regex("判断这些角色的性别和年龄段：(.*)\n").find(prompt)!!.groupValues[1].split("、")
        val about = LinkedHashMap<String, Any?>()
        names.forEachIndexed { i, name ->
            about[name] = linkedMapOf(
                "gender" to (ScriptFormat.GENDERS + "x")[(i + size) % 4],
                "age" to ScriptFormat.AGES[(i * 2 + size) % 6],
            )
        }
        if (size % 2 == 0) return PyJson.dumps(about)
        return about.entries.joinToString("\n") { PyJson.dumps(mapOf(it.key to it.value)) }
    }

    private fun split(data: JsonElement, segments: JsonElement, script: JsonElement) {
        val want = data.jsonObject
        val asked = mutableListOf<Triple<String, Int, Boolean>>()
        val analyzer = Analyzer { prompt, maxTokens, tuned ->
            asked.add(Triple(prompt, maxTokens, tuned))
            fakeModel(prompt, maxTokens, tuned)
        }
        val characters = LinkedHashMap<String, Role>()
        val chapters = segments.jsonArray.mapIndexed { k, case ->
            "第 ${k + 1} 章" to Split.splitChapter(case.jsonObject["paragraphs"]!!.strings(), characters, analyzer)
        }
        val wantAsked = want["asked"]!!.jsonArray.map { it.jsonObject }
        same("问模型的次数", wantAsked.size, asked.size)
        for ((n, pair) in wantAsked.zip(asked).withIndex()) {
            val (w, got) = pair
            same("第 ${n + 1} 次的提示", w["prompt"]!!.str, got.first)
            same("第 ${n + 1} 次的 max_tokens", w["max_tokens"]!!.jsonPrimitive.int, got.second)
            same("第 ${n + 1} 次是否用微调权重", w["tuned"]!!.jsonPrimitive.boolean, got.third)
            same("第 ${n + 1} 次的回答", w["answer"]!!.str, fakeModel(got.first, got.second, got.third))
        }
        val wantLines = want["chapters"]!!.jsonArray.map { chapter ->
            chapter.jsonObject["lines"]!!.jsonArray.map { it.jsonObject }.map {
                SplitLine(it["kind"]!!.str, it["text"]!!.str, it["para"]!!.jsonPrimitive.int, it["speaker"]!!.str, it["emotion"]!!.str)
            }
        }
        same("拆分结果", wantLines, chapters.map { it.second })
        val wantCharacters = want["characters"]!!.jsonObject.map { (name, c) ->
            name to Role(c.jsonObject["gender"]!!.str, c.jsonObject["age"]!!.str, c.jsonObject["lines"]!!.jsonPrimitive.int)
        }
        same("角色", wantCharacters, characters.toList())
        val dumps = script.jsonObject["dumps"]!!.str
        same("朗读脚本文件", dumps, Split.script(script.jsonObject["title"]!!.str, characters, chapters).dumps())
        same("读回来再写出的朗读脚本", dumps, Script.parse(dumps).dumps())
    }

    private fun casting(data: JsonElement) {
        val obj = data.jsonObject
        val voices = LinkedHashMap<String, Voice>()
        for (v in obj["voices"]!!.jsonArray.map { it.jsonObject }) {
            voices[v["id"]!!.str] = Voice(v["id"]!!.str, v["name"]!!.str, v["gender"]!!.str, v["age"]!!.str, v["kind"]!!.str, v["genre"]!!.str)
        }
        val characters = LinkedHashMap<String, Profile>()
        for ((name, about) in obj["characters"]!!.jsonObject) {
            characters[name] = Profile(about.jsonObject["gender"]!!.str, about.jsonObject["age"]!!.str)
        }
        for (case in obj["cases"]!!.jsonArray.map { it.jsonObject }) {
            val genre = case["genre"]!!.str
            fun JsonElement.pairs() = (this as JsonObject).map { (k, v) -> k to v.str }
            same("$genre 的旁白", case["narrator"]!!.str, Casting.narratorVoice(voices, genre))
            same("$genre 的配声音", case["assigned"]!!.pairs(), Casting.assign(characters, voices, emptyMap(), null, genre).toList())
            same(
                "$genre 保留已选的声音",
                case["kept"]!!.pairs(),
                Casting.assign(characters, voices, mapOf("路人3" to "mine", "路人4" to "gone"), "m_cold", genre).toList(),
            )
        }
    }
}
