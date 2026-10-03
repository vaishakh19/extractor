package com.universaltextextractor.settings

import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import com.universaltextextractor.service.FloatingAccessibilityService

object SettingsStore {
    private const val PREFS = "extractor_preferences"
    private const val KEY_FLOATING_BUTTON = "floating_button_enabled"

    private fun preferences(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun isFloatingButtonEnabled(context: Context): Boolean =
        preferences(context).getBoolean(KEY_FLOATING_BUTTON, false)

    fun setFloatingButtonEnabled(context: Context, enabled: Boolean) {
        preferences(context).edit().putBoolean(KEY_FLOATING_BUTTON, enabled).apply()
    }

    fun isAccessibilityServiceEnabled(context: Context): Boolean {
        val expected = ComponentName(context, FloatingAccessibilityService::class.java).flattenToString()
        val enabled = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
        ) ?: return false
        return enabled.split(':').any { it.equals(expected, ignoreCase = true) }
    }
}
