package com.universaltextextractor.ocr

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SensitiveContentGuardTest {
    @Test
    fun blocksObviousCredentialAndVerificationForms() {
        assertTrue(SensitiveContentGuard.looksLikeAuthenticationScreen("Sign in\nEmail\nPassword"))
        assertTrue(SensitiveContentGuard.looksLikeAuthenticationScreen("Verification code"))
    }

    @Test
    fun doesNotBlockOrdinaryArticleTextAboutSecurity() {
        assertFalse(SensitiveContentGuard.looksLikeAuthenticationScreen("A password manager can help organize your accounts."))
    }
}
