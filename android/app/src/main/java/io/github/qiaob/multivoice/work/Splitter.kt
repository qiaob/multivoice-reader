package io.github.qiaob.multivoice.work

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.PowerManager
import io.github.qiaob.multivoice.core.Analyzer
import io.github.qiaob.multivoice.core.LanguageModel
import io.github.qiaob.multivoice.core.Line
import io.github.qiaob.multivoice.core.Split
import io.github.qiaob.multivoice.core.Text
import io.github.qiaob.multivoice.data.Book
import io.github.qiaob.multivoice.data.ChapterResult
import io.github.qiaob.multivoice.data.LabelModel
import io.github.qiaob.multivoice.data.Library
import io.github.qiaob.multivoice.data.LineDto
import io.github.qiaob.multivoice.data.Models
import io.github.qiaob.multivoice.llm.Llama
import io.github.qiaob.multivoice.ui.MainActivity
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.coroutines.coroutineContext

data class SplitState(
    val running: Boolean = false,
    val bookId: String? = null,
    val model: String = "",
    val now: String = "",
    val done: Int = 0,
    val todo: Int = 0,
    val charsPerSecond: Double? = null,
    val error: String? = null,
)

/** A try of a model on a short passage, to see that it works and how fast it is. */
data class TryResult(
    val lines: List<Line>,
    val seconds: Double,
    val stats: Llama.Stats,
    val templateWarning: String?,
)

object Splitter {
    private val _state = MutableStateFlow(SplitState())
    val state: StateFlow<SplitState> = _state

    private val lock = Mutex() // one model in memory, one job at a time
    private var loaded: Triple<String, Int, Llama>? = null

    fun threads(context: Context) = context.getSharedPreferences("settings", Context.MODE_PRIVATE).getInt("threads", 6)

    fun setThreads(context: Context, n: Int) =
        context.getSharedPreferences("settings", Context.MODE_PRIVATE).edit().putInt("threads", n).apply()

    private fun llama(context: Context, model: LabelModel): Llama {
        val threads = threads(context)
        loaded?.let { (id, n, llama) -> if (id == model.id && n == threads) return llama else llama.close() }
        loaded = null
        if (!Models.ready(context, model)) throw IllegalStateException("${model.name} 的模型文件还没下载")
        val llama = Llama.load(Models.baseFile(context, model).path, Models.adapterFile(context, model).path, threads)
        loaded = Triple(model.id, threads, llama)
        return llama
    }

    private fun release() {
        loaded?.third?.close()
        loaded = null
    }

    /** A model that gives up between questions once the job is cancelled. */
    private suspend fun cancellable(llama: Llama): LanguageModel {
        val job = coroutineContext[Job]!!
        return LanguageModel { prompt, maxTokens, tuned ->
            if (!job.isActive) throw CancellationException()
            llama.ask(prompt, maxTokens, tuned)
        }
    }

    /** Split [book]'s chapters in order, up to [until], skipping those already split. */
    internal suspend fun run(context: Context, book: Book, until: Int, model: LabelModel) = lock.withLock {
        val todo = book.done().take(until).withIndex().filter { !it.value }.map { it.index }
        _state.value = SplitState(true, book.id, model.name, "加载模型", 0, todo.size)
        try {
            val llama = llama(context, model)
            val analyzer = Analyzer(cancellable(llama))
            var characters = book.characters()
            for ((n, k) in todo.withIndex()) {
                coroutineContext.ensureActive()
                _state.value = _state.value.copy(now = book.chapters[k], done = n)
                val paragraphs = book.paragraphs(k)
                val before = llama.stats()
                val start = System.nanoTime()
                val working = LinkedHashMap(characters) // kept only if the chapter is finished
                val lines = Split.splitChapter(paragraphs, working, analyzer)
                val seconds = (System.nanoTime() - start) / 1e9
                val after = llama.stats()
                val chars = paragraphs.sumOf { it.codePointCount(0, it.length) }
                book.saveResult(
                    k,
                    ChapterResult(
                        model.id,
                        lines.map { LineDto(it.kind, it.text, it.para, it.speaker, it.emotion) },
                        chars,
                        seconds,
                        after.promptTokens - before.promptTokens,
                        after.answerTokens - before.answerTokens,
                    ),
                )
                characters = working
                book.saveCharacters(characters)
                _state.value = _state.value.copy(done = n + 1, charsPerSecond = chars / seconds)
            }
            _state.value = _state.value.copy(running = false, now = "")
        } catch (e: CancellationException) {
            _state.value = _state.value.copy(running = false, now = "", error = "已停止")
        } catch (e: Throwable) {
            _state.value = _state.value.copy(running = false, now = "", error = e.message ?: e.toString())
        } finally {
            release() // give the memory back while nothing is being split
        }
    }

