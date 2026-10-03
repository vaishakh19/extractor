package com.universaltextextractor.ocr

import android.graphics.Bitmap
import com.google.android.gms.tasks.Task
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.devanagari.DevanagariTextRecognizerOptions
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Bundled, offline recognizers. Add another OcrEngine implementation without changing capture or UI. */
class MlKitOcrEngine : OcrEngine {
    private val recognizers: List<TextRecognizer> = listOf(
        TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS),
        TextRecognition.getClient(DevanagariTextRecognizerOptions.Builder().build()),
    )

    override suspend fun extract(bitmap: Bitmap): String = withContext(Dispatchers.Default) {
        val processed = BitmapPreprocessor.prepare(bitmap)
        try {
            val image = InputImage.fromBitmap(processed, 0)
            val detectedLines = mutableListOf<OcrLine>()
            var recognizerSucceeded = false
            var firstFailure: Exception? = null

            recognizers.forEach { recognizer ->
                try {
                    val result = recognizer.process(image).awaitResult()
                    recognizerSucceeded = true
                    detectedLines += result.toOcrLines()
                } catch (error: Exception) {
                    if (firstFailure == null) firstFailure = error
                }
            }

            if (!recognizerSucceeded) throw firstFailure ?: IllegalStateException("OCR could not process this screen.")
            ReadingOrderFormatter.format(detectedLines)
        } finally {
            processed.recycle()
        }
    }

    override fun close() {
        recognizers.forEach { it.close() }
    }

    private fun Text.toOcrLines(): List<OcrLine> = textBlocks.flatMap { block ->
        block.lines.mapNotNull { line ->
            val rect = line.boundingBox ?: return@mapNotNull null
            OcrLine(line.text, rect.left, rect.top, rect.right, rect.bottom)
        }
    }

    private suspend fun <T> Task<T>.awaitResult(): T = suspendCancellableCoroutine { continuation ->
        addOnSuccessListener { value ->
            if (continuation.isActive) continuation.resume(value)
        }.addOnFailureListener { error ->
            if (continuation.isActive) continuation.resumeWithException(error)
        }
    }
}
