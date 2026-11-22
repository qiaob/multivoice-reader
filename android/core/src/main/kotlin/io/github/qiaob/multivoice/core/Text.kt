package io.github.qiaob.multivoice.core

/**
 * Plain text in, chapters and speakable segments out. Rules only, no models.
 * A port of src/multivoice_reader/text.py; keep the two in step.
 */
data class Chapter(val title: String, val paragraphs: List<String>)

/** [kind] is "narration", "dialogue", or "system": what a novel's "system" announces. */
data class Segment(val kind: String, val text: String, val para: Int)

object Text {
    private const val S = Py.SPACE

    // "第12章 标题", "第十二回", "第12章：标题", optionally after a short volume name: "卷名 第12章 标题".
    private val HEADING = Regex(
        "^[$S]*(?:[^$S，。！？：“”]{1,12}[$S]+)?第[$S]*[0-9０-９零〇一二三四五六七八九十百千两]+[$S]*[章回节卷]" +
            "(?:[$S：:、．.—-]+.{0,40})?[$S]*$",
    )

    // A line this long that recurs this often is not the story: it is a site's watermark.
    private const val WATERMARK_MIN_CHARS = 8
    private const val WATERMARK_MAX_CHARS = 40
    private const val WATERMARK_MIN_REPEATS = 10

    // Curly quotes, corner brackets, and straight quotes, which are paired up in order.
    private val QUOTED = Regex("“([^“”]*)”|「([^「」]*)」|『([^『』]*)』|\"([^\"]*)\"")

    private const val SENTENCE_END = "。！？…!?"

    // What a quoted span ends with when it is speech rather than a quoted term in the narration.
    private const val SPEECH_END = "$SENTENCE_END，、；—～~.,"
    private const val FALLBACK_CHAPTER_CHARS = 3000
    private const val FRONT_MATTER_MAX_CHARS = 6000 // more than this before the first heading is story
    const val NARRATION_CHARS = 70
    const val DIALOGUE_CHARS = 120

    private val SENTENCE = Regex("[^$SENTENCE_END]*[$SENTENCE_END]+[”」’』）)]*|[^$SENTENCE_END]+$")
    private val SPACES = Regex("[$S]+")
    private val WORD = Regex("(?U)\\w")

    // A paragraph that is nothing but 【…】 is the system speaking: 【叮！获得能力：仙师天眼】.
    private val SYSTEM_TEXT = Regex("(?:【[^【】]+】[$S]*)+")

    // Unless it is the author talking to the readers, which is set off the same way.
    private val AUTHOR_NOTE = Regex("求收藏|求推荐|求月票|求订阅|求打赏|新书|加更|更新|作者|[Pp][Ss][:：]")

    private fun quotedText(match: MatchResult): String = match.groups.drop(1).first { it != null }!!.value

    /** The text of a file, in whichever of the encodings Chinese novels come in. */
    fun decode(raw: ByteArray): String {
        // Python's utf-16 reads the byte order mark and, without one, takes little-endian.
        val bom = raw.size >= 2 && raw[0] == 0xFE.toByte() && raw[1] == 0xFF.toByte()
        for (charset in listOf("UTF-8", "GB18030", if (bom) "UTF-16" else "UTF-16LE")) {
            val decoder = java.nio.charset.Charset.forName(charset).newDecoder()
            try {
                val text = decoder.decode(java.nio.ByteBuffer.wrap(raw)).toString()
                return if (charset == "GB18030") text else text.removePrefix("﻿")
            } catch (_: java.nio.charset.CharacterCodingException) {
            }
        }
        throw IllegalArgumentException("认不出这个文件的文字编码")
    }

    /** Cut text that has no headings into pieces of roughly equal size at paragraph breaks. */
    private fun bySize(lines: List<String>, label: String): List<Chapter> {
        val chapters = mutableListOf<Pair<String, MutableList<String>>>()
        var size = 0
        for (line in lines) {
            if (chapters.isEmpty() || size >= FALLBACK_CHAPTER_CHARS) {
                chapters.add("${label}第 ${chapters.size + 1} 段" to mutableListOf())
                size = 0
            }
            chapters.last().second.add(line)
            size += Py.len(line)
        }
        return chapters.map { Chapter(it.first, it.second) }
    }

    /**
     * Split on chapter headings. A little text before the first heading is a blurb or credits
     * and is dropped. A lot of it is story whose headings were not recognised, and is kept, cut
     * by size. So is a text with no headings at all.
     */
    fun splitChapters(text: String): List<Chapter> {
        var lines = Py.splitLines(text).map(Py::strip).filter { it.isNotEmpty() }
        val repeats = HashMap<String, Int>()
        for (line in lines) {
            if (Py.len(line) in WATERMARK_MIN_CHARS..WATERMARK_MAX_CHARS && QUOTED.find(line) == null) {
                repeats.merge(line, 1, Int::plus)
            }
        }
        val watermarks = repeats.filterValues { it >= WATERMARK_MIN_REPEATS }.keys
        lines = lines.filter { it !in watermarks }
        val front = mutableListOf<String>()
        val chapters = mutableListOf<Pair<String, MutableList<String>>>()
        for (line in lines) {
            if (HEADING.containsMatchIn(line)) {
                chapters.add(line.replace(SPACES, " ") to mutableListOf())
            } else if (chapters.isNotEmpty()) {
                chapters.last().second.add(line)
            } else {
                front.add(line)
            }
        }
        if (chapters.isEmpty()) return bySize(front, "")
        val found = chapters.filter { it.second.isNotEmpty() }.map { Chapter(it.first, it.second) }
        if (front.sumOf { Py.len(it) } > FRONT_MATTER_MAX_CHARS) return bySize(front, "开头 ") + found
        return found
    }

