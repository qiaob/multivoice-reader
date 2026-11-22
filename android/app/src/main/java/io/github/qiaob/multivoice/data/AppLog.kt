package io.github.qiaob.multivoice.data

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import io.github.qiaob.multivoice.llm.Llama
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * What happened in the app, to be copied from the log page and sent to whoever fixes it:
 * every error with its whole stack trace, crashes included (written before the app goes
 * down), and a few notes on what was being done. Kept in a file, so it outlives the app.
 */
object AppLog {
    private lateinit var file: File
    private lateinit var app: Context
    private const val KEEP_BYTES = 256 * 1024
    private val time = SimpleDateFormat("MM-dd HH:mm:ss", Locale.ROOT)

    fun init(context: Context) {
        app = context.applicationContext
        file = File(context.filesDir, "log.txt")
        val before = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, e ->
            try {
                write("崩溃", "线程 ${thread.name}\n${trace(e)}")
            } finally {
                before?.uncaughtException(thread, e)
            }
        }
    }

    fun info(where: String, message: String) = write(where, message)

    /** Log an error and give it back in a few words, for the screen. */
    fun error(where: String, e: Throwable): String {
        write("出错：$where", trace(e))
        return describe(e)
    }

    /** An error in words, with what caused it: a bare class name tells the user nothing. */
    fun describe(e: Throwable): String =
        generateSequence(e) { it.cause }.take(3).map { it.message ?: it.javaClass.simpleName }.distinct().joinToString("：")

    private fun trace(e: Throwable) = StringWriter().also { e.printStackTrace(PrintWriter(it)) }.toString().trim()

    @Synchronized
    private fun write(where: String, text: String) {
        try {
            file.appendText("[${time.format(Date())}] $where\n$text\n\n")
            if (file.length() > KEEP_BYTES) {
                val kept = file.readText().takeLast(KEEP_BYTES / 2)
                file.writeText(kept.substring(kept.indexOf("\n[").coerceAtLeast(0)))
            }
        } catch (_: Throwable) {
        }
    }

    @Synchronized
    fun entries(): String = if (::file.isInitialized && file.isFile) file.readText() else ""

    @Synchronized
    fun clear() {
        file.delete()
    }

    /** Everything worth sending: the phone, the app, the log, and what llama.cpp said. */
    fun report(): String {
        val memory = ActivityManager.MemoryInfo().also { app.getSystemService(ActivityManager::class.java).getMemoryInfo(it) }
        val version = app.packageManager.getPackageInfo(app.packageName, 0).versionName
        val native = try {
            Llama.log().ifBlank { "（还没有加载过模型）" }
        } catch (e: Throwable) {
            "模型库加载失败：${trace(e)}"
        }
        return buildString {
            appendLine("多声朗读 $version")
            appendLine("手机：${Build.MANUFACTURER} ${Build.MODEL}，Android ${Build.VERSION.RELEASE}（API ${Build.VERSION.SDK_INT}）")
            appendLine("芯片：$soc，${Build.SUPPORTED_ABIS.joinToString()}")
            appendLine("内存：共 %.1f GB，可用 %.1f GB".format(memory.totalMem / 1e9, memory.availMem / 1e9))
            appendLine()
            appendLine("==== 记录 ====")
            appendLine(entries().ifBlank { "（没有记录）" })
            appendLine("==== llama.cpp ====")
            appendLine(native.takeLast(16 * 1024))
        }
    }

    private val soc: String
        get() = if (Build.VERSION.SDK_INT >= 31) "${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}" else Build.HARDWARE
}
