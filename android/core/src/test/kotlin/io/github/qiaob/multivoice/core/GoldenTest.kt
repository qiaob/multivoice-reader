package io.github.qiaob.multivoice.core

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * The port does what the Python reader does, on the same inputs (see SelfCheck; the app runs
 * the same check on the phone). The expected results are written by android/tools/make_golden.py.
 */
class GoldenTest {
    @Test
    fun matchesThePythonReader() {
        val failures = SelfCheck.run { javaClass.getResource("/golden/$it")!!.readText() }
        assertEquals(emptyList(), failures, failures.joinToString("\n\n"))
    }

    /**
     * Some regular expressions mean one thing on the JVM, where these tests run, and another on
     * Android, or fail there: \w and \d are ASCII here and any script there, and the flag that
     * widens them here is refused there. Spell such classes out (\p{L}, \p{Nd}) instead.
     */
    @Test
    fun noRegularExpressionsThatDifferOnAndroid() {
        val sources = File("src/main/kotlin").walk().filter { it.extension == "kt" }
        for (file in sources) {
            file.readLines().forEachIndexed { i, line ->
                val code = line.substringBefore("//").takeIf { "Regex(" in it } ?: return@forEachIndexed
                for (bad in listOf("(?U)", "\\\\w", "\\\\d", "\\\\b", "\\\\W", "\\\\D", "\\\\B")) {
                    assert(bad !in code) { "${file.name}:${i + 1} 用了 $bad：$line" }
                }
            }
        }
    }
}
