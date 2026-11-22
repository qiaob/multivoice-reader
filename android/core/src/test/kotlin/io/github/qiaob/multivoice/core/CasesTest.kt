package io.github.qiaob.multivoice.core

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** The cases of tests/ on the Python side that the golden files do not cover. */
class CasesTest {
    @Test
    fun aLineNeedsOnlyItsText() {
        val script = Script.parse("""{"chapters": [{"lines": [{"text": " 夜色渐深。 "}]}]}""")
        assertEquals("未命名", script.title)
        assertEquals("第 1 段", script.chapters[0].title)
        assertEquals(listOf(Line("夜色渐深。", "旁白", "中性", 0)), script.chapters[0].lines)
        assertEquals(emptyMap(), script.characters)
    }

    @Test
    fun whatIsNotAScriptIsRefused() {
        val bad = listOf(
            "[]", "{}", """{"chapters": []}""", """{"chapters": [{"title": "一"}]}""",
            """{"chapters": [{"lines": [{"speaker": "张三"}]}]}""", """{"chapters": [{"lines": [{"text": "  "}]}]}""",
            """{"format": "something-else", "chapters": [{"lines": [{"text": "好"}]}]}""",
            """{"version": 99, "chapters": [{"lines": [{"text": "好"}]}]}""", "not json",
        )
        for (text in bad) assertFailsWith<ScriptError>(text) { Script.parse(text) }
    }

    @Test
    fun chapterRanges() {
        assertEquals(4 until 5, Script.chapterRange("5", 10))
        assertEquals(2 until 8, Script.chapterRange("3-8", 10))
        assertEquals(2 until 10, Script.chapterRange("3-", 10))
        assertEquals(0 until 8, Script.chapterRange("-8", 10))
        for (bad in listOf("", "-", "0", "9-3", "11", "a")) assertFailsWith<ScriptError>(bad) { Script.chapterRange(bad, 10) }
    }

    @Test
    fun aProfileIsFoundInOneObjectOrInOnePerLine() {
        val whole = "好的：\n{\"张三\": {\"gender\": \"男\", \"age\": \"青年\"}, \"李四\": {\"gender\": \"女\", \"age\": \"老年\"}}"
        val perLine = "{\"张三\": {\"gender\": \"男\", \"age\": \"青年\"}}\n{\"李四\": {\"gender\": \"女\", \"age\": \"老年\"}}"
        for (answer in listOf(whole, perLine)) {
            assertEquals(Json.parseToJsonElement("""{"gender": "女", "age": "老年"}"""), Analyze.profileIn(answer, "李四"))
        }
        assertEquals(emptyMap(), Analyze.profileIn(whole, "王五"))
        assertEquals(emptyMap(), Analyze.profileIn("{\"张三\": {\"gender\": 男}}", "张三"))
    }

    @Test
    fun textInTheEncodingsNovelsComeIn() {
        val text = "第一章 夜雨\n“走吧。”"
        assertEquals(text, Text.decode(("﻿" + text).toByteArray(Charsets.UTF_8)))
        assertEquals(text, Text.decode(text.toByteArray(charset("GB18030"))))
    }

    @Test
    fun rareCharactersCountAsOne() {
        // 𠮷 is outside the basic plane: two UTF-16 units, one character to Python.
        assertEquals(3, Py.len("𠮷野家"))
        assertEquals("𠮷野", Py.head("𠮷野家", 2))
    }
}
