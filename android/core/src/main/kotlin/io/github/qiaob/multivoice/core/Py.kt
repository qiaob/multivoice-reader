package io.github.qiaob.multivoice.core

/**
 * The few places where Python and Kotlin disagree about text, done the Python way, so that the
 * port cuts and counts exactly as the Python reader does (and as the models were trained on).
 *
 * - Python counts characters as code points; a Kotlin String counts UTF-16 units, and a rare
 *   character outside the basic plane is two of them.
 * - Python's whitespace (str.isspace, and \s in a regex) is its own set.
 * - str.splitlines() breaks on more than \n and \r.
 */
internal object Py {
    /** Python's whitespace, as the inside of a regex character class. */
    const val SPACE = "\\t\\n\\x0B\\f\\r\\x1C-\\x1F \\x85\\xA0\\u1680\\u2000-\\u200A\\u2028\\u2029\\u202F\\u205F\\u3000"

    fun isSpace(c: Int): Boolean =
        c in 0x09..0x0D || c in 0x1C..0x20 || c == 0x85 || c == 0xA0 || c == 0x1680 ||
            c in 0x2000..0x200A || c == 0x2028 || c == 0x2029 || c == 0x202F || c == 0x205F || c == 0x3000

    /** len(s) */
    fun len(s: String): Int = s.codePointCount(0, s.length)

    /** s.strip() */
    fun strip(s: String): String = strip(s) { isSpace(it) }

    /** s.strip(chars) */
    fun strip(s: String, chars: String): String = strip(s) { chars.codePoints().anyMatch { c -> c == it } }

    private inline fun strip(s: String, drop: (Int) -> Boolean): String {
        var start = 0
        var end = s.length
        while (start < end && drop(s.codePointAt(start))) start += Character.charCount(s.codePointAt(start))
        while (end > start && drop(s.codePointBefore(end))) end -= Character.charCount(s.codePointBefore(end))
        return s.substring(start, end)
    }

    /** s[:n] */
    fun head(s: String, n: Int): String =
        if (len(s) <= n) s else s.substring(0, s.offsetByCodePoints(0, n))

    /** s.splitlines() */
    fun splitLines(s: String): List<String> {
        val out = mutableListOf<String>()
        var start = 0
        var i = 0
        while (i < s.length) {
            val c = s[i]
            val breaks = c == '\n' || c == '\r' || c == '\u000B' || c == '\u000C' || c in '\u001C'..'\u001E' ||
                c == '\u0085' || c == ' ' || c == ' '
            if (breaks) {
                out.add(s.substring(start, i))
                i += if (c == '\r' && i + 1 < s.length && s[i + 1] == '\n') 2 else 1
                start = i
            } else {
                i++
            }
        }
        if (start < s.length) out.add(s.substring(start))
        return out
    }

    /** The last character, as a code point; -1 if there is none. */
    fun last(s: String): Int = if (s.isEmpty()) -1 else s.codePointBefore(s.length)
}
