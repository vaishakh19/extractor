package com.universaltextextractor.ocr

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Paint
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/** Conservative, local preprocessing. The input bitmap remains owned by the caller. */
internal object BitmapPreprocessor {
    private const val MAX_DIMENSION = 2400

    fun prepare(source: Bitmap, threshold: Int? = null): Bitmap {
        var working = trimFlatOuterMargins(source)
        val longestSide = max(working.width, working.height)
        val scale = when {
            longestSide > MAX_DIMENSION -> MAX_DIMENSION.toFloat() / longestSide
            longestSide < 900 -> min(1.35f, 1200f / longestSide)
            else -> 1f
        }
        if (scale != 1f) {
            val scaled = Bitmap.createScaledBitmap(
                working,
                max(1, (working.width * scale).toInt()),
                max(1, (working.height * scale).toInt()),
                true,
            )
            if (working !== source && working !== scaled) working.recycle()
            working = scaled
        }

        val grayContrast = Bitmap.createBitmap(working.width, working.height, Bitmap.Config.ARGB_8888)
        val contrast = 1.12f
        val offset = -8f
        val matrix = ColorMatrix(
            floatArrayOf(
                0.299f * contrast, 0.587f * contrast, 0.114f * contrast, 0f, offset,
                0.299f * contrast, 0.587f * contrast, 0.114f * contrast, 0f, offset,
                0.299f * contrast, 0.587f * contrast, 0.114f * contrast, 0f, offset,
                0f, 0f, 0f, 1f, 0f,
            ),
        )
        val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG).apply {
            colorFilter = ColorMatrixColorFilter(matrix)
        }
        Canvas(grayContrast).drawBitmap(working, 0f, 0f, paint)
        if (working !== source) working.recycle()

        return if (threshold == null) grayContrast else threshold(grayContrast, threshold).also {
            grayContrast.recycle()
        }
    }

    /** Optional hard threshold; left off by default to preserve antialiased glyph detail. */
    private fun threshold(source: Bitmap, threshold: Int): Bitmap {
        val output = Bitmap.createBitmap(source.width, source.height, Bitmap.Config.ARGB_8888)
        val row = IntArray(source.width)
        val cut = threshold.coerceIn(0, 255)
        for (y in 0 until source.height) {
            source.getPixels(row, 0, source.width, 0, y, source.width, 1)
            for (x in row.indices) {
                val pixel = row[x]
                val luminance = (Color.red(pixel) * 299 + Color.green(pixel) * 587 + Color.blue(pixel) * 114) / 1000
                val value = if (luminance >= cut) 255 else 0
                row[x] = Color.rgb(value, value, value)
            }
            output.setPixels(row, 0, source.width, 0, y, source.width, 1)
        }
        return output
    }

    /** Trim only tiny, completely flat outer borders; text or icons at an edge stop the crop. */
    private fun trimFlatOuterMargins(source: Bitmap): Bitmap {
        val maxX = min(source.width / 30, 64)
        val maxY = min(source.height / 30, 64)
        if (maxX <= 0 || maxY <= 0) return source

        var top = 0
        var bottom = source.height
        var left = 0
        var right = source.width
        while (top < maxY && isFlatLine(source, horizontal = true, position = top, start = left, end = right)) top++
        while (bottom - 1 > top && source.height - bottom < maxY &&
            isFlatLine(source, horizontal = true, position = bottom - 1, start = left, end = right)
        ) bottom--
        while (left < maxX && isFlatLine(source, horizontal = false, position = left, start = top, end = bottom)) left++
        while (right - 1 > left && source.width - right < maxX &&
            isFlatLine(source, horizontal = false, position = right - 1, start = top, end = bottom)
        ) right--

        val cropWidth = right - left
        val cropHeight = bottom - top
        if (left == 0 && top == 0 && right == source.width && bottom == source.height) return source
        if (cropWidth < source.width * 0.85f || cropHeight < source.height * 0.85f) return source
        return Bitmap.createBitmap(source, left, top, cropWidth, cropHeight)
    }

    private fun isFlatLine(bitmap: Bitmap, horizontal: Boolean, position: Int, start: Int, end: Int): Boolean {
        val length = end - start
        if (length < 2) return false
        val sampleCount = min(length, 160)
        var outliers = 0
        var reference = 0
        for (i in 0 until sampleCount) {
            val along = start + (i * (length - 1) / max(1, sampleCount - 1))
            val color = if (horizontal) bitmap.getPixel(along, position) else bitmap.getPixel(position, along)
            if (i == sampleCount / 2) reference = color
            else if (colorDistance(color, reference) > 18) outliers++
        }
        return outliers <= max(1, sampleCount / 100)
    }

    private fun colorDistance(first: Int, second: Int): Int = max(
        max(abs(Color.red(first) - Color.red(second)), abs(Color.green(first) - Color.green(second))),
        abs(Color.blue(first) - Color.blue(second)),
    )
}
