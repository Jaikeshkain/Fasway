import 'dart:async';

import 'package:flutter/services.dart';

/// Reads text aloud with the phone's own text-to-speech (see Speaker.kt). [say] finishes when the
/// phone has finished speaking, so a conversation knows when to listen again.
class Speaker {
  Speaker() {
    _ch.setMethodCallHandler((call) async {
      if (call.method == 'spoken' && '${call.arguments}' == '$_id') _finish();
    });
  }

  static const _ch = MethodChannel('fasway/speech');
  static final _devanagari = RegExp(r'[ऀ-ॿ]');
  int _id = 0;
  Completer<void>? _done;

  /// Text as it should be heard: symbols the voice would spell out or skip, made into words.
  static String spoken(String text) => text
      .replaceAllMapped(RegExp(r'(\d)\s*%'), (m) => '${m[1]} percent')
      .replaceAll(RegExp(r'[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]', unicode: true), '')
      .replaceAll(RegExp(r'[*_#`>]'), '')
      .trim();

  Future<void> say(String text) async {
    stop();
    final words = spoken(text);
    if (words.isEmpty) return;
    final id = ++_id;
    final done = _done = Completer<void>();
    try {
      await _ch.invokeMethod('speak', {'text': words, 'lang': _devanagari.hasMatch(words) ? 'hi' : 'en', 'id': '$id'});
    } catch (_) {
      _finish(); // no speech on this phone: carry on silently
    }
    // never wait forever if the engine doesn't report back (about 6 words a second, plus start-up)
    await done.future.timeout(Duration(seconds: 6 + words.length ~/ 10), onTimeout: () {});
  }

  void _finish() {
    final d = _done;
    _done = null;
    if (d != null && !d.isCompleted) d.complete();
  }

  void stop() {
    if (_done == null) return;
    _finish();
    _ch.invokeMethod('stop').catchError((Object _) => null);
  }

  void dispose() {
    stop();
    _ch.setMethodCallHandler(null);
  }
}
