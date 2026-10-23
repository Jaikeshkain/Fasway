package com.fasway.fasway

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build

/**
 * Quiet, ongoing "Fasway" notification with a "Send clipboard" button: Android lets apps read the
 * clipboard only while on screen, so after copying in any app you pull down the shade and tap the
 * button (an invisible screen reads the clipboard and sends it to the laptop).
 */
object ClipboardNotification {
    private const val CHANNEL = "clipboard"
    private const val ID = 1

    fun sendClipboardIntent(context: Context): PendingIntent {
        val i = Intent(context, CopyToLaptopActivity::class.java)
            .setAction(CopyToLaptopActivity.ACTION_SEND_CLIPBOARD)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION)
        return PendingIntent.getActivity(context, 1, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    fun show(context: Context, laptop: String) {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        if (Build.VERSION.SDK_INT >= 33 && !nm.areNotificationsEnabled()) return
        val b = if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, "Clipboard button", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "Send the phone clipboard to the laptop with one tap"
                    setShowBadge(false)
                })
            Notification.Builder(context, CHANNEL)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(context).setPriority(Notification.PRIORITY_LOW)
        }
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val send = sendClipboardIntent(context)
        @Suppress("DEPRECATION")
        val action = Notification.Action.Builder(R.mipmap.ic_launcher_foreground, "📋 Send clipboard", send).build()
        val n = b.setSmallIcon(R.mipmap.ic_launcher_foreground)
            .setContentTitle("Fasway · $laptop")
            .setContentText("Copied something? Tap Send clipboard to put it on the laptop.")
            .setContentIntent(open)
            .addAction(action)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setColor(0xFF4F8CFF.toInt())
            .build()
        nm.notify(ID, n)
    }

    fun hide(context: Context) {
        context.getSystemService(NotificationManager::class.java)?.cancel(ID)
    }
}
