package com.universaltextextractor.ui

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccessibilityNew
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DocumentScanner
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.universaltextextractor.data.HistoryEntry
import com.universaltextextractor.data.HistoryRepository
import com.universaltextextractor.settings.SettingsStore
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

enum class AppPage { Home, History, Settings, Editor }

@Composable
fun ExtractorApp(
    page: AppPage,
    editorValue: TextFieldValue,
    historyId: Long?,
    pendingMessage: String?,
    onPageChange: (AppPage) -> Unit,
    onEditorChange: (TextFieldValue) -> Unit,
    onOpenEntry: (String, Long?) -> Unit,
    onCapture: () -> Unit,
    onMessageConsumed: () -> Unit,
    onSaved: (Long) -> Unit,
) {
    val snackbarHost = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val repository = remember(context) { HistoryRepository.get(context) }

    LaunchedEffect(pendingMessage) {
        if (!pendingMessage.isNullOrBlank()) {
            snackbarHost.showSnackbar(pendingMessage)
            onMessageConsumed()
        }
    }
    BackHandler(enabled = page != AppPage.Home) { onPageChange(AppPage.Home) }

    Scaffold(snackbarHost = { SnackbarHost(snackbarHost) }) { padding ->
        when (page) {
            AppPage.Home -> HomeScreen(
                modifier = Modifier.fillMaxSize().padding(padding),
                onCapture = onCapture,
                onHistory = { onPageChange(AppPage.History) },
                onSettings = { onPageChange(AppPage.Settings) },
            )
            AppPage.History -> HistoryScreen(
                modifier = Modifier.fillMaxSize().padding(padding),
                onBack = { onPageChange(AppPage.Home) },
                onOpen = onOpenEntry,
                onCopy = { text -> copyToClipboard(context, text); scope.launch { snackbarHost.showSnackbar("Copied to clipboard") } },
                onShare = { text -> shareText(context, text) },
                onDelete = { id -> scope.launch { repository.delete(id); snackbarHost.showSnackbar("History item deleted") } },
            )
            AppPage.Settings -> SettingsScreen(
                modifier = Modifier.fillMaxSize().padding(padding),
                onBack = { onPageChange(AppPage.Home) },
                onClearHistory = {
                    scope.launch {
                        repository.clear()
                        snackbarHost.showSnackbar("History cleared")
                    }
                },
            )
            AppPage.Editor -> EditorScreen(
                modifier = Modifier.fillMaxSize().padding(padding),
                value = editorValue,
                onValueChange = onEditorChange,
                onBack = { onPageChange(AppPage.Home) },
                onSave = {
                    val text = editorValue.text.trim()
                    if (text.isBlank()) {
                        scope.launch { snackbarHost.showSnackbar("There is no text to save") }
                    } else {
                        scope.launch {
                            runCatching { repository.save(text, historyId) }
                                .onSuccess { id ->
                                    onSaved(id)
                                    snackbarHost.showSnackbar("Saved to history")
                                }
                                .onFailure { snackbarHost.showSnackbar("Couldn't save this text") }
                        }
                    }
                },
                onCopySelection = {
                    val selection = editorValue.selection
                    if (!selection.collapsed) {
                        val start = minOf(selection.start, selection.end).coerceIn(0, editorValue.text.length)
                        val end = maxOf(selection.start, selection.end).coerceIn(start, editorValue.text.length)
                        copyToClipboard(context, editorValue.text.substring(start, end))
                        scope.launch { snackbarHost.showSnackbar("Selection copied") }
                    } else {
                        scope.launch { snackbarHost.showSnackbar("Select text in the editor first") }
                    }
                },
                onCopyAll = {
                    copyToClipboard(context, editorValue.text)
                    scope.launch { snackbarHost.showSnackbar("All text copied") }
                },
                onShare = { shareText(context, editorValue.text) },
            )
        }
    }
}

