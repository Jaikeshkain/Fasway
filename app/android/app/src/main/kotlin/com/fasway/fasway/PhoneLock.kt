package com.fasway.fasway

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal

/**
 * "Confirm it's you" with the phone's own lock: fingerprint, face or the screen-lock PIN / pattern.
 * Used before risky laptop actions (restart, shut down, commands, AI approvals), so someone holding
 * an unlocked phone can't do them. A phone without a screen lock has nothing to check: allowed.
 */
object PhoneLock {
    const val REQUEST = 41
    private var pending: ((Boolean) -> Unit)? = null

    fun confirm(activity: Activity, reason: String, done: (Boolean) -> Unit) {
        val keyguard = activity.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        if (!keyguard.isDeviceSecure) return done(true)
        var answered = false
        val once = { ok: Boolean -> if (!answered) { answered = true; done(ok) } }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            val builder = BiometricPrompt.Builder(activity)
                .setTitle("Confirm it's you")
                .setSubtitle(reason)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                builder.setAllowedAuthenticators(
                    BiometricManager.Authenticators.BIOMETRIC_WEAK or BiometricManager.Authenticators.DEVICE_CREDENTIAL)
            } else {
                @Suppress("DEPRECATION")
                builder.setDeviceCredentialAllowed(true)
            }
            builder.build().authenticate(CancellationSignal(), activity.mainExecutor,
                object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult?) = once(true)
                    override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) = once(false)
                })
        } else {
            // Android 7-8: the system's "confirm your PIN / pattern" screen
            @Suppress("DEPRECATION")
            val intent = keyguard.createConfirmDeviceCredentialIntent("Confirm it's you", reason)
                ?: return once(true)
            pending = once
            activity.startActivityForResult(intent, REQUEST)
        }
    }

    /** From MainActivity.onActivityResult (Android 7-8 only). */
    fun onResult(ok: Boolean) {
        pending?.invoke(ok)
        pending = null
    }
}
