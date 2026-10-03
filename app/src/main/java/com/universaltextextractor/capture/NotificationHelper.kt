package com.universaltextextractor.capture

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.universaltextextractor.CapturePermissionActivity
import com.universaltextextractor.MainActivity
import com.universaltextextractor.R

internal object NotificationHelper {
    const val FOREGROUND_ID = 4101
    private const val RESULT_ID = 4102
    private const val CAPTURE_CHANNEL = "capture_status"
    private const val RESULT_CHANNEL = "text_results"

    fun ensureChannels(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel(
                CAPTURE_CHANNEL,
                "Screen capture",
                NotificationManager.IMPORTANCE_LOW,
            ).apply { description = "Shows while the approved screen frame is processed on device." },
        )
        manager.createNotificationChannel(
            NotificationChannel(
                RESULT_CHANNEL,
                "Extraction results",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply { description = "Lets you review extracted text or start another capture." },
        )
    }

    fun foreground(context: Context): Notification {
        ensureChannels(context)
        return NotificationCompat.Builder(context, CAPTURE_CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Extracting visible text")
            .setContentText("Processing one screen frame on this device")
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    fun postReady(context: Context, historyId: Long) {
        ensureChannels(context)
        val review = reviewIntent(context, historyId)
        val retry = PendingIntent.getActivity(
            context,
            4104,
            Intent(context, CapturePermissionActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, RESULT_CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Text is ready")
            .setContentText("Tap to review your on-device extraction.")
            .setContentIntent(review)
            .setAutoCancel(true)
            .setTimeoutAfter(2 * 60 * 60 * 1000L)
            .addAction(R.drawable.ic_notification, "Review", review)
            .addAction(R.drawable.ic_notification, "Extract again", retry)
            .build()
        runCatching { NotificationManagerCompat.from(context).notify(RESULT_ID, notification) }
    }

    fun postStatus(context: Context, message: String) {
        ensureChannels(context)
        val open = PendingIntent.getActivity(
            context,
            4105,
            Intent(context, MainActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP,
            ),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, RESULT_CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Universal Text Extractor")
            .setContentText(message)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        runCatching { NotificationManagerCompat.from(context).notify(RESULT_ID, notification) }
    }

    private fun reviewIntent(context: Context, historyId: Long): PendingIntent = PendingIntent.getActivity(
        context,
        4103,
        Intent(context, MainActivity::class.java).apply {
            action = CaptureIntents.ACTION_OPEN_TEXT
            putExtra(CaptureIntents.EXTRA_HISTORY_ID, historyId)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        },
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
}