@Composable
private fun HomeScreen(
    modifier: Modifier,
    onCapture: () -> Unit,
    onHistory: () -> Unit,
    onSettings: () -> Unit,
) {
    Column(
        modifier = modifier.verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(
                modifier = Modifier.size(48.dp).clip(RoundedCornerShape(15.dp)).background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.DocumentScanner, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            }
            Column {
                Text("Universal Text", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text("EXTRACTOR", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Copy text from any screen.", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "Capture what you can see, then select, edit, copy, or share the recognized text.",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Card(
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
            shape = RoundedCornerShape(24.dp),
        ) {
            Column(
                modifier = Modifier.fillMaxWidth().padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.Default.Lock, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Text("Private by design", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                }
                Text(
                    "OCR runs on this device. Screenshots are temporary and never added to history.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(onClick = onCapture, modifier = Modifier.fillMaxWidth().height(54.dp)) {
                    Icon(Icons.Default.DocumentScanner, contentDescription = null)
                    Spacer(Modifier.width(10.dp))
                    Text("Extract Text")
                }
            }
        }

        Text(
            "To capture another app, start from its screen with the Extract text Quick Settings tile or the optional floating button. Android will ask you to approve each capture.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
        NavigationCard(
            icon = { Icon(Icons.Default.History, contentDescription = null) },
            title = "History",
            subtitle = "Search and revisit recent extractions",
            onClick = onHistory,
        )
        NavigationCard(
            icon = { Icon(Icons.Default.Settings, contentDescription = null) },
            title = "Settings",
            subtitle = "Floating shortcut, notifications, and privacy",
            onClick = onSettings,
        )
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun NavigationCard(
    icon: @Composable () -> Unit,
    title: String,
    subtitle: String,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(18.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Box(
                modifier = Modifier.size(42.dp).clip(CircleShape).background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center,
            ) { icon() }
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Medium)
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun EditorScreen(
    modifier: Modifier,
    value: TextFieldValue,
    onValueChange: (TextFieldValue) -> Unit,
    onBack: () -> Unit,
    onSave: () -> Unit,
    onCopySelection: () -> Unit,
    onCopyAll: () -> Unit,
    onShare: () -> Unit,
) {
    Column(modifier = modifier.imePadding().padding(horizontal = 18.dp, vertical = 8.dp)) {
        PageHeader(title = "Extracted Text", onBack = onBack)
        Text(
            "Tap and hold to select. Copy uses your selection; Copy all copies the full text.",
            modifier = Modifier.padding(horizontal = 4.dp, vertical = 8.dp),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier.fillMaxWidth().weight(1f),
            placeholder = { Text("Recognized text will appear here") },
            textStyle = MaterialTheme.typography.bodyLarge,
            shape = RoundedCornerShape(18.dp),
            minLines = 8,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Default),
        )
        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            FilledTonalButton(onClick = onCopySelection, modifier = Modifier.weight(1f)) {
                Icon(Icons.Default.ContentCopy, contentDescription = null, modifier = Modifier.size(17.dp))
                Spacer(Modifier.width(5.dp))
                Text("Copy")
            }
            FilledTonalButton(onClick = onCopyAll, modifier = Modifier.weight(1f)) {
                Text("Copy all")
            }
            FilledTonalButton(onClick = onShare, modifier = Modifier.weight(1f)) {
                Icon(Icons.Default.Share, contentDescription = null, modifier = Modifier.size(17.dp))
                Spacer(Modifier.width(5.dp))
                Text("Share")
            }
        }
        TextButtonWithIcon(
            icon = { Icon(Icons.Default.Save, contentDescription = null, modifier = Modifier.size(18.dp)) },
            label = "Save edits to history",
            onClick = onSave,
            modifier = Modifier.align(Alignment.CenterHorizontally),
        )
    }
}

@Composable
private fun HistoryScreen(
    modifier: Modifier,
    onBack: () -> Unit,
    onOpen: (String, Long?) -> Unit,
    onCopy: (String) -> Unit,
    onShare: (String) -> Unit,
    onDelete: (Long) -> Unit,
) {
    val context = LocalContext.current
    val repository = remember(context) { HistoryRepository.get(context) }
    var query by rememberSaveable { mutableStateOf("") }
    var entries by remember { mutableStateOf(emptyList<HistoryEntry>()) }
    LaunchedEffect(query) {
        repository.observeSearch(query).collect { entries = it }
    }

    Column(modifier = modifier.padding(horizontal = 18.dp, vertical = 8.dp)) {
        PageHeader(title = "History", onBack = onBack)
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 12.dp),
            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
            placeholder = { Text("Search extracted text") },
            singleLine = true,
            shape = RoundedCornerShape(16.dp),
        )
        if (entries.isEmpty()) {
            EmptyState(
                icon = { Icon(Icons.Default.History, contentDescription = null) },
                title = if (query.isBlank()) "Nothing here yet" else "No matches",
                body = if (query.isBlank()) "Your recent extractions are saved locally on this device." else "Try another word or clear the search.",
                modifier = Modifier.weight(1f).fillMaxWidth(),
            )
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(entries, key = { it.id }) { entry ->
                    HistoryCard(
                        entry = entry,
                        onOpen = { onOpen(entry.text, entry.id) },
                        onCopy = { onCopy(entry.text) },
                        onShare = { onShare(entry.text) },
                        onDelete = { onDelete(entry.id) },
                    )
                }
            }
        }
    }
}

@Composable
private fun HistoryCard(
    entry: HistoryEntry,
    onOpen: () -> Unit,
    onCopy: () -> Unit,
    onShare: () -> Unit,
    onDelete: () -> Unit,
) {
    var menuExpanded by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onOpen),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(18.dp),
    ) {
        Row(modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 6.dp, top = 14.dp, bottom = 14.dp)) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(entry.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 1)
                Text(
                    entry.text.replace('\n', ' '),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                )
                Text(
                    DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(entry.createdAt)),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Box {
                IconButton(onClick = { menuExpanded = true }) {
                    Icon(Icons.Default.MoreVert, contentDescription = "More options")
                }
                DropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
                    DropdownMenuItem(
                        text = { Text("Copy") },
                        leadingIcon = { Icon(Icons.Default.ContentCopy, contentDescription = null) },
                        onClick = { menuExpanded = false; onCopy() },
                    )
                    DropdownMenuItem(
                        text = { Text("Share") },
                        leadingIcon = { Icon(Icons.Default.Share, contentDescription = null) },
                        onClick = { menuExpanded = false; onShare() },
                    )
                    DropdownMenuItem(
                        text = { Text("Delete") },
                        leadingIcon = { Icon(Icons.Default.Delete, contentDescription = null) },
                        onClick = { menuExpanded = false; confirmDelete = true },
                    )
                }
            }
        }
    }
    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Delete this item?") },
            text = { Text("This removes the text from local history.") },
            confirmButton = {
                TextButton(onClick = { confirmDelete = false; onDelete() }) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun SettingsScreen(
    modifier: Modifier,
    onBack: () -> Unit,
    onClearHistory: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var floatingEnabled by remember { mutableStateOf(SettingsStore.isFloatingButtonEnabled(context)) }
    var accessibilityEnabled by remember { mutableStateOf(SettingsStore.isAccessibilityServiceEnabled(context)) }
    var notificationsAllowed by remember { mutableStateOf(NotificationManagerCompat.from(context).areNotificationsEnabled()) }
    var showAccessibilityDialog by remember { mutableStateOf(false) }
    var showClearDialog by remember { mutableStateOf(false) }

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                floatingEnabled = SettingsStore.isFloatingButtonEnabled(context)
                accessibilityEnabled = SettingsStore.isAccessibilityServiceEnabled(context)
                notificationsAllowed = NotificationManagerCompat.from(context).areNotificationsEnabled()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    val notificationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        notificationsAllowed = NotificationManagerCompat.from(context).areNotificationsEnabled()
    }

    Column(modifier = modifier.verticalScroll(rememberScrollState()).padding(horizontal = 18.dp, vertical = 8.dp)) {
        PageHeader(title = "Settings", onBack = onBack)
        Text("Shortcuts", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 12.dp, bottom = 8.dp))
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(18.dp)) {
            Column(modifier = Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Icon(Icons.Default.AccessibilityNew, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Floating button", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                        Text(
                            if (accessibilityEnabled && floatingEnabled) "Enabled and ready" else if (floatingEnabled) "Turn on the service to show it" else "Optional drag-anywhere shortcut",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Switch(
                        checked = floatingEnabled,
                        onCheckedChange = { enabled ->
                            SettingsStore.setFloatingButtonEnabled(context, enabled)
                            floatingEnabled = enabled
                            if (enabled && !accessibilityEnabled) showAccessibilityDialog = true
                        },
                    )
                }
                HorizontalDivider()
                Text(
                    "Accessibility is used only to display this button. The service does not read screen text or window contents. You can disable it here or in Android Accessibility settings.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedButton(
                    onClick = { openAccessibilitySettings(context) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Default.AccessibilityNew, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Manage Accessibility service")
                }
            }
        }

        Text("Notifications", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 22.dp, bottom = 8.dp))
        SettingsInfoCard(
            icon = { Icon(Icons.Default.Notifications, contentDescription = null, tint = MaterialTheme.colorScheme.primary) },
            title = if (notificationsAllowed) "Results can notify you" else "Notifications are off",
            body = if (notificationsAllowed)
                "When a capture starts from another app, a notification lets you review the result or extract again. It never shows the extracted text."
            else
                "Allow notifications to review results started from Quick Settings or the floating button. You can still use the app without them.",
            actionLabel = if (notificationsAllowed) "Notification settings" else "Allow notifications",
            onAction = {
                if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                } else {
                    openNotificationSettings(context)
                }
            },
        )

        Text("Quick Settings", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 22.dp, bottom = 8.dp))
        SettingsInfoCard(
            icon = { Icon(Icons.Default.PhoneAndroid, contentDescription = null, tint = MaterialTheme.colorScheme.primary) },
            title = "Add the Extract text tile",
            body = "Open Quick Settings, tap Edit, then drag “Extract text” into your active tiles. Tap it from another app to start a capture.",
        )

        Text("Privacy", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 22.dp, bottom = 8.dp))
        SettingsInfoCard(
            icon = { Icon(Icons.Default.Security, contentDescription = null, tint = MaterialTheme.colorScheme.primary) },
            title = "Local, temporary screen capture",
            body = "OCR is on-device. Images are not saved or uploaded. Extracted text is kept in this app's local history until you delete it. Android-secured or DRM-protected areas may be blank and are never bypassed.",
        )
        OutlinedButton(onClick = { showClearDialog = true }, modifier = Modifier.fillMaxWidth().padding(top = 10.dp)) {
            Icon(Icons.Default.Delete, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Clear all history")
        }
        Spacer(Modifier.height(24.dp))
    }

    if (showAccessibilityDialog) {
        AlertDialog(
            onDismissRequest = { showAccessibilityDialog = false },
            icon = { Icon(Icons.Default.AccessibilityNew, contentDescription = null) },
            title = { Text("Enable the floating shortcut") },
            text = {
                Text("Android requires you to turn on the Universal Text Extractor service. It only draws the floating button; it does not inspect screen contents. You can keep using Extract Text and the Quick Settings tile without enabling it.")
            },
            confirmButton = {
                TextButton(onClick = { showAccessibilityDialog = false; openAccessibilitySettings(context) }) { Text("Open settings") }
            },
            dismissButton = {
                TextButton(onClick = {
                    showAccessibilityDialog = false
                    if (!accessibilityEnabled) {
                        SettingsStore.setFloatingButtonEnabled(context, false)
                        floatingEnabled = false
                    }
                }) { Text("Not now") }
            },
        )
    }
    if (showClearDialog) {
        AlertDialog(
            onDismissRequest = { showClearDialog = false },
            title = { Text("Clear all history?") },
            text = { Text("This permanently deletes extracted text stored on this device. Screenshots are not stored.") },
            confirmButton = {
                TextButton(onClick = { showClearDialog = false; onClearHistory() }) { Text("Clear history") }
            },
            dismissButton = { TextButton(onClick = { showClearDialog = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun SettingsInfoCard(
    icon: @Composable () -> Unit,
    title: String,
    body: String,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(18.dp)) {
        Column(modifier = Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                icon()
                Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            }
            Text(body, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (actionLabel != null && onAction != null) {
                TextButton(onClick = onAction, modifier = Modifier.align(Alignment.End)) { Text(actionLabel) }
            }
        }
    }
}

@Composable
private fun PageHeader(title: String, onBack: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
        IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, contentDescription = "Back") }
        Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun EmptyState(icon: @Composable () -> Unit, title: String, body: String, modifier: Modifier = Modifier) {
    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Box(
            modifier = Modifier.size(56.dp).clip(CircleShape).background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) { icon() }
        Text(title, modifier = Modifier.padding(top = 16.dp), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Text(body, modifier = Modifier.padding(top = 6.dp), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun TextButtonWithIcon(
    icon: @Composable () -> Unit,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    TextButton(onClick = onClick, modifier = modifier) {
        icon()
        Spacer(Modifier.width(7.dp))
        Text(label)
    }
}

private fun copyToClipboard(context: Context, text: String) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("Extracted text", text))
}

private fun shareText(context: Context, text: String) {
    if (text.isBlank()) return
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, text)
    }
    context.startActivity(Intent.createChooser(intent, "Share extracted text"))
}

private fun openAccessibilitySettings(context: Context) {
    runCatching { context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

private fun openNotificationSettings(context: Context) {
    val intent = if (Build.VERSION.SDK_INT >= 26) {
        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
    } else {
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).setData(android.net.Uri.parse("package:${context.packageName}"))
    }
    runCatching { context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}
