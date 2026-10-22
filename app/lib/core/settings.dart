import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// User preferences (same defaults as the web app).
class Settings extends ChangeNotifier {
  Settings(this._p);
  final SharedPreferences _p;

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
    notifyListeners();
  }

  static const quality = {
    'low': (w: 854, fps: 20),
    'medium': (w: 1280, fps: 30),
    'high': (w: 1920, fps: 30),
  };
}
