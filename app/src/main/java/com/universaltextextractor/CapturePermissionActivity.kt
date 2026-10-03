package com.universaltextextractor

import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.universaltextextractor.capture.CaptureIntents
import com.universaltextextractor.capture.CaptureService
import com.universaltextextractor.ui.ExtractorTheme

class CapturePermissionActivity : ComponentActivity() {
    private var errorMessage by mutableStateOf<String?>(null)
    private var requesting by mutableStateOf(false)
    private var captureExplanationSeen = false

    companion object {
        private const val PREFS = "extractor_preferences"
        private const val KEY_CAPTURE_EXPLANATION_SEEN = "capture_explanation_seen"
    }

    private val captureConsent = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        requesting = false
        val data = result.data
        if (result.resultCode != RESULT_OK || data == null) {
            errorMessage = "Screen capture was cancelled. Nothing was captured."
            return@registerForActivityResult
        }

        try {
            val serviceIntent = Intent(this, CaptureService::class.java).apply {
                putExtra(CaptureIntents.EXTRA_RESULT_CODE, result.resultCode)
                putExtra(CaptureIntents.EXTRA_RESULT_DATA, data)
            }
            ContextCompat.startForegroundService(this, serviceIntent)
            finish()
        } catch (_: RuntimeException) {
            errorMessage = "Android couldn't start screen capture. Try again from the app or Quick Settings."
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        captureExplanationSeen = getSharedPreferences(PREFS, MODE_PRIVATE)
            .getBoolean(KEY_CAPTURE_EXPLANATION_SEEN, false)
        setContent {
            ExtractorTheme {
                CaptureRationaleScreen(
                    requesting = requesting,
                    errorMessage = errorMessage,
                    onBack = ::finish,
                    onContinue = ::requestCapture,
                    onDismissError = { errorMessage = null },
                )
            }
        }
        if (captureExplanationSeen && savedInstanceState == null) {
            window.decorView.post { requestCapture() }
        }
    }

    private fun requestCapture() {
        if (requesting) return
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
            .putBoolean(KEY_CAPTURE_EXPLANATION_SEEN, true)
            .apply()
        requesting = true
        try {
            val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            captureConsent.launch(manager.createScreenCaptureIntent())
        } catch (_: RuntimeException) {
            requesting = false
            errorMessage = "Screen capture isn't available on this device."
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@androidx.compose.runtime.Composable
private fun CaptureRationaleScreen(
    requesting: Boolean,
    errorMessage: String?,
    onBack: () -> Unit,
    onContinue: () -> Unit,
    onDismissError: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Before you capture") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Cancel")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 24.dp, vertical = 18.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "One screen. On-device OCR.",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                "Android will ask you to approve a one-time screen capture. Depending on your device, you may choose the screen or app to share.",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            InfoCard(
                icon = { Icon(Icons.Default.PhoneAndroid, contentDescription = null) },
                title = "Your screen stays on this device",
                body = "A single frame is processed locally. The screenshot is discarded after OCR; extracted text is saved only in your on-device history.",
            )
            InfoCard(
                icon = { Icon(Icons.Default.Lock, contentDescription = null) },
                title = "Protected screens stay protected",
                body = "Secure or DRM-protected areas may appear blank. We don't bypass those protections. Avoid using the extractor on passwords, sign-in, or verification screens.",
            )
            Spacer(Modifier.weight(1f))
            Button(
                onClick = onContinue,
                enabled = !requesting,
                modifier = Modifier.fillMaxWidth().height(54.dp),
            ) {
                Text(if (requesting) "Waiting for Android…" else "Continue to screen capture")
            }
            TextButton(onClick = onBack, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                Text("Cancel")
            }
        }
    }

    if (errorMessage != null) {
        AlertDialog(
            onDismissRequest = onDismissError,
            title = { Text("Capture not started") },
            text = { Text(errorMessage) },
            confirmButton = { TextButton(onClick = onDismissError) { Text("OK") } },
        )
    }
}

@androidx.compose.runtime.Composable
private fun InfoCard(
    icon: @androidx.compose.runtime.Composable () -> Unit,
    title: String,
    body: String,
) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            icon()
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(body, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
