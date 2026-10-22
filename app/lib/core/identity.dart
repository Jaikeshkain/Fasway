import 'dart:convert';
import 'dart:math';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// This phone's identity towards Fasway: a random id + secret key made once and kept in the
/// Android keystore-backed secure storage. The laptop stores only a hash of the key.
class Identity {
  final String id;
  final String key;
  final String name;

  Identity(this.id, this.key, this.name);

  static const _storage = FlutterSecureStorage();

  static String _random(int bytes) {
    final r = Random.secure();
    final b = List<int>.generate(bytes, (_) => r.nextInt(256));
    return base64Url.encode(b).replaceAll('=', '');
  }

  static Future<Identity> load() async {
    var id = await _storage.read(key: 'device_id');
    var key = await _storage.read(key: 'device_key');
    if (id == null || key == null) {
      id = _random(12);
      key = _random(32);
      await _storage.write(key: 'device_id', value: id);
      await _storage.write(key: 'device_key', value: key);
    }
    return Identity(id, key, await _deviceName());
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