    suspend fun tryModel(context: Context, model: LabelModel): TryResult = lock.withLock {
        try {
            val llama = llama(context, model)
            val template = llama.chatTemplate()
            val warning = when {
                template.isEmpty() -> "模型文件里没有聊天模板，无法核对提示格式"
                "<|im_start|>" !in template || "enable_thinking" !in template ->
                    "模型自带的聊天模板和 Qwen3 的不一样，提示格式可能和训练时不同"
                else -> null
            }
            val before = llama.stats()
            val start = System.nanoTime()
            val characters = LinkedHashMap<String, io.github.qiaob.multivoice.core.Role>()
            val paragraphs = Text.splitChapters(SAMPLE).first().paragraphs
            val split = Split.splitChapter(paragraphs, characters, Analyzer(llama))
            val seconds = (System.nanoTime() - start) / 1e9
            val after = llama.stats()
            TryResult(
                Split.script("试读", characters, listOf("夜雨" to split)).chapters.first().lines,
                seconds,
                Llama.Stats(
                    after.promptTokens - before.promptTokens,
                    after.answerTokens - before.answerTokens,
                    after.promptSeconds - before.promptSeconds,
                    after.answerSeconds - before.answerSeconds,
                ),
                warning,
            )
        } finally {
            release()
        }
    }

    // An original passage (the one docs/samples/night-rain.json reads), with the cues a novel gives.
    private val SAMPLE = """
        第一章 夜雨
        夜色渐深，老街尽头的路灯忽明忽暗。雨下了整整一夜，屋檐下的水珠连成了线。
        林晚推开门的时候，周远正坐在窗边，手里捏着那封拆开的信。
        “你还没睡？”林晚轻声问。
        周远猛地站起来：“你到底还要骗我多久？”
        林晚愣在门口，雨水顺着伞尖滴在地板上。
        “我不是想骗你……我只是不知道该怎么开口。”她的声音发颤。
        里屋的门吱呀一声开了，奶奶披着外衣走出来。
        “大半夜的，吵什么呢？哎呀，晚晚回来了！”
        奶奶拉住林晚的手，笑得合不拢嘴：“回来就好，回来就好，锅里还给你留着汤呢。”
        “奶奶，您先去睡吧，我们没事。”周远说。
        周远把信折好放进口袋，声音低了下来：“先喝汤吧。有什么话，明天再说。”
    """.trimIndent()

    fun start(context: Context, bookId: String, until: Int, modelId: String) {
        val intent = Intent(context, SplitService::class.java)
            .putExtra("book", bookId).putExtra("until", until).putExtra("model", modelId)
        context.startForegroundService(intent)
    }

    fun stop(context: Context) {
        context.startService(Intent(context, SplitService::class.java).setAction(SplitService.STOP))
    }

    fun clearError() {
        _state.value = _state.value.copy(error = null)
    }
}

/** Keeps splitting going with the screen off: a foreground service with a notification. */
class SplitService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var job: Job? = null
    private var wake: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(1, notification("准备拆分"), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (intent?.action == STOP || intent == null) {
            job?.cancel()
            if (job == null) stopSelf()
            return START_NOT_STICKY
        }
        if (job?.isActive == true) return START_NOT_STICKY
        val book = Library.open(intent.getStringExtra("book")!!) ?: return START_NOT_STICKY.also { stopSelf() }
        val model = Models.get(intent.getStringExtra("model")!!)
        val until = intent.getIntExtra("until", 1)
        wake = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "mvr:split").apply { acquire(6 * 3600_000L) }
        job = scope.launch {
            val updates = launch {
                Splitter.state.collect { s ->
                    if (s.running) notify(notification("《${book.title}》${s.now}（${s.done}/${s.todo}）"))
                }
            }
            Splitter.run(applicationContext, book, until, model)
            updates.cancel()
            stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        wake?.takeIf { it.isHeld }?.release()
        super.onDestroy()
    }

    private fun notify(n: Notification) = getSystemService(NotificationManager::class.java).notify(1, n)

    private fun notification(text: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "拆分", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("正在拆分")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    companion object {
        const val STOP = "stop"
        private const val CHANNEL = "split"
    }
}
