package com.universaltextextractor.capture

import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.DisplayMetrics
import android.view.WindowManager
import androidx.core.app.ServiceCompat
import com.universaltextextractor.data.HistoryRepository
import com.universaltextextractor.ocr.MlKitOcrEngine
import com.universaltextextractor.ocr.SensitiveContentGuard
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean
import android.content.pm.ServiceInfo
import android.graphics.Rect
import android.os.Looper

/** Captures exactly one Android-approved display frame, performs local OCR, and discards the bitmap. */
class CaptureService : Service() {
    private val frameAcquired = AtomicBoolean(false)
    private val finished = AtomicBoolean(false)
    private var started = false
    private var projection: MediaProjection? = null
    private var reader: ImageReader? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var captureThread: HandlerThread? = null
    private var captureHandler: Handler? = null

    private val exceptionHandler = CoroutineExceptionHandler { _, _ ->
        reportFailure("Text extraction failed. Please try again.")
    }
    private val workScope = CoroutineScope(SupervisorJob() + Dispatchers.IO + exceptionHandler)

    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            if (!frameAcquired.get()) reportFailure("Screen capture was stopped before a frame was received.")
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        try {
            val foregroundType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            } else {
                0
            }
            ServiceCompat.startForeground(
                this,
                NotificationHelper.FOREGROUND_ID,
                NotificationHelper.foreground(this),
                foregroundType,
            )
        } catch (_: RuntimeException) {
            reportFailure("Android couldn't start screen capture. Please try again.")
            return START_NOT_STICKY
        }

        if (started) return START_NOT_STICKY
        started = true
        val resultCode = intent?.getIntExtra(CaptureIntents.EXTRA_RESULT_CODE, 0) ?: 0
        val resultData = intent?.parcelableIntent(CaptureIntents.EXTRA_RESULT_DATA)
        if (resultCode == 0 || resultData == null) {
            reportFailure("Screen capture permission was not received.")
            return START_NOT_STICKY
        }

        beginCapture(resultCode, resultData)
        return START_NOT_STICKY
    }

    private fun beginCapture(resultCode: Int, resultData: Intent) {
        try {
            val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            val activeProjection = manager.getMediaProjection(resultCode, resultData)
            projection = activeProjection

            val (width, height) = displaySize()
            if (width <= 0 || height <= 0) {
                reportFailure("The current screen size couldn't be read.")
                return
            }

            captureThread = HandlerThread("text-extractor-capture").also { it.start() }
            captureHandler = Handler(captureThread!!.looper)
            activeProjection.registerCallback(projectionCallback, captureHandler)
            reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
            reader?.setOnImageAvailableListener(::onImageAvailable, captureHandler)

            // Let the consent activity close and the original app become visible before mirroring.
            captureHandler?.postDelayed({
                if (!finished.get()) {
                    try {
                        virtualDisplay = activeProjection.createVirtualDisplay(
                            "Universal Text Extractor",
                            width,
                            height,
                            resources.displayMetrics.densityDpi,
                            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                            reader?.surface,
                            null,
                            captureHandler,
                        )
                    } catch (_: RuntimeException) {
                        reportFailure("Android couldn't capture this screen. Protected content may be unavailable.")
                    }
                }
            }, 450L)
            captureHandler?.postDelayed({
                if (!frameAcquired.get()) reportFailure("No screen frame arrived. Please try again.")
            }, 12_000L)
        } catch (_: SecurityException) {
            reportFailure("Android denied screen capture. Protected screens cannot be read.")
        } catch (_: RuntimeException) {
            reportFailure("Screen capture isn't available right now. Please try again.")
        }
    }

    private fun onImageAvailable(imageReader: ImageReader) {
        val image = try {
            imageReader.acquireLatestImage()
        } catch (_: RuntimeException) {
            null
        } ?: return

        if (!frameAcquired.compareAndSet(false, true)) {
            image.close()
            return
        }
        captureHandler?.removeCallbacksAndMessages(null)

        val bitmap = try {
            image.toBitmap()
        } catch (_: RuntimeException) {
            null
        } finally {
            image.close()
        }

        releaseCaptureResources(stopProjection = true)
        if (bitmap == null) {
            reportFailure("The screen image couldn't be read. Please try again.")
            return
        }

        workScope.launch {
            try {
                val engine = MlKitOcrEngine()
                val resultText = try {
                    engine.extract(bitmap)
                } finally {
                    engine.close()
                }
                if (resultText.isBlank()) {
                    reportFailure("No readable text was found. Try a clearer or zoomed view.")
                    return@launch
                }
                if (SensitiveContentGuard.looksLikeAuthenticationScreen(resultText)) {
                    reportFailure("For privacy, text from sign-in or verification screens isn't extracted.")
                    return@launch
                }

                val historyId = try {
                    HistoryRepository.get(this@CaptureService).save(resultText)
                } catch (_: Exception) {
                    null
                }
                sendTextReady(resultText, historyId)
                if (historyId != null && historyId > 0) {
                    NotificationHelper.postReady(this@CaptureService, historyId)
                } else {
                    NotificationHelper.postStatus(this@CaptureService, "Text was extracted, but history couldn't be saved.")
                }
                finishService()
            } catch (_: Exception) {
                reportFailure("Text extraction failed. Please try again.")
            } finally {
                bitmap.recycle()
            }
        }
    }

    private fun sendTextReady(text: String, historyId: Long?) {
        val result = Intent(CaptureIntents.ACTION_TEXT_READY)
            .setPackage(packageName)
            .putExtra(CaptureIntents.EXTRA_TEXT, text)
        if (historyId != null && historyId > 0) result.putExtra(CaptureIntents.EXTRA_HISTORY_ID, historyId)
        sendBroadcast(result)
    }

    private fun reportFailure(message: String) {
        if (!finished.compareAndSet(false, true)) return
        releaseCaptureResources(stopProjection = true)
        sendBroadcast(
            Intent(CaptureIntents.ACTION_CAPTURE_STATUS)
                .setPackage(packageName)
                .putExtra(CaptureIntents.EXTRA_STATUS_MESSAGE, message),
        )
        NotificationHelper.postStatus(this, message)
        stopServiceNow()
    }

    private fun finishService() {
        if (!finished.compareAndSet(false, true)) return
        releaseCaptureResources(stopProjection = true)
        stopServiceNow()
    }

    private fun stopServiceNow() {
        Handler(Looper.getMainLooper()).post {
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun releaseCaptureResources(stopProjection: Boolean) {
        val activeReader = reader
        reader = null
        try {
            activeReader?.setOnImageAvailableListener(null, null)
            activeReader?.close()
        } catch (_: RuntimeException) {
            // Cleanup is best-effort if Android has already stopped the projection.
        }
        try {
            virtualDisplay?.release()
        } catch (_: RuntimeException) {
            // Already released by the platform.
        }
        virtualDisplay = null
        val activeProjection = projection
        projection = null
        if (activeProjection != null) {
            try {
                activeProjection.unregisterCallback(projectionCallback)
            } catch (_: RuntimeException) {
                // Callback may already have been removed by Android.
            }
            if (stopProjection) {
                try {
                    activeProjection.stop()
                } catch (_: RuntimeException) {
                    // Projection may already be stopped.
                }
            }
        }
        captureThread?.quitSafely()
        captureThread = null
        captureHandler = null
    }

    private fun displaySize(): Pair<Int, Int> {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val bounds: Rect = (getSystemService(Context.WINDOW_SERVICE) as WindowManager).maximumWindowMetrics.bounds
            bounds.width() to bounds.height()
        } else {
            @Suppress("DEPRECATION")
            val display = (getSystemService(Context.WINDOW_SERVICE) as WindowManager).defaultDisplay
            val metrics = DisplayMetrics()
            @Suppress("DEPRECATION")
            display.getRealMetrics(metrics)
            metrics.widthPixels to metrics.heightPixels
        }
    }

    override fun onDestroy() {
        releaseCaptureResources(stopProjection = true)
        workScope.cancel()
        super.onDestroy()
    }

    private fun Image.toBitmap(): Bitmap {
        val plane = planes.firstOrNull() ?: throw IllegalStateException("Screen image has no pixel plane")
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        val paddedWidth = rowStride / pixelStride
        val padded = Bitmap.createBitmap(paddedWidth, height, Bitmap.Config.ARGB_8888)
        padded.copyPixelsFromBuffer(plane.buffer)
        if (paddedWidth == width) return padded
        val cropped = Bitmap.createBitmap(padded, 0, 0, width, height)
        padded.recycle()
        return cropped
    }

    private fun Intent.parcelableIntent(key: String): Intent? = if (Build.VERSION.SDK_INT >= 33) {
        getParcelableExtra(key, Intent::class.java)
    } else {
        @Suppress("DEPRECATION")
        getParcelableExtra(key)
    }
}
