import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// This phone's identity towards Fasway: a random id + secret key made once. The laptop stores only
/// a hash of the key.
///
/// Kept in Android's keystore-backed secure storage. Some phones' keystores fail or hang (seen on
/// Android 10), which must never block the app from starting: then the key lives in the app's
/// private storage instead (still only readable by this app).
class Identity {
  final String id;
  final String key;
  final String name;

  Identity(this.id, this.key, this.name);

  static const _secure = FlutterSecureStorage();
  static const _timeout = Duration(seconds: 4);

  static String _random(int bytes) {
    final r = Random.secure();
    final b = List<int>.generate(bytes, (_) => r.nextInt(256));
    return base64Url.encode(b).replaceAll('=', '');
  }

  static Future<Identity> load(SharedPreferences prefs) async {
    String? id, key;
    var secureOk = prefs.getBool('identity_in_prefs') != true;
    if (secureOk) {
      try {
        id = await _secure.read(key: 'device_id').timeout(_timeout);
        key = await _secure.read(key: 'device_key').timeout(_timeout);
        if (id == null || key == null) {
          id = _random(12);
          key = _random(32);
          await _secure.write(key: 'device_id', value: id).timeout(_timeout);
          await _secure.write(key: 'device_key', value: key).timeout(_timeout);
        }
      } catch (e) {
        debugPrint('secure storage unavailable, using app storage: $e');
        secureOk = false;
      }
    }
    if (!secureOk) {
      await prefs.setBool('identity_in_prefs', true);
      id = prefs.getString('device_id');
      key = prefs.getString('device_key');
      if (id == null || key == null) {
        id = _random(12);
        key = _random(32);
        await prefs.setString('device_id', id);
        await prefs.setString('device_key', key);
      }
    }
    return Identity(id!, key!, await _deviceName().timeout(_timeout, onTimeout: () => 'Android phone · Fasway app'));
  }

  /// e.g. "Pixel 8 · Fasway app"
  static Future<String> _deviceName() async {
    try {
      final a = await DeviceInfoPlugin().androidInfo;
      final brand = a.brand.isEmpty ? '' : '${a.brand[0].toUpperCase()}${a.brand.substring(1)} ';
      final model = a.model.toLowerCase().startsWith(a.brand.toLowerCase()) ? a.model : '$brand${a.model}';
      return '$model · Fasway app';
    } catch (_) {
      return 'Android phone · Fasway app';
    }
  }
}
