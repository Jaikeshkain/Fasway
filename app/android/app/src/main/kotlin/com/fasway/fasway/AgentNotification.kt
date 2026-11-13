package com.fasway.fasway

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build

/**
 * "The assistant needs your OK": the only way to hear about an approval while another app is on
 * screen. Tapping it opens Fasway; the answer is always given inside the app, on the full card.
 */
object AgentNotification {
    private const val CHANNEL = "agent_approval"
    private const val ID = 2

    fun show(context: Context, text: String) {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        if (Build.VERSION.SDK_INT >= 33 && !nm.areNotificationsEnabled()) return
        val b = if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, "Assistant approvals", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "The assistant needs your OK before a step on the laptop"
                })
            Notification.Builder(context, CHANNEL)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(context).setPriority(Notification.PRIORITY_HIGH)
        }
        val open = PendingIntent.getActivity(
            context, 2,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = b.setSmallIcon(R.mipmap.ic_launcher_foreground)
            .setContentTitle("Fasway needs your OK")
            .setContentText(text)
            .setContentIntent(open)
            .setAutoCancel(true)
            .setColor(0xFF4F8CFF.toInt())
            .build()
        nm.notify(ID, n)
    }

    fun hide(context: Context) {
        context.getSystemService(NotificationManager::class.java)?.cancel(ID)
    }
}
