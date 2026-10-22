package com.fasway.fasway

import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.view.WindowManager
import android.webkit.MimeTypeMap
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import kotlin.concurrent.thread

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // A remote control should not let the phone screen go dark while you use it.
        // (Only while Fasway is open; Android clears this when the app goes to the background.)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // Files received from the laptop: save to Downloads/Fasway and open them.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "fasway/files").setMethodCallHandler { call, result ->
            when (call.method) {
                "save" -> {
                    val path = call.argument<String>("path")!!
                    val name = call.argument<String>("name")!!
                    val main = Handler(Looper.getMainLooper())
                    thread {   // copying a large file must not freeze the app
                        try {
                            val saved = saveToDownloads(File(path), name)
                            main.post { result.success(saved) }
                        } catch (e: Exception) {
                            main.post { result.error("save", e.message ?: "$e", null) }
                        }
                    }
                }
                "open" -> result.success(open(call.argument<String>("uri")!!, call.argument<String>("name")!!))
                else -> result.notImplemented()
            }
        }
    }

    private fun mimeOf(name: String): String =
        MimeTypeMap.getSingleton().getMimeTypeFromExtension(name.substringAfterLast('.', "").lowercase())
            ?: "application/octet-stream"

    /** Returns a content:// uri (Android 10+) or a file path (older Android). */
    private fun saveToDownloads(src: File, name: String): String {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.MIME_TYPE, mimeOf(name))
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Fasway")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Couldn't create the file in Downloads")
            try {
                contentResolver.openOutputStream(uri)!!.use { out -> src.inputStream().use { it.copyTo(out) } }
            } catch (e: Exception) {
                contentResolver.delete(uri, null, null)
                throw e
            }
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            contentResolver.update(uri, values, null, null)
            return uri.toString()
        }
        // Android 7–9: the shared Downloads folder needs a storage permission; use the app's own
        // Downloads folder instead (Android/data/com.fasway.fasway/files/Download/Fasway)
        val dir = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "Fasway").apply { mkdirs() }
        val stem = name.substringBeforeLast('.')
        val ext = if (name.contains('.')) "." + name.substringAfterLast('.') else ""
        var dest = File(dir, name)
        var n = 2
        while (dest.exists()) dest = File(dir, "$stem ($n)$ext").also { n++ }
        src.copyTo(dest)
        return dest.path
    }

    private fun open(uri: String, name: String): Boolean {
        if (!uri.startsWith("content://")) return false
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(Uri.parse(uri), mimeOf(name))
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return try {
            startActivity(intent)
            true
        } catch (e: ActivityNotFoundException) {
            false
        }
    }
}
