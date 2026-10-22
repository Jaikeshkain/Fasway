import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'connection.dart';
import 'discovery.dart';
import 'identity.dart';
import 'laptop.dart';
import 'settings.dart';

/// Everything the app shares: settings, this phone's identity, discovery and the paired laptop.
class AppState extends ChangeNotifier {
  AppState._(this.prefs, this.settings, this.identity);

  final SharedPreferences prefs;
  final Settings settings;
  final Identity identity;
  final Discovery discovery = Discovery();
  Laptop? laptop;
  Connection? connection;

  static Future<AppState> load() async {
    final prefs = await SharedPreferences.getInstance().timeout(const Duration(seconds: 8));
    final s = AppState._(prefs, Settings(prefs), await Identity.load(prefs));
    final saved = prefs.getString('laptop');
    if (saved != null) {
      try {
        s.laptop = Laptop.decode(saved);
      } catch (_) {}
    }
    // discovery runs in the background: never let it delay or break startup
    unawaited(s.discovery.start().catchError((Object e) => debugPrint('discovery: $e')));
    if (s.laptop != null) s._connect();
    return s;
  }

  void _connect() {
    connection?.dispose();
    connection = Connection(laptop!, identity, discovery, onLaptopChanged: _save)..connect();
  }

  void _save(Laptop l) => prefs.setString('laptop', l.encode());

  /// A QR code was scanned: pair with that laptop (replaces the previous one).
  void pair(Laptop l) {
    final old = laptop;
    if (old != null && old.id == l.id && l.fp.isEmpty) l.fp = old.fp; // keep the pinned certificate
    if (old != null && old.id == l.id) l.ips = {...l.ips, ...old.ips}.toList();
    laptop = l;
    _save(l);
    _connect();
    notifyListeners();
  }

  void forget() {
    connection?.dispose();
    connection = null;
    laptop = null;
    prefs.remove('laptop');
    notifyListeners();
  }
}
