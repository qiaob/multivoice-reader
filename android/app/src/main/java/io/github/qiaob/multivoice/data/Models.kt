package io.github.qiaob.multivoice.data

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import java.io.File

/**
 * The labelling models the app can use: a base model, downloaded once as a GGUF file, and the
 * fine-tuned adapter for it, which comes with the app (made from finetune/adapters).
 */
data class LabelModel(
    val id: String,
    val name: String,
    val about: String,
    val file: String,
    val sizeGb: Double,
    val sources: List<Pair<String, String>>, // label to URL
)

object Models {
    val ALL = listOf(
        LabelModel(
            id = "qwen3-1.7b",
            name = "Qwen3-1.7B 微调版",
            about = "最快最省内存。电脑上的准确率：说话人 90%，情绪 96%",
            file = "Qwen3-1.7B-Q8_0.gguf",
            sizeGb = 1.8,
            sources = listOf(
                "魔搭" to "https://modelscope.cn/models/Qwen/Qwen3-1.7B-GGUF/resolve/master/Qwen3-1.7B-Q8_0.gguf",
                "Hugging Face" to "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q8_0.gguf",
            ),
        ),
        LabelModel(
            id = "qwen3.5-4b",
            name = "Qwen3.5-4B 微调版",
            about = "最准，慢一倍。电脑上的准确率：说话人 97%，情绪 98%",
            file = "Qwen3.5-4B-Q4_K_M.gguf",
            sizeGb = 2.7,
            sources = listOf(
                "魔搭" to "https://modelscope.cn/models/unsloth/Qwen3.5-4B-GGUF/resolve/master/Qwen3.5-4B-Q4_K_M.gguf",
                "Hugging Face" to "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf",
            ),
        ),
    )

    fun get(id: String) = ALL.first { it.id == id }

    private fun dir(context: Context) = File(context.getExternalFilesDir(null), "models").apply { mkdirs() }

    fun baseFile(context: Context, model: LabelModel) = File(dir(context), model.file)

    /** Where a download is written until it is complete, so a half file is never used. */
    private fun partFile(context: Context, model: LabelModel) = File(dir(context), model.file + ".part")

    fun ready(context: Context, model: LabelModel) = baseFile(context, model).let { it.isFile && it.length() > 100_000_000 }

    /** The adapter, copied out of the app once so llama.cpp can open it as a file. */
    fun adapterFile(context: Context, model: LabelModel): File {
        val out = File(context.filesDir, "adapters/${model.id}.gguf")
        val asset = "adapters/${model.id}.gguf"
        val size = context.assets.openFd(asset).use { it.length }
        if (!out.isFile || out.length() != size) {
            out.parentFile!!.mkdirs()
            val tmp = File(out.path + ".tmp")
            context.assets.open(asset).use { input -> tmp.outputStream().use { input.copyTo(it) } }
            tmp.renameTo(out)
        }
        return out
    }

    // ---- downloading ----
    private fun prefs(context: Context) = context.getSharedPreferences("downloads", Context.MODE_PRIVATE)

    fun download(context: Context, model: LabelModel, url: String) {
        cancel(context, model)
        val request = DownloadManager.Request(Uri.parse(url))
            .setTitle(model.name)
            .setDescription(model.file)
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
            .setDestinationUri(Uri.fromFile(partFile(context, model)))
            .setAllowedOverMetered(true)
        val id = context.getSystemService(DownloadManager::class.java).enqueue(request)
        prefs(context).edit().putLong(model.id, id).apply()
    }

    fun cancel(context: Context, model: LabelModel) {
        val id = prefs(context).getLong(model.id, -1)
        if (id >= 0) context.getSystemService(DownloadManager::class.java).remove(id)
        prefs(context).edit().remove(model.id).apply()
        partFile(context, model).delete()
    }

    data class Progress(val done: Long, val total: Long, val failed: String?)

    /** How a download is going; null if none is. A finished one is moved into place here. */
    fun progress(context: Context, model: LabelModel): Progress? {
        val id = prefs(context).getLong(model.id, -1)
        if (id < 0) return null
        val manager = context.getSystemService(DownloadManager::class.java)
        manager.query(DownloadManager.Query().setFilterById(id)).use { c ->
            if (!c.moveToFirst()) {
                prefs(context).edit().remove(model.id).apply()
                return null
            }
            val status = c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
            val done = c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
            val total = c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
            return when (status) {
                DownloadManager.STATUS_SUCCESSFUL -> {
                    partFile(context, model).renameTo(baseFile(context, model))
                    prefs(context).edit().remove(model.id).apply()
                    null
                }
                DownloadManager.STATUS_FAILED -> {
                    val reason = c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON))
                    Progress(done, total, "下载失败（代码 $reason），换一个来源试试")
                }
                else -> Progress(done, total, null)
            }
        }
    }

    /** Copy a model file the user already has (picked with the system's file picker). */
    fun import(context: Context, model: LabelModel, uri: Uri, onProgress: (Long) -> Unit) {
        val part = partFile(context, model)
        context.contentResolver.openInputStream(uri)!!.use { input ->
            part.outputStream().use { output ->
                val buffer = ByteArray(1 shl 20)
                var copied = 0L
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    output.write(buffer, 0, n)
                    copied += n
                    onProgress(copied)
                }
            }
        }
        val head = part.inputStream().use { input -> ByteArray(4).also { input.read(it) }.toString(Charsets.US_ASCII) }
        if (head != "GGUF") {
            part.delete()
            throw IllegalArgumentException("这不是 GGUF 格式的模型文件")
        }
        part.renameTo(baseFile(context, model))
    }

    fun remove(context: Context, model: LabelModel) {
        cancel(context, model)
        baseFile(context, model).delete()
    }
}
