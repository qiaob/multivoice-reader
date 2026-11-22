package io.github.qiaob.multivoice.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.qiaob.multivoice.data.AppLog
import kotlinx.coroutines.launch

/** The log, to copy and send when something goes wrong. */
@Composable
fun LogScreen(modifier: Modifier, snackbar: SnackbarHostState) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var report by remember { mutableStateOf(AppLog.report()) }
    Column(modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Text(
            "出错、崩溃、拆分和试模型的情况都记在这里。遇到问题时点「复制全部」，粘贴发给开发者。",
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(vertical = 8.dp),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                report = AppLog.report()
                context.getSystemService(ClipboardManager::class.java)
                    .setPrimaryClip(ClipData.newPlainText("多声朗读日志", report))
                scope.launch { snackbar.showSnackbar("已复制，共 ${report.length} 字") }
            }) { Text("复制全部") }
            OutlinedButton(onClick = {
                report = AppLog.report()
                val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, report)
                context.startActivity(Intent.createChooser(send, "发送日志"))
            }) { Text("分享") }
            TextButton(onClick = { report = AppLog.report() }) { Text("刷新") }
            TextButton(onClick = { AppLog.clear(); report = AppLog.report() }) { Text("清空") }
        }
        SelectionContainer(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).horizontalScroll(rememberScrollState()),
        ) {
            Text(report, fontFamily = FontFamily.Monospace, fontSize = 11.sp, lineHeight = 15.sp)
        }
    }
}
