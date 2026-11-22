package io.github.qiaob.multivoice.core

import java.io.File
import kotlin.test.Test

/**
 * Writes every regular expression the port uses to build/regex-patterns.txt, one per line, so
 * that tools/check_icu_regex.c can compile them with ICU, the engine Android's regexes run on.
 */
class RegexDump {
    @Test
    fun dump() {
        val found = mutableListOf<String>()
        fun from(owner: Any) {
            var type: Class<*>? = owner.javaClass
            while (type != null && type != Any::class.java) {
                for (field in type.declaredFields) {
                    if (field.type == Regex::class.java) {
                        field.isAccessible = true
                        found.add((field.get(owner) as Regex).pattern)
                    }
                }
                type = type.superclass
            }
        }
        listOf(Text, Analyze, Script.Companion).forEach(::from)
        // Made on the spot rather than kept in a field.
        found.add("\"" + Regex.escape("张三") + "\"[${Py.SPACE}]*:[${Py.SPACE}]*(\\{[^{}]*\\})")
        found.add("-?(?:0|[1-9][0-9]*)(\\.[0-9]+)?([eE][-+]?[0-9]+)?")
        found.add("【(\\p{Nd}+)】“")
        found.add("判断这些角色的性别和年龄段：(.*)\n")
        File("build/regex-patterns.txt").writeText(found.joinToString("\n") { it.replace("\n", "\\n") } + "\n")
    }
}
