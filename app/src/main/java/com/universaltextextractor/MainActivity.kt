package com.universaltextextractor

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import com.universaltextextractor.capture.CaptureIntents
import com.universaltextextractor.data.HistoryRepository
import com.universaltextextractor.ui.AppPage
import com.universaltextextractor.ui.ExtractorApp
import com.universaltextextractor.ui.ExtractorTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val pageState = androidx.compose.runtime.mutableStateOf(AppPage.Home)
    private val editorState = androidx.compose.runtime.mutableStateOf(TextFieldValue(""))
    private val historyIdState = androidx.compose.runtime.mutableStateOf<Long?>(null)
    private val messageState = androidx.compose.runtime.mutableStateOf<String?>(null)
    private var receiverRegistered = false

    private val captureReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                CaptureIntents.ACTION_TEXT_READY -> {
                    val text = intent.getStringExtra(CaptureIntents.EXTRA_TEXT).orEmpty()
                    val id = intent.getLongExtra(CaptureIntents.EXTRA_HISTORY_ID, -1L).takeIf { it > 0 }
                    if (text.isNotBlank()) showEditor(text, id)
                }
                CaptureIntents.ACTION_CAPTURE_STATUS -> {
                    messageState.value = intent.getStringExtra(CaptureIntents.EXTRA_STATUS_MESSAGE)
                        ?: "Screen capture didn't finish."
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleLaunchIntent(intent)
        setContent {
            ExtractorTheme {
                ExtractorApp(
                    page = pageState.value,
                    editorValue = editorState.value,
                    historyId = historyIdState.value,
                    pendingMessage = messageState.value,
                    onPageChange = { pageState.value = it },
                    onEditorChange = { editorState.value = it },
                    onOpenEntry = { text, id -> showEditor(text, id) },
                    onCapture = {
                        startActivity(Intent(this, CapturePermissionActivity::class.java))
                    },
                    onMessageConsumed = { messageState.value = null },
                    onSaved = { id -> historyIdState.value = id },
                )
            }
        }
    }

    override fun onStart() {
        super.onStart()
        if (!receiverRegistered) {
            val filter = IntentFilter().apply {
                addAction(CaptureIntents.ACTION_TEXT_READY)
                addAction(CaptureIntents.ACTION_CAPTURE_STATUS)
            }
            ContextCompat.registerReceiver(this, captureReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
            receiverRegistered = true
        }
    }

    override fun onStop() {
        if (receiverRegistered) {
            unregisterReceiver(captureReceiver)
            receiverRegistered = false
        }
        super.onStop()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleLaunchIntent(intent)
    }

    private fun handleLaunchIntent(launchIntent: Intent?) {
        if (launchIntent == null) return
        val text = launchIntent.getStringExtra(CaptureIntents.EXTRA_TEXT)
        if (!text.isNullOrBlank()) {
            val id = launchIntent.getLongExtra(CaptureIntents.EXTRA_HISTORY_ID, -1L).takeIf { it > 0 }
            showEditor(text, id)
            return
        }
        val id = launchIntent.getLongExtra(CaptureIntents.EXTRA_HISTORY_ID, -1L)
        if (id > 0 && launchIntent.action == CaptureIntents.ACTION_OPEN_TEXT) {
            lifecycleScope.launch {
                val entry = runCatching { HistoryRepository.get(this@MainActivity).getById(id) }.getOrNull()
                if (entry != null) showEditor(entry.text, entry.id)
                else messageState.value = "That history item is no longer available."
            }
        }
    }

    private fun showEditor(text: String, id: Long?) {
        editorState.value = TextFieldValue(text, selection = TextRange(0))
        historyIdState.value = id
        pageState.value = AppPage.Editor
    }
}
