import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'connection.dart';
import 'discovery.dart';
import 'identity.dart';
import 'laptop.dart';
import 'settings.dart';

/// Everything the app shares: settings, this phone's identity, discovery and the paired laptops.
class AppState extends ChangeNotifier {
  AppState._(this.prefs, this.settings, this.identity);

  final SharedPreferences prefs;
  final Settings settings;
  final Identity identity;
  final Discovery discovery = Discovery();
  final List<Laptop> laptops = [];
  Laptop? laptop; // the one being controlled; only this one is connected
  Connection? connection;
  int tab = 0; // the open tab stays open when switching laptops

  static Future<AppState> load() async {
    final prefs = await SharedPreferences.getInstance().timeout(const Duration(seconds: 8));
    final s = AppState._(prefs, Settings(prefs), await Identity.load(prefs));
    s._loadLaptops();
    // discovery runs in the background: never let it delay or break startup
    unawaited(s.discovery.start().catchError((Object e) => debugPrint('discovery: $e')));
    if (s.laptop != null) s._connect();
    return s;
  }

  void _loadLaptops() {
    final saved = prefs.getString('laptops');
    final single = prefs.getString('laptop'); // saved by versions that kept one laptop
    try {
      if (saved != null) {
        laptops.addAll((jsonDecode(saved) as List).map((j) => Laptop.fromJson(j as Map<String, dynamic>)));
      } else if (single != null) {
        laptops.add(Laptop.decode(single));
      }
    } catch (_) {}
    if (laptops.isEmpty) return;
    final active = prefs.getString('activeLaptop');
    laptop = laptops.firstWhere((l) => l.id == active, orElse: () => laptops.first);
    if (saved == null) _save();
  }

  void _connect() {
    if (connection != null) Connection.clipNotification(false, ''); // back once the new laptop is connected
    connection?.close();
    connection = Connection(laptop!, identity, discovery, onLaptopChanged: _laptopChanged)
      ..saveNativeLink()
      ..connect();
  }

  void _save() {
    prefs.setString('laptops', jsonEncode(laptops));
    final l = laptop;
    if (l != null) {
      prefs.setString('activeLaptop', l.id);
    } else {
      prefs.remove('activeLaptop');
    }
    prefs.remove('laptop');
  }

  void _laptopChanged(Laptop _) {
    _save();
    notifyListeners();
  }

  /// A QR code was scanned: add that laptop and switch to it. Scanning a known laptop updates it.
  void pair(Laptop l) {
    final i = laptops.indexWhere((o) => o.id == l.id);
    if (i >= 0) {
      final old = laptops[i];
      if (l.fp.isEmpty) l.fp = old.fp; // keep the pinned certificate
      l.ips = {...l.ips, ...old.ips}.toList();
      l
        ..key = old.key
        ..name = old.name
        ..renamed = old.renamed;
      laptops[i] = l;
    } else {
      l.key = Identity.newKey();
      l.name = discovery.found[l.id]?.name ?? l.name;
      laptops.add(l);
    }
    laptop = l;
    _save();
    _connect();
    notifyListeners();
  }

  /// Control this laptop instead of the current one.
  void switchTo(Laptop l) {
    if (l.id == laptop?.id) return;
    laptop = l;
    _save();
    _connect();
    notifyListeners();
  }

  void rename(Laptop l, String name) {
    l
      ..name = name
      ..renamed = true;
    _laptopChanged(l);
  }

  /// Removes a laptop. Forgetting the current one moves on to the next, if there is one.
  void forget(Laptop l) {
    laptops.removeWhere((o) => o.id == l.id);
    if (l.id == laptop?.id) {
      if (laptops.isEmpty) {
        connection?.close();
        connection = null;
        laptop = null;
        Connection.clearNativeLink(); // "Copy to laptop" stops sending there
      } else {
        laptop = laptops.first;
        _connect();
      }
    }
    _save();
    notifyListeners();
  }
}