    private fun sentences(text: String): List<String> =
        SENTENCE.findAll(text).map { Py.strip(it.value) }.filter { it.isNotEmpty() }.toList()

    /** Group whole sentences into pieces of at most [limit] characters where possible. */
    private fun chunks(text: String, limit: Int): List<String> {
        val out = mutableListOf<String>()
        for (sentence in sentences(text)) {
            if (out.isNotEmpty() && Py.len(out.last()) + Py.len(sentence) <= limit) {
                out[out.size - 1] = out.last() + sentence
            } else {
                out.add(sentence)
            }
        }
        return out
    }

    private fun isSpeech(quoted: String): Boolean {
        val inner = Py.strip(quoted)
        return Py.len(inner) > 12 || (inner.isNotEmpty() && SPEECH_END.codePoints().anyMatch { it == Py.last(inner) })
    }

    /** Cut paragraphs into narration, dialogue and system announcements, in reading order. */
    fun splitSegments(paragraphs: List<String>): List<Segment> {
        val segments = mutableListOf<Segment>()
        for ((index, para) in paragraphs.withIndex()) {
            if (SYSTEM_TEXT.matches(para) && !AUTHOR_NOTE.containsMatchIn(para)) {
                chunks(para, NARRATION_CHARS).forEach { segments.add(Segment("system", it, index)) }
                continue
            }
            val narration = StringBuilder()
            var cursor = 0
            fun flush() {
                if (WORD.containsMatchIn(narration)) {
                    chunks(narration.toString(), NARRATION_CHARS).forEach { segments.add(Segment("narration", it, index)) }
                }
                narration.clear()
            }
            for (match in QUOTED.findAll(para)) {
                val inner = quotedText(match)
                narration.append(para, cursor, match.range.first)
                cursor = match.range.last + 1
                if (isSpeech(inner)) {
                    flush()
                    chunks(Py.strip(inner), DIALOGUE_CHARS).forEach { segments.add(Segment("dialogue", it, index)) }
                } else {
                    narration.append(match.value) // a quoted term stays part of the narration
                }
            }
            narration.append(para, cursor, para.length)
            flush()
        }
        return segments
    }

    private const val DIGITS = "零一二三四五六七八九"

    private fun integerToChinese(value: Long): String {
        if (value < 10) return DIGITS[value.toInt()].toString()
        if (value >= 100_000_000L) {
            val head = value / 100_000_000L
            val rest = value % 100_000_000L
            val tail = if (rest != 0L) integerToChinese(rest) else ""
            return integerToChinese(head) + "亿" + (if (rest in 1 until 10_000_000L) "零" else "") + tail
        }
        if (value >= 10_000L) {
            val head = value / 10_000L
            val rest = value % 10_000L
            val tail = if (rest != 0L) integerToChinese(rest) else ""
            return integerToChinese(head) + "万" + (if (rest in 1 until 1000L) "零" else "") + tail
        }
        val out = StringBuilder()
        var number = value
        var zeroPending = false
        for ((unit, name) in listOf(1000L to "千", 100L to "百", 10L to "十", 1L to "")) {
            val digit = (number / unit).toInt()
            number %= unit
            if (digit != 0) {
                if (zeroPending && out.isNotEmpty()) out.append('零')
                out.append(DIGITS[digit]).append(name)
                zeroPending = false
            } else {
                zeroPending = true
            }
        }
        return if (out.startsWith("一十")) out.substring(1) else out.toString()
    }

    private fun digitsOf(s: String): List<Int> = s.codePoints().map { Character.digit(it, 10) }.toArray().toList()

    private fun spellDigits(s: String): String = digitsOf(s).joinToString("") { DIGITS[it].toString() }

    private val YEAR = Regex("(?U)(?<!\\d)(\\d{4})(?=年)")
    private val NUMBER = Regex("(?U)(\\d+)(?:\\.(\\d+))?(%?)")

    /** Spell numbers out the way they are read aloud; speech models stumble on digits. */
    fun speakable(text: String): String {
        val ascii = buildString(text.length) {
            for (c in text) append(if (c in '０'..'９') '0' + (c - '０') else c)
        }
        val years = YEAR.replace(ascii) { spellDigits(it.groupValues[1]) }
        return NUMBER.replace(years) { match ->
            val whole = match.groupValues[1]
            val fraction = match.groupValues[2]
            var spoken = if (Py.len(whole) > 12) {
                spellDigits(whole) // an id or a phone number: read it digit by digit
            } else {
                integerToChinese(digitsOf(whole).fold(0L) { acc, d -> acc * 10 + d })
            }
            if (fraction.isNotEmpty()) spoken += "点" + spellDigits(fraction)
            if (match.groupValues[3].isNotEmpty()) "百分之$spoken" else spoken
        }
    }
}
