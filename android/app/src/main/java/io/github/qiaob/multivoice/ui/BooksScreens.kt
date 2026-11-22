package io.github.qiaob.multivoice.ui

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import io.github.qiaob.multivoice.core.ScriptFormat
import io.github.qiaob.multivoice.data.Book
import io.github.qiaob.multivoice.data.Library
import io.github.qiaob.multivoice.data.Models
import io.github.qiaob.multivoice.work.Splitter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun BooksScreen(modifier: Modifier, snackbar: SnackbarHostState, onBook: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var books by remember { mutableStateOf(Library.all()) }
    var busy by remember { mutableStateOf(false) }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris: List<Uri> ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        busy = true
        scope.launch {
            for (uri in uris) {
                val name = context.contentResolver.query(uri, null, null, null, null)?.use { c ->
                    c.moveToFirst()
                    c.getString(c.getColumnIndexOrThrow(OpenableColumns.DISPLAY_NAME))
                } ?: "小说.txt"
                try {
                    withContext(Dispatchers.IO) {
                        Library.add(name, context.contentResolver.openInputStream(uri)!!.use { it.readBytes() })
                    }
                } catch (e: Exception) {
                    snackbar.showSnackbar(e.message ?: "导入失败")
                }
            }
            books = Library.all()
            busy = false
        }
    }
    Box(modifier.fillMaxSize()) {
        if (books.isEmpty()) {
            Text(
                "还没有书。点右下角导入 txt 小说。\n\n先到「模型」页下载一个模型，才能拆分。",
                Modifier.align(Alignment.Center).padding(32.dp),
                style = MaterialTheme.typography.bodyLarge,
            )
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 96.dp)) {
            items(books, key = { it.id }) { book ->
                val done = remember(book.id) { book.done() }
                ListItem(
                    headlineContent = { Text(book.title) },
                    supportingContent = { Text("共 ${book.chapters.size} 章，已拆 ${done.count { it }} 章") },
                    modifier = Modifier.clickable { onBook(book.id) },
                )
                HorizontalDivider()
            }
        }
        ExtendedFloatingActionButton(
            onClick = { if (!busy) pick.launch(arrayOf("text/plain")) },
            icon = { Icon(Icons.Filled.Add, null) },
            text = { Text(if (busy) "导入中…" else "导入小说") },
            modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp),
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun BookScreen(id: String, modifier: Modifier, snackbar: SnackbarHostState, onChapter: (Int) -> Unit, onGone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val book = remember(id) { Library.open(id) } ?: return
    val split by Splitter.state.collectAsState()
    var done by remember { mutableStateOf(book.done()) }
    LaunchedEffect(split.done, split.running) { done = book.done() }
    val ready = Models.ALL.filter { Models.ready(context, it) }
    var model by remember { mutableStateOf(ready.firstOrNull()?.id) }
    var until by remember { mutableStateOf("${minOf(book.chapters.size, done.count { it } + 3)}") }
    var asking by remember { mutableStateOf(false) }
    val mine = split.bookId == book.id
    val export = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            try {
                withContext(Dispatchers.IO) {
                    val text = book.script().dumps()
                    context.contentResolver.openOutputStream(uri)!!.use { it.write(text.toByteArray()) }
                }
                snackbar.showSnackbar("已导出，电脑版的朗读页可以直接打开")
            } catch (e: Exception) {
                snackbar.showSnackbar(e.message ?: "导出失败")
            }
        }
    }
    LaunchedEffect(split.error) {
        if (mine && split.error != null) {
            snackbar.showSnackbar(split.error!!)
            Splitter.clearError()
        }
    }

    LazyColumn(modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp)) {
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("共 ${book.chapters.size} 章，已拆 ${done.count { it }} 章", style = MaterialTheme.typography.titleMedium)
                    if (ready.isEmpty()) {
                        Text("还没有可用的模型：先到「模型」页下载。", color = MaterialTheme.colorScheme.error)
                    } else {
                        Text("拆分用的模型", style = MaterialTheme.typography.labelLarge)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            ready.forEach { m ->
                                FilterChip(model == m.id, { model = m.id }, label = { Text(m.name) })
                            }
                        }
                    }
                    if (split.running && mine) {
                        Text("${split.model}：${split.now}", style = MaterialTheme.typography.bodyMedium)
                        LinearProgressIndicator(
                            progress = { if (split.todo == 0) 0f else split.done.toFloat() / split.todo },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        val speed = split.charsPerSecond?.let { "，上一章每秒 %.0f 字".format(it) } ?: ""
                        Text("这次 ${split.done} / ${split.todo} 章$speed", style = MaterialTheme.typography.bodySmall)
                        OutlinedButton(onClick = { Splitter.stop(context) }) { Text("停止") }
                    } else {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            OutlinedTextField(
                                until, { until = it.filter(Char::isDigit) },
                                label = { Text("拆到第几章") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                modifier = Modifier.width(140.dp),
                            )
                            Spacer(Modifier.width(12.dp))
                            Button(
                                enabled = model != null && !split.running,
                                onClick = {
                                    val n = (until.toIntOrNull() ?: 1).coerceIn(1, book.chapters.size)
                                    Splitter.start(context, book.id, n, model!!)
                                },
                            ) { Text("拆分") }
                        }
                        if (split.running) Text("正在拆另一本书，等它结束", style = MaterialTheme.typography.bodySmall)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(enabled = done.firstOrNull() == true, onClick = { export.launch("${book.title}.json") }) {
                            Text("导出朗读脚本")
                        }
                        TextButton(enabled = !(split.running && mine), onClick = { asking = true }) { Text("删除这本书") }
                    }
                }
            }
        }
        val characters = book.characters()
        if (characters.isNotEmpty()) {
            item {
                Text("角色", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 16.dp, bottom = 8.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    characters.forEach { (name, role) ->
                        AssistChip({}, label = { Text("$name · ${role.gender} · ${role.age} · ${role.lines} 句") })
                    }
                }
            }
        }
        item { Text("章节", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 16.dp)) }
        itemsIndexed(book.chapters) { k, title ->
            val result = if (done.getOrElse(k) { false }) remember(k, done) { book.result(k) } else null
            ListItem(
                headlineContent = { Text(title) },
                supportingContent = result?.let { r ->
                    { Text("%d 字，用时 %.0f 秒，每秒 %.0f 字".format(r.chars, r.seconds, r.chars / r.seconds)) }
                },
                trailingContent = if (result != null) ({ Icon(Icons.Filled.CheckCircle, "已拆分") }) else null,
                modifier = Modifier.clickable(enabled = result != null) { onChapter(k) },
            )
        }
    }
    if (asking) {
        AlertDialog(
            onDismissRequest = { asking = false },
            title = { Text("删除《${book.title}》？") },
            text = { Text("拆分的结果也会一起删掉。") },
            confirmButton = { TextButton({ asking = false; book.remove(); onGone() }) { Text("删除") } },
            dismissButton = { TextButton({ asking = false }) { Text("取消") } },
        )
    }
}

