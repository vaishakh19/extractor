package com.universaltextextractor.ocr

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

internal data class OcrLine(
    val text: String,
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
) {
    val width: Int get() = right - left
    val height: Int get() = bottom - top
}

/** Merges script recognizers, removes duplicate detections, and approximates top-to-bottom reading order. */
internal object ReadingOrderFormatter {
    fun format(input: List<OcrLine>): String {
        val lines = deduplicate(input.filter { it.text.isNotBlank() })
            .sortedWith(compareBy<OcrLine> { it.top }.thenBy { it.left })
        if (lines.isEmpty()) return ""

        val rows = mutableListOf<MutableList<OcrLine>>()
        for (line in lines) {
            val row = rows.lastOrNull()?.takeIf { current -> sameVisualRow(current, line) }
            if (row == null) rows += mutableListOf(line) else row += line
        }

        val output = StringBuilder()
        var previousBottom = -1
        var previousHeight = 0
        rows.forEach { row ->
            val orderedRow = row.sortedBy { it.left }
            val top = orderedRow.minOf { it.top }
            val bottom = orderedRow.maxOf { it.bottom }
            val height = orderedRow.map { max(1, it.height) }.sorted()[orderedRow.size / 2]

            if (output.isNotEmpty()) {
                val gap = top - previousBottom
                val paragraphGap = gap > max(12, max(previousHeight, height) * 0.85f).toInt()
                output.append(if (paragraphGap) "\n\n" else "\n")
            }

            orderedRow.forEachIndexed { index, line ->
                if (index > 0) output.append("   ")
                output.append(cleanLine(line.text))
            }
            previousBottom = bottom
            previousHeight = height
        }

        return output.toString()
            .replace(Regex("[ \\t]+([,.;:!?])"), "\$1")
            .replace(Regex("[ \\t]{2,}"), " ")
            .trim()
    }

    private fun sameVisualRow(row: List<OcrLine>, candidate: OcrLine): Boolean {
        val top = row.minOf { it.top }
        val bottom = row.maxOf { it.bottom }
        val rowCenter = (top + bottom) / 2f
        val candidateCenter = (candidate.top + candidate.bottom) / 2f
        val rowHeight = max(1, bottom - top)
        val candidateHeight = max(1, candidate.height)
        return abs(rowCenter - candidateCenter) <= max(rowHeight, candidateHeight) * 0.52f
    }

    private fun deduplicate(lines: List<OcrLine>): List<OcrLine> {
        val accepted = mutableListOf<OcrLine>()
        for (line in lines) {
            val normalized = normalize(line.text)
            if (normalized.isEmpty()) continue
            val duplicateIndex = accepted.indexOfFirst { existing ->
                val other = normalize(existing.text)
                val overlap = intersectionOverUnion(line, existing)
                overlap > 0.42f && (
                    normalized == other ||
                        (overlap > 0.72f && (normalized.contains(other) || other.contains(normalized)))
                    )
            }
            if (duplicateIndex < 0) {
                accepted += line
            } else if (line.text.length > accepted[duplicateIndex].text.length) {
                accepted[duplicateIndex] = line
            }
        }
        return accepted
    }

    private fun intersectionOverUnion(first: OcrLine, second: OcrLine): Float {
        val left = max(first.left, second.left)
        val top = max(first.top, second.top)
        val right = min(first.right, second.right)
        val bottom = min(first.bottom, second.bottom)
        val intersection = max(0, right - left) * max(0, bottom - top)
        val union = first.width * first.height + second.width * second.height - intersection
        return if (union <= 0) 0f else intersection.toFloat() / union
    }

    private fun normalize(text: String): String = text
        .lowercase()
        .filter(Char::isLetterOrDigit)

    private fun cleanLine(text: String): String = text
        .replace('\u00a0', ' ')
        .replace(Regex("[ \\t]+"), " ")
        .trim()
}
