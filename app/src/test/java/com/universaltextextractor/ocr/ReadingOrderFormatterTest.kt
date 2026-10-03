package com.universaltextextractor.ocr

import org.junit.Assert.assertEquals
import org.junit.Test

class ReadingOrderFormatterTest {
    @Test
    fun ordersRowsAndKeepsParagraphBreaks() {
        val result = ReadingOrderFormatter.format(
            listOf(
                OcrLine("Right", 180, 0, 260, 20),
                OcrLine("Heading", 0, 1, 100, 21),
                OcrLine("First paragraph.", 0, 48, 150, 68),
                OcrLine("Second line", 0, 73, 120, 93),
            ),
        )

        assertEquals("Heading Right\n\nFirst paragraph.\nSecond line", result)
    }

    @Test
    fun dropsDuplicateOverlappingRecognizerLines() {
        val result = ReadingOrderFormatter.format(
            listOf(
                OcrLine("नमस्ते", 10, 10, 100, 30),
                OcrLine("नमस्ते", 11, 10, 101, 30),
            ),
        )

        assertEquals("नमस्ते", result)
    }

    @Test
    fun removesSpaceBeforePunctuation() {
        assertEquals("Hello, world!", ReadingOrderFormatter.format(listOf(OcrLine("Hello , world !", 0, 0, 180, 20))))
    }
}
