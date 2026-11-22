package io.github.qiaob.multivoice.data

import io.github.qiaob.multivoice.core.Role
import io.github.qiaob.multivoice.core.Script
import io.github.qiaob.multivoice.core.Split
import io.github.qiaob.multivoice.core.SplitLine
import io.github.qiaob.multivoice.core.Text
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.security.MessageDigest

@Serializable
data class BookMeta(val title: String, val chapters: List<String>)

@Serializable
data class LineDto(val kind: String, val text: String, val para: Int, val speaker: String, val emotion: String)

@Serializable
data class RoleDto(val gender: String, val age: String, val lines: Int)

/** One chapter as it was split, and how long it took. */
@Serializable
data class ChapterResult(
    val model: String,
    val lines: List<LineDto>,
    val chars: Int,
    val seconds: Double,
    val promptTokens: Long,
    val answerTokens: Long,
)

private val json = Json { ignoreUnknownKeys = true; prettyPrint = false }

private fun File.writeAtomically(text: String) {
    val tmp = File(path + ".tmp")
    tmp.writeText(text)
    tmp.renameTo(this)
}

/** A novel on the phone: its chapters as text, and what splitting found in them. */
class Book(val dir: File) {
    val id: String = dir.name
    val meta: BookMeta = json.decodeFromString(File(dir, "book.json").readText())
    val title get() = meta.title
    val chapters get() = meta.chapters

    fun paragraphs(chapter: Int): List<String> =
        File(dir, "text/%05d.txt".format(chapter)).readText().split("\n")

    private fun resultFile(chapter: Int) = File(dir, "lines/%05d.json".format(chapter))

    fun result(chapter: Int): ChapterResult? =
        resultFile(chapter).takeIf { it.isFile }?.let { json.decodeFromString<ChapterResult>(it.readText()) }

    fun done(): List<Boolean> = chapters.indices.map { resultFile(it).isFile }

    fun saveResult(chapter: Int, result: ChapterResult) {
        resultFile(chapter).parentFile!!.mkdirs()
        resultFile(chapter).writeAtomically(json.encodeToString(result))
    }

    fun characters(): LinkedHashMap<String, Role> {
        val file = File(dir, "characters.json")
        val out = LinkedHashMap<String, Role>()
        if (file.isFile) {
            json.decodeFromString<Map<String, RoleDto>>(file.readText()).forEach { (name, r) ->
                out[name] = Role(r.gender, r.age, r.lines)
            }
        }
        return out
    }

    fun saveCharacters(characters: Map<String, Role>) {
        val dto = LinkedHashMap<String, RoleDto>()
        characters.forEach { (name, r) -> dto[name] = RoleDto(r.gender, r.age, r.lines) }
        File(dir, "characters.json").writeAtomically(json.encodeToString(dto))
    }

    /**
     * The reading script of the chapters split so far, from the first up to the first one not
     * split yet: the same format the computer version reads (and writes).
     */
    fun script(): Script {
        val done = mutableListOf<Pair<String, List<SplitLine>>>()
        for (k in chapters.indices) {
            val result = result(k) ?: break
            done.add(chapters[k] to result.lines.map { SplitLine(it.kind, it.text, it.para, it.speaker, it.emotion) })
        }
        if (done.isEmpty()) throw IllegalStateException("第一章还没有拆分")
        return Split.script(title, characters(), done)
    }

    fun remove() {
        dir.deleteRecursively()
    }
}

object Library {
    private lateinit var root: File

    fun init(filesDir: File) {
        root = File(filesDir, "books").apply { mkdirs() }
    }

    fun all(): List<Book> =
        root.listFiles().orEmpty().filter { File(it, "book.json").isFile }.sortedBy { it.lastModified() }.map(::Book)

    fun open(id: String): Book? = File(root, id).takeIf { File(it, "book.json").isFile }?.let(::Book)

    /** Cut a novel into chapters and keep it. IllegalArgumentException says what is wrong with it. */
    fun add(name: String, raw: ByteArray): Book {
        val title = name.removeSuffix(".txt").replace(Regex("\\s*作者[:：].*$"), "").trim().ifEmpty { name }
        val chapters = Text.splitChapters(Text.decode(raw))
        if (chapters.isEmpty()) throw IllegalArgumentException("$name 里没有可以朗读的正文")
        val digest = MessageDigest.getInstance("SHA-1").digest(raw).joinToString("") { "%02x".format(it) }.take(8)
        val dir = File(root, "${title.replace(Regex("[^\\w-]+"), "_").take(40)}-$digest")
        File(dir, "text").mkdirs()
        chapters.forEachIndexed { k, chapter ->
            File(dir, "text/%05d.txt".format(k)).writeText(chapter.paragraphs.joinToString("\n"))
        }
        File(dir, "book.json").writeAtomically(json.encodeToString(BookMeta(title, chapters.map { it.title })))
        return Book(dir)
    }
}
