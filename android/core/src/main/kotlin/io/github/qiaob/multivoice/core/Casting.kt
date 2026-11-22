package io.github.qiaob.multivoice.core

import io.github.qiaob.multivoice.core.ScriptFormat.SYSTEM
import io.github.qiaob.multivoice.core.ScriptFormat.UNKNOWN
import kotlin.math.abs

/**
 * A voice: a reference recording and what is said in it. [kind] is "narrator", "character" or
 * "system" for the voices that come with the reader; "clone" or "design" for the user's own,
 * which are never assigned automatically. [genre] is the kind of story it was made for, "" for any.
 */
data class Voice(
    val id: String,
    val name: String,
    val gender: String,
    val age: String,
    val kind: String,
    val genre: String = "",
    val desc: String = "",
    val refText: String = "",
    val own: Boolean = false,
)

data class Genre(val id: String, val name: String, val narrator: String)

/** Choose a voice for each character from what is known about them. A port of casting.py. */
object Casting {
    const val DEFAULT_NARRATOR = "n_m_passion"
    val AGE_ORDER = listOf("儿童", "少年", "青年", "中年", "老年")
    val GENRES = listOf(
        Genre("suspense", "悬疑灵异", "sus_n_m"),
        Genre("system", "系统爽文", "sys_n_m"),
        Genre("romance", "言情", "rom_n_f"),
    )

    fun narratorVoice(voices: Map<String, Voice>, genre: String = ""): String {
        for (id in listOf(GENRES.find { it.id == genre }?.narrator, DEFAULT_NARRATOR)) {
            if (id != null && id in voices) return id
        }
        val narrators = voices.values.filter { it.kind == "narrator" }.map { it.id }
        return narrators.ifEmpty { voices.keys.toList() }.first()
    }

    /**
     * Higher is better: right gender, then unused, then made for this kind of story (unless it
     * is the wrong generation), then a character voice, then the closest age.
     */
    private fun fit(voice: Voice, gender: String, age: String, timesUsed: Int, genre: String): List<Int> {
        val genderOk = gender == UNKNOWN || voice.gender == gender
        val ageGap = if (age in AGE_ORDER && voice.age in AGE_ORDER) {
            abs(AGE_ORDER.indexOf(age) - AGE_ORDER.indexOf(voice.age))
        } else {
            2
        }
        val ofGenre = genre.isNotEmpty() && voice.genre == genre && (age !in AGE_ORDER || ageGap <= 1)
        return listOf(genderOk.int(), -timesUsed, ofGenre.int(), (voice.kind == "character").int(), -ageGap)
    }

    private fun Boolean.int() = if (this) 1 else 0

    private val BY_FIT = Comparator<List<Int>> { a, b ->
        a.zip(b).map { (x, y) -> x.compareTo(y) }.firstOrNull { it != 0 } ?: 0
    }

    /** The best free voice for a character; the first of equals, as Python's max() picks. */
    fun pickVoice(profile: Profile, voices: Map<String, Voice>, inUse: Map<String, Int>, genre: String = ""): String {
        val pool = voices.values.filter { it.kind in listOf("narrator", "character") && it.genre in listOf("", genre) }
        var best: Voice? = null
        var bestFit: List<Int>? = null
        for (voice in pool.ifEmpty { voices.values.toList() }) {
            val fit = fit(voice, profile.gender, profile.age, inUse[voice.id] ?: 0, genre)
            if (bestFit == null || BY_FIT.compare(fit, bestFit) > 0) {
                best = voice
                bestFit = fit
            }
        }
        return best!!.id
    }

    /**
     * A voice for every character, in the order given, so the first get the pick of the voices.
     * Whoever already has a voice that still exists keeps it. A character of whom neither gender
     * nor age is known is left out: they speak with the narrator's voice until the listener says
     * otherwise. The system, if the story has one, gets the system's voice.
     */
    fun assign(
        characters: Map<String, Profile>,
        voices: Map<String, Voice>,
        before: Map<String, String>,
        narrator: String? = null,
        genre: String = "",
    ): Map<String, String> {
        val theNarrator = if (narrator != null && narrator in voices) narrator else narratorVoice(voices, genre)
        val system = voices.values.firstOrNull { it.kind == "system" }?.id
        val kept = characters.keys.filter { before[it] in voices }.associateWith { before.getValue(it) }
        val inUse = HashMap<String, Int>()
        kept.values.forEach { inUse.merge(it, 1, Int::plus) }
        inUse.merge(theNarrator, 1, Int::plus)
        val out = LinkedHashMap<String, String>()
        for ((name, about) in characters) {
            when {
                name in kept -> out[name] = kept.getValue(name)
                name == SYSTEM && system != null -> out[name] = system
                about.gender == UNKNOWN && about.age == UNKNOWN -> continue
                else -> {
                    out[name] = pickVoice(about, voices, inUse, genre)
                    inUse.merge(out.getValue(name), 1, Int::plus)
                }
            }
        }
        return out
    }
}
