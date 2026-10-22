package com.fasway.fasway

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager
import kotlin.concurrent.thread

/**
 * "Copy to laptop" in the text-selection menu of any app, and Fasway in the Share sheet for text.
 * Invisible: sends the text to the laptop clipboard, shows a toast and closes, without opening Fasway.
 * (Android doesn't let apps read the clipboard in the background, so this replaces copy + switch app.)
 */
class CopyToLaptopActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = when (intent?.action) {
            Intent.ACTION_PROCESS_TEXT -> intent.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT)
            Intent.ACTION_SEND -> intent.getCharSequenceExtra(Intent.EXTRA_TEXT)
            else -> null
        }?.toString().orEmpty()
        if (text.isEmpty()) {
            finish()
            return
        }
        val app = applicationContext
        thread {
            val msg = try {
                send(app, text)
                "📋 Copied to laptop"
            } catch (e: Exception) {
                e.message ?: "Couldn't reach the laptop"
            }
            runOnUiThread { Toast.makeText(app, msg, Toast.LENGTH_SHORT).show() }
        }
        finish() // the toast and the network call outlive the (invisible) activity
    }

    companion object {
        const val PREFS = "fasway_link"

        /** Saved by the app whenever it connects: how to reach and authenticate with the laptop. */
        fun saveLink(context: Context, link: Map<*, *>) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("hosts", JSONArray(link["hosts"] as List<*>).toString())
                .putInt("port", (link["port"] as Number).toInt())
                .putString("fp", link["fp"] as String)
                .putString("id", link["id"] as String)
                .putString("key", link["key"] as String)
                .apply()
        }

        fun clearLink(context: Context) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply()
        }

        private fun send(context: Context, text: String) {
            val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val fp = p.getString("fp", "").orEmpty()
            val hosts = JSONArray(p.getString("hosts", "[]"))
            if (fp.isEmpty() || hosts.length() == 0) throw Exception("Open Fasway and pair with your laptop first")
            val port = p.getInt("port", 8443)

            // trust exactly the paired laptop's certificate (same pinning as the app)
            val pinned = object : X509TrustManager {
                override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = throw CertificateException()
                override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                    val got = MessageDigest.getInstance("SHA-256").digest(chain[0].encoded).joinToString("") { "%02x".format(it) }
                    if (got != fp) throw CertificateException("not the paired laptop")
                }
                override fun getAcceptedIssuers() = arrayOf<X509Certificate>()
            }
            val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf(pinned), null) }
            val body = JSONObject().put("v", text).toString().toByteArray()

            var lastError = "Laptop not reachable – is Fasway running on it?"
            for (i in 0 until hosts.length()) {
                val c = URL("https://${hosts.getString(i)}:$port/clip").openConnection() as HttpsURLConnection
                try {
                    c.sslSocketFactory = ssl.socketFactory
                    c.setHostnameVerifier { _, _ -> true } // the pinned certificate is the check
                    c.connectTimeout = 2500
                    c.readTimeout = 5000
                    c.requestMethod = "POST"
                    c.doOutput = true
                    c.setRequestProperty("Content-Type", "application/json")
                    c.setRequestProperty("X-Fasway-Device", p.getString("id", ""))
                    c.setRequestProperty("X-Fasway-Key", p.getString("key", ""))
                    c.outputStream.use { it.write(body) }
                    when (c.responseCode) {
                        HttpURLConnection.HTTP_OK -> {
                            val ok = JSONObject(c.inputStream.bufferedReader().readText()).optBoolean("ok")
                            if (!ok) throw Exception("The laptop couldn't set its clipboard")
                            return
                        }
                        HttpURLConnection.HTTP_FORBIDDEN -> throw Exception("This phone isn't trusted by the laptop – pair again")
                        HttpURLConnection.HTTP_NOT_FOUND -> throw Exception("Update Fasway on the laptop")
                        else -> lastError = "Laptop answered ${c.responseCode}"
                    }
                } catch (e: java.io.IOException) {
                    lastError = "Laptop not reachable – is Fasway running on it?" // try the next address
                } finally {
                    c.disconnect()
                }
            }
            throw Exception(lastError)
        }
    }
}
