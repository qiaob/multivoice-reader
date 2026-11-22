package io.github.qiaob.multivoice.ui

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext

/** Where the user is: a tab of the home screen, a book, or one chapter of it. */
sealed interface Place {
    data class Home(val tab: Int) : Place
    data class OfBook(val id: String) : Place
    data class OfChapter(val id: String, val chapter: Int) : Place
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT >= 33) {
            registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
                .launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent { Theme { App() } }
    }
}

@Composable
fun Theme(content: @Composable () -> Unit) {
    val context = LocalContext.current
    val dark = isSystemInDarkTheme()
    val colors = when {
        Build.VERSION.SDK_INT >= 31 -> if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        dark -> darkColorScheme()
        else -> lightColorScheme()
    }
    MaterialTheme(colorScheme = colors, content = content)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App() {
    var stack by remember { mutableStateOf(listOf<Place>(Place.Home(0))) }
    var tab by rememberSaveable { mutableStateOf(0) }
    val place = stack.last()
    val go: (Place) -> Unit = { stack = stack + it }
    val back: () -> Unit = { stack = stack.dropLast(1) }
    val snackbar = remember { SnackbarHostState() }
    BackHandler(enabled = stack.size > 1, onBack = back)

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        when (place) {
                            is Place.Home -> "多声朗读 · " + listOf("书架", "模型", "日志")[tab]
                            is Place.OfBook -> io.github.qiaob.multivoice.data.Library.open(place.id)?.title ?: ""
                            is Place.OfChapter ->
                                io.github.qiaob.multivoice.data.Library.open(place.id)?.chapters?.getOrNull(place.chapter) ?: ""
                        },
                        maxLines = 1,
                    )
                },
                navigationIcon = {
                    if (stack.size > 1) {
                        IconButton(onClick = back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回") }
                    }
                },
            )
        },
        bottomBar = {
            if (place is Place.Home) {
                NavigationBar {
                    NavigationBarItem(tab == 0, { tab = 0 }, { Icon(Icons.Filled.MenuBook, null) }, label = { Text("书架") })
                    NavigationBarItem(tab == 1, { tab = 1 }, { Icon(Icons.Filled.Memory, null) }, label = { Text("模型") })
                    NavigationBarItem(tab == 2, { tab = 2 }, { Icon(Icons.Filled.BugReport, null) }, label = { Text("日志") })
                }
            }
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        val modifier = Modifier.padding(padding)
        when (place) {
            is Place.Home -> when (tab) {
                0 -> BooksScreen(modifier, snackbar) { go(Place.OfBook(it)) }
                1 -> ModelsScreen(modifier)
                else -> LogScreen(modifier, snackbar)
            }
            is Place.OfBook -> BookScreen(place.id, modifier, snackbar, onChapter = { go(Place.OfChapter(place.id, it)) }, onGone = back)
            is Place.OfChapter -> ChapterScreen(place.id, place.chapter, modifier)
        }
    }
}