/** A colour for each speaker, the same every time. */
fun speakerColor(name: String): Color {
    val hues = listOf(0xFF1565C0, 0xFFC62828, 0xFF2E7D32, 0xFF6A1B9A, 0xFFEF6C00, 0xFF00838F, 0xFFAD1457, 0xFF4E342E)
    return Color(hues[Math.floorMod(name.hashCode(), hues.size)])
}

@Composable
fun ChapterScreen(id: String, chapter: Int, modifier: Modifier) {
    val book = remember(id) { Library.open(id) } ?: return
    val result = remember(id, chapter) { book.result(chapter) } ?: return
    val paragraphs = result.lines.groupBy { it.para }.values.toList()
    LazyColumn(modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp)) {
        item {
            Surface(color = MaterialTheme.colorScheme.secondaryContainer, shape = MaterialTheme.shapes.medium) {
                Text(
                    "%s · %d 字 · %.1f 秒 · 每秒 %.0f 字\n读了 %d 个词元，写了 %d 个".format(
                        Models.get(result.model).name, result.chars, result.seconds, result.chars / result.seconds,
                        result.promptTokens, result.answerTokens,
                    ),
                    Modifier.padding(12.dp),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Spacer(Modifier.width(8.dp))
        }
        items(paragraphs) { lines ->
            Text(
                buildAnnotatedString {
                    for (line in lines) {
                        if (line.kind == "narration") {
                            append(line.text)
                            continue
                        }
                        val color = if (line.speaker == ScriptFormat.SYSTEM) Color(0xFF00897B) else speakerColor(line.speaker)
                        withStyle(SpanStyle(color = color, fontWeight = FontWeight.Bold)) {
                            val feeling = if (line.emotion == ScriptFormat.NEUTRAL) "" else "·${line.emotion}"
                            append("［${line.speaker}$feeling］")
                        }
                        withStyle(SpanStyle(color = color)) {
                            append(if (line.kind == "system") line.text else "“${line.text}”")
                        }
                    }
                },
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.padding(vertical = 6.dp),
            )
        }
    }
}
