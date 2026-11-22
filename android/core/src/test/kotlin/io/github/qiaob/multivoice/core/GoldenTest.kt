package io.github.qiaob.multivoice.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * The port does what the Python reader does, on the same inputs. The expected results are
 * written by android/tools/make_golden.py; run it again when the Python side changes.
 */
class GoldenTest {
    private fun golden(name: String): JsonElement =
        Json.parseToJsonElement(javaClass.getResource("/golden/$name")!!.readText())

    private val JsonElement.str get() = jsonPrimitive.content
    private fun JsonElement.strings() = jsonArray.map { it.str }

    @Test
    fun segmentsAndHowTheyAreSpoken() {
        for (case in golden("segments.json").jsonArray) {
            val got = Text.splitSegments(case.jsonObject["paragraphs"]!!.strings())
            val want = case.jsonObject["segments"]!!.jsonArray.map { it.jsonObject }
            assertEquals(want.map { Segment(it["kind"]!!.str, it["text"]!!.str, it["para"]!!.jsonPrimitive.int) }, got)
            assertEquals(want.map { it["spoken"]!!.str }, got.map { Text.speakable(it.text) })
        }
    }

    @Test
    fun chapters() {
        for (case in golden("chapters.json").jsonArray) {
            val want = case.jsonObject["chapters"]!!.jsonArray.map {
                Chapter(it.jsonObject["title"]!!.str, it.jsonObject["paragraphs"]!!.strings())
            }
            assertEquals(want, Text.splitChapters(case.jsonObject["text"]!!.str))
        }
    }

    @Test
    fun numbers() {
        for (case in golden("speakable.json").jsonArray) {
            assertEquals(case.jsonObject["spoken"]!!.str, Text.speakable(case.jsonObject["text"]!!.str))
        }
    }

    /** android/tools/make_golden.py's fake_model, line for line. */
    private fun fakeModel(prompt: String, maxTokens: Int, tuned: Boolean): String {
        val size = Py.len(prompt)
        if (tuned) {
            val names = listOf("张三", "李四（冷笑）", "\"王五\"", "", null, "某个名字特别特别长的角色啊真的很长", "系统")
            val emotions = ScriptFormat.EMOTIONS + "狂喜"
            val items = Regex("(?U)【(\\d+)】“").findAll(prompt).map { it.groupValues[1].toInt() }
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

    @Test
    fun splittingAsksTheSameAndReadsTheAnswersTheSame() {
        val want = golden("split.json").jsonObject
        val asked = mutableListOf<Triple<String, Int, Boolean>>()
        val analyzer = Analyzer { prompt, maxTokens, tuned ->
            asked.add(Triple(prompt, maxTokens, tuned))
            fakeModel(prompt, maxTokens, tuned)
        }
        val characters = LinkedHashMap<String, Role>()
        val chapters = golden("segments.json").jsonArray.mapIndexed { k, case ->
            "第 ${k + 1} 章" to Split.splitChapter(case.jsonObject["paragraphs"]!!.strings(), characters, analyzer)
        }

        val wantAsked = want["asked"]!!.jsonArray.map { it.jsonObject }
        assertEquals(wantAsked.size, asked.size)
        for ((w, got) in wantAsked.zip(asked)) {
            assertEquals(w["prompt"]!!.str, got.first)
            assertEquals(w["max_tokens"]!!.jsonPrimitive.int, got.second)
            assertEquals(w["tuned"]!!.jsonPrimitive.boolean, got.third)
            assertEquals(w["answer"]!!.str, fakeModel(got.first, got.second, got.third))
        }
        val wantLines = want["chapters"]!!.jsonArray.map { chapter ->
            chapter.jsonObject["lines"]!!.jsonArray.map { it.jsonObject }.map {
                SplitLine(it["kind"]!!.str, it["text"]!!.str, it["para"]!!.jsonPrimitive.int, it["speaker"]!!.str, it["emotion"]!!.str)
            }
        }
        assertEquals(wantLines, chapters.map { it.second })
        val wantCharacters = want["characters"]!!.jsonObject.mapValues { (_, c) ->
            Role(c.jsonObject["gender"]!!.str, c.jsonObject["age"]!!.str, c.jsonObject["lines"]!!.jsonPrimitive.int)
        }
        assertEquals(wantCharacters.toList(), characters.toList())

        // And the script made from it is written to a file exactly as Python writes it.
        val script = golden("script.json").jsonObject
        assertEquals(script["dumps"]!!.str, Split.script(script["title"]!!.str, characters, chapters).dumps())
        assertEquals(script["dumps"]!!.str, Script.parse(script["dumps"]!!.str).dumps())
    }

    @Test
    fun casting() {
        val data = golden("casting.json").jsonObject
        val voices = LinkedHashMap<String, Voice>()
        for (v in data["voices"]!!.jsonArray.map { it.jsonObject }) {
            voices[v["id"]!!.str] = Voice(v["id"]!!.str, v["name"]!!.str, v["gender"]!!.str, v["age"]!!.str, v["kind"]!!.str, v["genre"]!!.str)
        }
        val characters = LinkedHashMap<String, Profile>()
        for ((name, about) in data["characters"]!!.jsonObject) {
            characters[name] = Profile(about.jsonObject["gender"]!!.str, about.jsonObject["age"]!!.str)
        }
        for (case in data["cases"]!!.jsonArray.map { it.jsonObject }) {
            val genre = case["genre"]!!.str
            fun JsonElement.pairs() = (this as JsonObject).map { (k, v) -> k to v.str }
            assertEquals(case["narrator"]!!.str, Casting.narratorVoice(voices, genre))
            assertEquals(case["assigned"]!!.pairs(), Casting.assign(characters, voices, emptyMap(), null, genre).toList())
            assertEquals(
                case["kept"]!!.pairs(),
                Casting.assign(characters, voices, mapOf("路人3" to "mine", "路人4" to "gone"), "m_cold", genre).toList(),
            )
        }
    }
}
