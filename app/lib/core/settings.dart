import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'phone_lock.dart';

/// User preferences (same defaults as the web app).
class Settings extends ChangeNotifier {
  Settings(this._p) {
    PhoneLock.enabled = phoneLock;
  }
  final SharedPreferences _p;

  /// Fingerprint / screen lock before risky laptop actions (see PhoneLock).
  bool get phoneLock => _p.getBool('phoneLock') ?? true;

  double get speed => _p.getDouble('speed') ?? 1.6;
  double get accel => _p.getDouble('accel') ?? 1.2;
  double get scrollSpeed => _p.getDouble('scrollSpeed') ?? 2.0;
  bool get natural => _p.getBool('natural') ?? true;
  bool get haptics => _p.getBool('haptics') ?? true;
  bool get screenOn => _p.getBool('screenOn') ?? false;
  bool get screenLarge => _p.getBool('screenLarge') ?? false;
  String get screenQuality => _p.getString('screenQuality') ?? 'medium';
  String get screenMode => _p.getString('screenMode') ?? 'trackpad'; // trackpad | direct | view
  String get lang => _p.getString('lang') ?? 'mix-roman';
  bool get clipAuto => _p.getBool('clipAuto') ?? true;
  bool get clipNotify => _p.getBool('clipNotify') ?? true; // "Send clipboard" notification
  bool get speakReplies => _p.getBool('speakReplies') ?? true; // the assistant answers voice requests aloud
  bool get padOpen => _p.getBool('padOpen') ?? false; // the small touchpad under the laptop screen view
  // where the floating assistant bubble rests: which side, and how far down (0 top .. 1 bottom)
  bool get fabLeft => _p.getBool('fabLeft') ?? false;
  String get whatsNewSeen => _p.getString('whatsNewSeen') ?? ''; // the version whose "What's new" was shown
  double get fabY => _p.getDouble('fabY') ?? 0.55;

  Future<void> set(String key, Object value) async {
    switch (value) {
      case double v:
        await _p.setDouble(key, v);
      case bool v:
        await _p.setBool(key, v);
      case String v:
        await _p.setString(key, v);
      case int v:
        await _p.setInt(key, v);
    }
    if (key == 'phoneLock') PhoneLock.enabled = value as bool;
    notifyListeners();
  }

  static const quality = {
    'low': (w: 854, fps: 20),
    'medium': (w: 1280, fps: 30),
    'high': (w: 1920, fps: 30),
  };
}
