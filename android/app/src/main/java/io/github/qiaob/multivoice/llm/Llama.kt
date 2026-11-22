package io.github.qiaob.multivoice.llm

import io.github.qiaob.multivoice.core.Analyze
import io.github.qiaob.multivoice.core.LanguageModel
import java.io.Closeable

/**
 * A labelling model running on the phone (llama.cpp, see src/main/cpp): the base model as a
 * GGUF file, with the fine-tuned adapter put on to label lines and taken off otherwise.
 * Not thread-safe: one question at a time.
 */
class Llama private constructor(private var handle: Long) : LanguageModel, Closeable {
    /** Totals since it was loaded. */
    data class Stats(val promptTokens: Long, val answerTokens: Long, val promptSeconds: Double, val answerSeconds: Double)

    override fun ask(prompt: String, maxTokens: Int, tuned: Boolean): String =
        nativeAsk(handle, Analyze.qwen3Chat(prompt).toByteArray(Charsets.UTF_8), maxTokens, tuned)

    fun stats(): Stats = nativeStats(handle).let { Stats(it[0], it[1], it[2] / 1e6, it[3] / 1e6) }

    /** The chat template that came in the model file. */
    fun chatTemplate(): String = nativeChatTemplate(handle)

    override fun close() {
        nativeFree(handle)
        handle = 0
    }

    companion object {
        const val CONTEXT_TOKENS = 4096

        init {
            System.loadLibrary("mvr_llama")
        }

        /** IllegalStateException says in words what went wrong. */
        fun load(model: String, adapter: String?, threads: Int): Llama =
            Llama(nativeLoad(model, adapter ?: "", CONTEXT_TOKENS, threads))

        @JvmStatic private external fun nativeLoad(model: String, adapter: String, nCtx: Int, threads: Int): Long
        @JvmStatic private external fun nativeFree(handle: Long)
        @JvmStatic private external fun nativeAsk(handle: Long, text: ByteArray, maxTokens: Int, tuned: Boolean): String
        @JvmStatic private external fun nativeStats(handle: Long): LongArray
        @JvmStatic private external fun nativeChatTemplate(handle: Long): String
        @JvmStatic private external fun nativeLog(): String

        /** What llama.cpp has said since the app started (loading, warnings, errors). */
        fun log(): String = nativeLog()
    }
}
