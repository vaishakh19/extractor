package com.universaltextextractor.service

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.widget.TextView
import com.universaltextextractor.CapturePermissionActivity
import com.universaltextextractor.settings.SettingsStore
import kotlin.math.abs
import kotlin.math.max

/** Optional drag handle only. It deliberately never reads AccessibilityNodeInfo or screen text. */
class FloatingAccessibilityService : AccessibilityService() {
    private var floatingView: View? = null
    private val windowManager by lazy { getSystemService(Context.WINDOW_SERVICE) as WindowManager }
    private val preferences by lazy { getSharedPreferences("extractor_preferences", Context.MODE_PRIVATE) }
    private val preferenceListener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == "floating_button_enabled") updateOverlay()
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        preferences.registerOnSharedPreferenceChangeListener(preferenceListener)
        updateOverlay()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Intentionally empty: the service exists only to host the opt-in floating trigger.
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        preferences.unregisterOnSharedPreferenceChangeListener(preferenceListener)
        removeOverlay()
        super.onDestroy()
    }

    private fun updateOverlay() {
        if (SettingsStore.isFloatingButtonEnabled(this)) showOverlay() else removeOverlay()
    }

    private fun showOverlay() {
        if (floatingView != null) return
        val density = resources.displayMetrics.density
        val size = (52 * density).toInt()
        val margin = (12 * density).toInt()
        val button = TextView(this).apply {
            text = "T"
            textSize = 18f
            gravity = Gravity.CENTER
            setTextColor(0xFFFFFFFF.toInt())
            contentDescription = "Extract visible text"
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(0xFF137C78.toInt())
                setStroke((1.5f * density).toInt(), 0xFFFFFFFF.toInt())
            }
            elevation = 8 * density
            setOnClickListener {
                try {
                    startActivity(
                        Intent(this@FloatingAccessibilityService, CapturePermissionActivity::class.java)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    )
                } catch (_: RuntimeException) {
                    // The user can always launch capture from Quick Settings or the app.
                }
            }
        }
        val params = WindowManager.LayoutParams(
            size,
            size,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = max(margin, resources.displayMetrics.widthPixels - size - margin)
            y = resources.displayMetrics.heightPixels / 3
        }
        installDragHandler(button, params)
        try {
            windowManager.addView(button, params)
            floatingView = button
        } catch (_: RuntimeException) {
            floatingView = null
        }
    }

    private fun installDragHandler(view: View, params: WindowManager.LayoutParams) {
        val touchSlop = ViewConfiguration.get(this).scaledTouchSlop
        var downX = 0f
        var downY = 0f
        var initialX = 0
        var initialY = 0
        var dragged = false
        view.setOnTouchListener { target, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX
                    downY = event.rawY
                    initialX = params.x
                    initialY = params.y
                    dragged = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - downX).toInt()
                    val dy = (event.rawY - downY).toInt()
                    if (abs(dx) > touchSlop || abs(dy) > touchSlop) dragged = true
                    if (dragged) {
                        params.x = (initialX + dx).coerceIn(0, max(0, resources.displayMetrics.widthPixels - target.width))
                        params.y = (initialY + dy).coerceIn(0, max(0, resources.displayMetrics.heightPixels - target.height))
                        try {
                            windowManager.updateViewLayout(target, params)
                        } catch (_: RuntimeException) {
                            removeOverlay()
                        }
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!dragged) target.performClick()
                    true
                }
                MotionEvent.ACTION_CANCEL -> true
                else -> false
            }
        }
    }

    private fun removeOverlay() {
        val existing = floatingView ?: return
        try {
            windowManager.removeView(existing)
        } catch (_: RuntimeException) {
            // Already detached while the service was being stopped.
        }
        floatingView = null
    }
}
