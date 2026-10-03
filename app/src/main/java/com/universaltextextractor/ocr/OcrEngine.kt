package com.universaltextextractor.ocr

import android.graphics.Bitmap

/** Replaceable boundary for a local or future OCR provider. */
interface OcrEngine : AutoCloseable {
    suspend fun extract(bitmap: Bitmap): String

    override fun close() = Unit
}
