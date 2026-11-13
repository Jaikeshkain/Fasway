package com.fasway.fasway

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import io.flutter.plugin.common.MethodChannel
import java.util.Locale

/**
 * Reads the assistant's replies aloud with the phone's own text-to-speech (free, works offline).
 * Tells Flutter when each reply has been spoken ("spoken" + its id), so a conversation can listen again.
 */
class Speaker(context: Context, private val channel: MethodChannel) : TextToSpeech.OnInitListener {
    private val app = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private var tts: TextToSpeech? = null
    private var ready = false
    private var pending: Triple<String, String, String>? = null

    fun speak(text: String, lang: String, id: String) {
        if (tts == null) {
            pending = Triple(text, lang, id)
            tts = TextToSpeech(app, this)   // the engine starts in the background; onInit says it's ready
            return
        }
        if (!ready) {
            pending?.let { done(it.third) }   // a newer reply replaces one still waiting for the engine
            pending = Triple(text, lang, id)
            return
        }
        say(text, lang, id)
    }

    override fun onInit(status: Int) {
        ready = status == TextToSpeech.SUCCESS
        val waiting = pending
        pending = null
        if (!ready) {
            waiting?.let { done(it.third) }   // no speech engine: don't leave Flutter waiting
            return
        }
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) { done(utteranceId) }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) { done(utteranceId) }
            override fun onError(utteranceId: String?, errorCode: Int) { done(utteranceId) }
            override fun onStop(utteranceId: String?, interrupted: Boolean) { done(utteranceId) }
        })
        waiting?.let { say(it.first, it.second, it.third) }
    }

    private fun say(text: String, lang: String, id: String) {
        val t = tts ?: return done(id)
        // Hindi when the reply is in Devanagari; Indian English otherwise (it reads Hinglish well)
        val wanted = if (lang == "hi") Locale("hi", "IN") else Locale("en", "IN")
        if (t.setLanguage(wanted) < TextToSpeech.LANG_AVAILABLE) t.setLanguage(Locale.US)
        if (t.speak(text, TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS) done(id)
    }

    private fun done(id: String?) {
        main.post { channel.invokeMethod("spoken", id) }
    }

    fun stop() {
        tts?.stop()
    }

    fun shutdown() {
        tts?.shutdown()
        tts = null
        ready = false
    }
}
