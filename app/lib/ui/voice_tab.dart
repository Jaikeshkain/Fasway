import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../core/connection.dart';
import '../core/settings.dart';
import 'common.dart';

/// Voice typing with Android's own speech recognizer (works in the background of the app, keeps
/// listening across pauses, Hindi / English / Hinglish).
class VoiceTab extends StatefulWidget {
  const VoiceTab({super.key, required this.conn, required this.settings});
  final Connection conn;
  final Settings settings;
  @override
  State<VoiceTab> createState() => _VoiceTabState();
}

class _VoiceTabState extends State<VoiceTab> {
  static const langs = {
    'mix-roman': ('Mixed – Hinglish (Roman letters)', 'en_IN'),
    'mix-deva': ('Mixed – हिंदी लिपि (Devanagari)', 'hi_IN'),
    'en': ('English', 'en_IN'),
    'hi': ('हिंदी (Hindi)', 'hi_IN'),
  };

  final _stt = SpeechToText();
  bool _ready = false, _listening = false;
  String _status = 'Off', _interim = '';
  final _sent = <String>[];
  final _text = TextEditingController();
  bool _review = false;

  Settings get s => widget.settings;

  @override
  void dispose() {
    _listening = false;
    _stt.cancel();
    _text.dispose();
    super.dispose();
  }

  Future<void> _toggle() async {
    haptic(s.haptics);
    if (_listening) {
      _listening = false;
      await _stt.stop();
      setState(() {
        _status = 'Off';
        _interim = '';
      });
      return;
    }
    if (!_ready) {
      _ready = await _stt.initialize(onStatus: _onStatus, onError: _onError);
      if (!_ready) {
        setState(() => _status = 'Speech recognition is not available (allow the microphone, or install Google app)');
        return;
      }
    }
    _listening = true;
    await _listen();
  }

  Future<void> _listen() async {
    if (!_listening || !mounted) return;
    setState(() => _status = 'Listening… tap to stop');
    await _stt.listen(
      onResult: _onResult,
      listenOptions: SpeechListenOptions(
        localeId: langs[s.lang]?.$2 ?? 'en_IN',
        listenMode: ListenMode.dictation,
        partialResults: true,
        cancelOnError: false,
        pauseFor: const Duration(seconds: 4),
        listenFor: const Duration(minutes: 1),
      ),
    );
  }

  void _onResult(SpeechRecognitionResult r) {
    if (!r.finalResult) {
      setState(() => _interim = r.recognizedWords);
      return;
    }
    final text = r.recognizedWords.trim();
    setState(() => _interim = '');
    if (text.isEmpty) return;
    if (_review) {
      _text.text = _text.text.isEmpty ? text : '${_text.text.trimRight()} $text';
    } else {
      widget.conn.send({'t': 'txt', 'v': '$text '});
    }
    setState(() {
      _sent.add(text);
      if (_sent.length > 30) _sent.removeAt(0);
    });
  }

  void _onStatus(String status) {
    // Android stops after a pause: start again while the mic is on (continuous dictation)
    if ((status == 'done' || status == 'notListening') && _listening) {
      Future.delayed(const Duration(milliseconds: 150), _listen);
    }
  }

  void _onError(SpeechRecognitionError e) {
    if (e.errorMsg.contains('permission')) {
      _listening = false;
      setState(() => _status = 'Microphone permission denied');
    }
    // "no match" / "speech timeout" just mean silence: onStatus restarts listening
  }

  Widget _keyRow() => Row(children: [
        for (final (l, k) in [('⌫', 'backspace'), ('⌫ word', 'ctrl+backspace'), ('Space', 'space'), ('Enter ⏎', 'enter'), ('Undo', 'mod+z')])
          KeyButton(
            label: l,
            fontSize: 13,
            repeat: k == 'backspace',
            onPress: () {
              haptic(s.haptics);
              widget.conn.send({'t': 'key', 'k': k});
            },
          ),
      ]);

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const SizedBox(height: 4),
          DropdownButtonFormField<String>(
            initialValue: langs.containsKey(s.lang) ? s.lang : 'mix-roman',
            decoration: InputDecoration(
              labelText: 'Language',
              filled: true,
              fillColor: C.panel2,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide.none),
            ),
            items: [for (final e in langs.entries) DropdownMenuItem(value: e.key, child: Text(e.value.$1))],
            onChanged: (v) async {
              await s.set('lang', v!);
              if (_listening) {
                await _stt.stop(); // restarts with the new language via onStatus
              }
            },
          ),
          const SizedBox(height: 10),
          Container(
            height: 170,
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: C.panel, borderRadius: BorderRadius.circular(16)),
            child: SingleChildScrollView(
              reverse: true,
              child: _sent.isEmpty && _interim.isEmpty
                  ? Text(_listening ? 'Listening… speak now' : 'Tap the mic and speak…',
                      style: const TextStyle(color: C.muted))
                  : Text.rich(TextSpan(children: [
                      TextSpan(text: '${_sent.join(' ')} ', style: const TextStyle(fontSize: 18)),
                      TextSpan(text: _interim, style: const TextStyle(fontSize: 18, color: C.muted)),
                    ])),
            ),
          ),
          const SizedBox(height: 14),
          Center(
            child: GestureDetector(
              onTap: _toggle,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                width: 96,
                height: 96,
                decoration: BoxDecoration(
                  color: _listening ? C.bad : C.panel2,
                  shape: BoxShape.circle,
                  boxShadow: _listening ? [BoxShadow(color: C.bad.withValues(alpha: 0.5), blurRadius: 22, spreadRadius: 4)] : null,
                ),
                child: const Icon(Icons.mic_rounded, size: 46),
              ),
            ),
          ),
          const SizedBox(height: 6),
          Text(_status, textAlign: TextAlign.center, style: const TextStyle(color: C.muted, fontSize: 13)),
          SwitchListTile(
            value: _review,
            onChanged: (v) => setState(() => _review = v),
            title: const Text('Review before sending', style: TextStyle(fontSize: 14, color: C.muted)),
            dense: true,
            contentPadding: EdgeInsets.zero,
          ),
          Row(children: [
            Expanded(
              child: TextField(
                controller: _text,
                minLines: 1,
                maxLines: 3,
                decoration: InputDecoration(
                  hintText: "Type here, or use your keyboard's mic…",
                  filled: true,
                  fillColor: C.panel,
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                ),
              ),
            ),
            const SizedBox(width: 8),
            FilledButton(
              onPressed: () {
                if (_text.text.trim().isNotEmpty && widget.conn.send({'t': 'txt', 'v': _text.text})) {
                  _text.clear();
                  haptic(s.haptics);
                }
              },
              child: const Text('Send'),
            ),
          ]),
          const SizedBox(height: 8),
          _keyRow(),
        ]),
      );
}
