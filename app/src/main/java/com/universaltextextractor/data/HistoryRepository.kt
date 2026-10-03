package com.universaltextextractor.data

import android.content.Context
import kotlinx.coroutines.flow.Flow

class HistoryRepository private constructor(context: Context) {
    private val dao = HistoryDatabase.get(context.applicationContext).historyDao()

    fun observeSearch(query: String): Flow<List<HistoryEntry>> = dao.observeSearch(query.trim())

    suspend fun getById(id: Long): HistoryEntry? = dao.getById(id)

    suspend fun save(text: String, existingId: Long? = null): Long {
        val cleaned = text.trim()
        if (cleaned.isEmpty()) return existingId ?: 0L
        val now = System.currentTimeMillis()
        val title = titleFrom(cleaned)
        if (existingId != null) {
            val current = dao.getById(existingId)
            if (current != null) {
                dao.update(current.copy(createdAt = now, title = title, text = cleaned))
                dao.pruneOldEntries()
                return existingId
            }
        }
        val id = dao.insert(HistoryEntry(createdAt = now, title = title, text = cleaned))
        dao.pruneOldEntries()
        return id
    }

    suspend fun delete(id: Long) = dao.deleteById(id)

    suspend fun clear() = dao.deleteAll()

    companion object {
        @Volatile
        private var instance: HistoryRepository? = null

        fun get(context: Context): HistoryRepository = instance ?: synchronized(this) {
            instance ?: HistoryRepository(context.applicationContext).also { instance = it }
        }

        fun titleFrom(text: String): String {
            val words = text.trim().split(Regex("\\s+")).filter(String::isNotBlank).take(8)
            val title = words.joinToString(" ")
            return when {
                title.isBlank() -> "Extracted text"
                title.length > 58 -> title.take(55).trimEnd() + "…"
                text.trim().split(Regex("\\s+")).size > words.size -> title + "…"
                else -> title
            }
        }
    }
}
