package com.universaltextextractor.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val LightColors = lightColorScheme(
    primary = Color(0xFF137C78),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD4F2EC),
    onPrimaryContainer = Color(0xFF073B39),
    secondary = Color(0xFF536B68),
    background = Color(0xFFF6F8F7),
    surface = Color(0xFFFFFFFF),
    surfaceVariant = Color(0xFFE8EFED),
    onSurface = Color(0xFF182523),
    onSurfaceVariant = Color(0xFF586663),
    error = Color(0xFFBA1A1A),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF73D4C8),
    onPrimary = Color(0xFF003733),
    primaryContainer = Color(0xFF075B55),
    onPrimaryContainer = Color(0xFFBDF4EA),
    secondary = Color(0xFFB3CCC7),
    background = Color(0xFF101816),
    surface = Color(0xFF18211F),
    surfaceVariant = Color(0xFF273330),
    onSurface = Color(0xFFE1E9E6),
    onSurfaceVariant = Color(0xFFB6C4C0),
    error = Color(0xFFFFB4AB),
)

@Composable
fun ExtractorTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) DarkColors else LightColors,
        content = content,
    )
}
