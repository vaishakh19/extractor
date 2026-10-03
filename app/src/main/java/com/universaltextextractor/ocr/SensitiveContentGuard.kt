package com.universaltextextractor.ocr

/** Best-effort guard against turning obvious sign-in and verification forms into a text-copy tool. */
internal object SensitiveContentGuard {
    private val credentialLabel = Regex(
        "(?i)^\\s*(password|passcode|pin(?: code)?|otp|one[- ]time (password|code)|verification code|security code|cvv|card number)\\s*[:：._•*\\-]*\\s*$",
    )
    private val signInContext = Regex("(?i)\\b(sign[ -]?in|log[ -]?in|authenticate|verify your account|security check)\\b")
    private val credentialTerm = Regex(
        "(?i)\\b(password|passcode|pin(?: code)?|one[- ]time password|otp|verification code|security code|cvv|card number)\\b",
    )

    fun looksLikeAuthenticationScreen(text: String): Boolean {
        val lines = text.lineSequence().map(String::trim).filter(String::isNotEmpty).toList()
        if (lines.any(credentialLabel::matches)) return true
        return signInContext.containsMatchIn(text) && credentialTerm.containsMatchIn(text)
    }
}
