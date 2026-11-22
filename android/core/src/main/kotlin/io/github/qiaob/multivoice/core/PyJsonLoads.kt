package io.github.qiaob.multivoice.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * json.loads as Python does it: strict JSON, plus NaN and Infinity; a later duplicate key wins.
 * The model's answers are read with it, so that what counts as an answer is the same on both
 * sides (kotlinx's own parser lets unquoted words through, which Python refuses).
 */
object PyJsonLoads {
    class Error(message: String) : IllegalArgumentException(message)

    fun loads(text: String): JsonElement {
        val reader = Reader(text)
        reader.space()
        val value = reader.value()
        reader.space()
        if (reader.at < text.length) throw Error("Extra data at ${reader.at}")
        return value
    }

    private class Reader(val s: String) {
        var at = 0

        fun space() {
            while (at < s.length && s[at] in " \t\n\r") at++
        }

        private fun fail(): Nothing = throw Error("Expecting value at $at")

        private fun take(word: String): Boolean {
            if (!s.startsWith(word, at)) return false
            at += word.length
            return true
        }

        fun value(): JsonElement {
            if (at >= s.length) fail()
            return when (s[at]) {
                '{' -> obj()
                '[' -> array()
                '"' -> JsonPrimitive(string())
                else -> when {
                    take("null") -> JsonNull
                    take("true") -> JsonPrimitive(true)
                    take("false") -> JsonPrimitive(false)
                    take("NaN") -> JsonPrimitive(Double.NaN)
                    take("Infinity") -> JsonPrimitive(Double.POSITIVE_INFINITY)
                    take("-Infinity") -> JsonPrimitive(Double.NEGATIVE_INFINITY)
                    else -> number()
                }
            }
        }

        private val NUMBER = Regex("-?(?:0|[1-9][0-9]*)(\\.[0-9]+)?([eE][-+]?[0-9]+)?")

        private fun number(): JsonElement {
            val match = NUMBER.matchAt(s, at) ?: fail()
            at = match.range.last + 1
            val isFloat = match.groupValues[1].isNotEmpty() || match.groupValues[2].isNotEmpty()
            if (!isFloat) match.value.toLongOrNull()?.let { return JsonPrimitive(it) }
            return JsonPrimitive(match.value.toDouble())
        }

        private fun obj(): JsonObject {
            at++
            val out = LinkedHashMap<String, JsonElement>()
            space()
            if (at < s.length && s[at] == '}') {
                at++
                return JsonObject(out)
            }
            while (true) {
                space()
                if (at >= s.length || s[at] != '"') throw Error("Expecting property name at $at")
                val key = string()
                space()
                if (at >= s.length || s[at] != ':') throw Error("Expecting ':' at $at")
                at++
                space()
                out[key] = value()
                space()
                when (s.getOrNull(at++)) {
                    ',' -> continue
                    '}' -> return JsonObject(out)
                    else -> throw Error("Expecting ',' at ${at - 1}")
                }
            }
        }

        private fun array(): JsonArray {
            at++
            val out = mutableListOf<JsonElement>()
            space()
            if (at < s.length && s[at] == ']') {
                at++
                return JsonArray(out)
            }
            while (true) {
                space()
                out.add(value())
                space()
                when (s.getOrNull(at++)) {
                    ',' -> continue
                    ']' -> return JsonArray(out)
                    else -> throw Error("Expecting ',' at ${at - 1}")
                }
            }
        }

        private fun string(): String {
            at++
            val out = StringBuilder()
            while (true) {
                if (at >= s.length) throw Error("Unterminated string")
                val c = s[at++]
                when {
                    c == '"' -> return out.toString()
                    c < ' ' -> throw Error("Invalid control character at ${at - 1}")
                    c != '\\' -> out.append(c)
                    else -> {
                        val e = s.getOrNull(at++) ?: throw Error("Unterminated string")
                        when (e) {
                            '"', '\\', '/' -> out.append(e)
                            'b' -> out.append('\b')
                            'f' -> out.append('\u000C')
                            'n' -> out.append('\n')
                            'r' -> out.append('\r')
                            't' -> out.append('\t')
                            'u' -> {
                                if (at + 4 > s.length) throw Error("Invalid \\u escape")
                                val code = s.substring(at, at + 4).toIntOrNull(16) ?: throw Error("Invalid \\u escape")
                                at += 4
                                out.append(code.toChar()) // a surrogate pair comes out whole as two of these
                            }
                            else -> throw Error("Invalid escape at ${at - 1}")
                        }
                    }
                }
            }
        }
    }
}
