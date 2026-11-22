package io.github.qiaob.multivoice.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import io.github.qiaob.multivoice.core.ScriptFormat
import io.github.qiaob.multivoice.data.AppLog
import io.github.qiaob.multivoice.data.LabelModel
import io.github.qiaob.multivoice.data.Models
import io.github.qiaob.multivoice.work.Splitter
import io.github.qiaob.multivoice.work.TryResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun ModelsScreen(modifier: Modifier) {
    val context = LocalContext.current
    var threads by remember { mutableFloatStateOf(Splitter.threads(context).toFloat()) }
    LazyColumn(modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text(
                "拆分小说要用一个判断「谁说的、什么情绪」的模型。底座模型下载一次（约 2 到 3 GB），" +
                    "微调权重已经装在 app 里。全部在手机上运行。",
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        items(Models.ALL, key = { it.id }) { ModelCard(it) }
        item { SelfCheckCard() }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("用几个 CPU 核心：${threads.toInt()}", style = MaterialTheme.typography.titleSmall)
                    Slider(
                        threads, { threads = it }, valueRange = 2f..8f, steps = 5,
                        onValueChangeFinished = { Splitter.setThreads(context, threads.toInt()) },
                    )
                    Text("天玑 9500 是 1 个超大核 + 3 个大核 + 4 个小核。可以试试 4、6、8 哪个最快。", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ModelCard(model: LabelModel) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val split by Splitter.state.collectAsState()
    var tick by remember { mutableIntStateOf(0) }
    var ready by remember { mutableStateOf(Models.ready(context, model)) }
    var progress by remember { mutableStateOf(Models.progress(context, model)) }
    var importing by remember { mutableStateOf<Long?>(null) }
    val tries by Splitter.tries.collectAsState()
    val attempt = tries[model.id]
    var error by remember { mutableStateOf<String?>(null) }
    var custom by remember { mutableStateOf("") }
    LaunchedEffect(tick) {
        while (true) {
            progress = Models.progress(context, model)
            ready = Models.ready(context, model)
            if (progress == null) break
            delay(1000)
        }
    }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            importing = 0
            try {
                withContext(Dispatchers.IO) { Models.import(context, model, uri) { importing = it } }
            } catch (e: Throwable) {
                error = AppLog.error("导入 ${model.file}", e)
            }
            importing = null
            ready = Models.ready(context, model)
        }
    }

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(model.name, style = MaterialTheme.typography.titleMedium)
            Text(model.about, style = MaterialTheme.typography.bodySmall)
            val file = Models.baseFile(context, model)
            when {
                ready -> Text("已就绪：${model.file}（%.1f GB）".format(file.length() / 1e9), color = MaterialTheme.colorScheme.primary)
                importing != null -> {
                    Text("正在导入：%.2f GB".format(importing!! / 1e9))
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                }
                progress != null -> {
                    val p = progress!!
                    if (p.failed != null) {
                        Text(p.failed, color = MaterialTheme.colorScheme.error)
                    } else {
                        Text("下载中：%.2f / %.2f GB".format(p.done / 1e9, if (p.total > 0) p.total / 1e9 else model.sizeGb))
                        LinearProgressIndicator(
                            progress = { if (p.total > 0) p.done.toFloat() / p.total else 0f },
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    TextButton({ Models.cancel(context, model); tick++ }) { Text("取消下载") }
                }
                else -> Text("底座模型 ${model.file}，约 ${model.sizeGb} GB，还没下载")
            }
            if (!ready && progress == null && importing == null) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    model.sources.forEach { (label, url) ->
                        Button({ Models.download(context, model, url); tick++ }) { Text("从${label}下载") }
                    }
                    OutlinedButton({ pick.launch(arrayOf("*/*")) }) { Text("从手机里的文件导入") }
                }
                OutlinedTextField(
                    custom, { custom = it.trim() },
                    label = { Text("或者填一个下载地址（GGUF 文件）") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                if (custom.startsWith("http")) {
                    TextButton({ Models.download(context, model, custom); tick++ }) { Text("从这个地址下载") }
                }
            }
            if (ready) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        enabled = attempt?.running != true && !split.running,
                        onClick = { error = null; Splitter.startTry(context, model) },
                    ) { Text(if (attempt?.running == true) "正在试…" else "用一段示例试一下") }
                    TextButton(
                        enabled = attempt?.running != true && !split.running,
                        onClick = { Models.remove(context, model); ready = false; Splitter.clearTry(model) },
                    ) {
                        Text("删除模型文件")
                    }
                }
                if (attempt?.running == true) CircularProgressIndicator()
            }
            (error ?: attempt?.error)?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            attempt?.result?.let { TryCard(it) }
        }
    }
}

@Composable
private fun TryCard(result: TryResult) {
    val s = result.stats
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            "用时 %.1f 秒。读提示 %d 词元，每秒 %.0f；写回答 %d 词元，每秒 %.1f".format(
                result.seconds, s.promptTokens, s.promptTokens / s.promptSeconds, s.answerTokens, s.answerTokens / s.answerSeconds,
            ),
            style = MaterialTheme.typography.bodySmall,
        )
        result.templateWarning?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        Text("正确答案：林晚、周远（愤怒）、林晚（悲伤）、奶奶（惊讶）、奶奶（高兴）、周远、周远", style = MaterialTheme.typography.bodySmall)
        for (line in result.lines.filter { it.speaker != ScriptFormat.NARRATOR }) {
            Text(
                buildAnnotatedString {
                    withStyle(SpanStyle(color = speakerColor(line.speaker), fontWeight = FontWeight.Bold)) {
                        append(line.speaker)
                        if (line.emotion != ScriptFormat.NEUTRAL) append("·${line.emotion}")
                    }
                    append("：“${line.text}”")
                },
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

/** Run the Python reader's results through this phone's code (core's SelfCheck). */
@Composable
private fun SelfCheckCard() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var running by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<List<String>?>(null) }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("自检", style = MaterialTheme.typography.titleSmall)
            Text(
                "拿电脑版处理过的 50 段小说对照：切章切句、数字读法、问模型的每一句提示、读回答、配声音，结果是否一字不差。不用模型，几秒钟。",
                style = MaterialTheme.typography.bodySmall,
            )
            OutlinedButton(enabled = !running, onClick = {
                running = true
                scope.launch {
                    result = withContext(Dispatchers.Default) {
                        try {
                            io.github.qiaob.multivoice.core.SelfCheck.run { name ->
                                context.assets.open("golden/$name").use { it.readBytes().toString(Charsets.UTF_8) }
                            }
                        } catch (e: Throwable) {
                            listOf(AppLog.error("自检", e))
                        }
                    }
                    AppLog.info("自检", result!!.ifEmpty { listOf("全部一致") }.joinToString("\n\n"))
                    running = false
                }
            }) { Text(if (running) "正在对照…" else "开始自检") }
            result?.let { failures ->
                if (failures.isEmpty()) {
                    Text("全部一致", color = MaterialTheme.colorScheme.primary)
                } else {
                    failures.forEach { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                }
            }
        }
    }
}
