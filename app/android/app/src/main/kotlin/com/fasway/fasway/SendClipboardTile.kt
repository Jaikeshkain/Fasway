package com.fasway.fasway

import android.content.Intent
import android.os.Build
import android.service.quicksettings.TileService

/** Quick Settings tile "Send clipboard": one tap from the shade sends the phone clipboard to the laptop. */
class SendClipboardTile : TileService() {
    override fun onClick() {
        super.onClick()
        if (Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(ClipboardNotification.sendClipboardIntent(this))
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(
                Intent(this, CopyToLaptopActivity::class.java)
                    .setAction(CopyToLaptopActivity.ACTION_SEND_CLIPBOARD)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION))
        }
    }
}
