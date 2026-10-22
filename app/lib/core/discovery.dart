import 'dart:async';

import 'package:bonsoir/bonsoir.dart';
import 'package:flutter/foundation.dart';

/// A Fasway laptop seen on the local network (mDNS service `_fasway._tcp`).
class FoundLaptop {
  final String id;
  final String name;
  final String ip;
  final int port;
  final DateTime seen;
  FoundLaptop(this.id, this.name, this.ip, this.port) : seen = DateTime.now();
}

/// Finds Fasway laptops on the Wi-Fi with Android's network service discovery. This is how the app
/// keeps working when the laptop's IP changes, without relying on `.local` name resolution.
class Discovery extends ChangeNotifier {
  final Map<String, FoundLaptop> found = {};
  BonsoirDiscovery? _d;
  StreamSubscription? _sub;

  Future<void> start() async {
    if (_d != null) return;
    try {
      final d = BonsoirDiscovery(type: '_fasway._tcp', printLogs: false);
      _d = d;
      await d.initialize();
      _sub = d.eventStream?.listen((event) {
        switch (event) {
          case BonsoirDiscoveryServiceFoundEvent():
            event.service.resolve(d.serviceResolver); // ask for its address + TXT record
          case BonsoirDiscoveryServiceResolvedEvent() || BonsoirDiscoveryServiceUpdatedEvent():
            final s = event.service;
            if (s != null) _add(s);
          case BonsoirDiscoveryServiceLostEvent():
            final s = event.service;
            found.removeWhere((_, f) => s.name.endsWith(f.name));
            notifyListeners();
          default:
        }
      });
      await d.start();
    } catch (e) {
      debugPrint('discovery unavailable: $e');
      _d = null;
    }
  }

  void _add(BonsoirService s) {
    final id = s.attributes['id'] ?? '';
    if (id.isEmpty) return;
    // prefer an IPv4 address: the laptop's server listens on IPv4
    final ip = s.hostAddresses.firstWhere((a) => RegExp(r'^\d+\.\d+\.\d+\.\d+$').hasMatch(a),
        orElse: () => s.hostAddresses.isNotEmpty ? s.hostAddresses.first : '');
    if (ip.isEmpty) return;
    final label = s.name.replaceFirst(RegExp(r'^Fasway on '), '');
    found[id] = FoundLaptop(id, label, ip, s.port);
    notifyListeners();
  }

  Future<void> stop() async {
    await _sub?.cancel();
    _sub = null;
    try {
      await _d?.stop();
    } catch (_) {}
    _d = null;
  }
}
