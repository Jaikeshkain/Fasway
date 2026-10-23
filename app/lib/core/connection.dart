import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'discovery.dart';
import 'identity.dart';
import 'laptop.dart';

enum LinkState { offline, connecting, waitingApproval, connected, declined, removed, wrongLaptop }

/// One live connection to the paired laptop (same WebSocket protocol as the web app).
///
/// * Trusts exactly the laptop's certificate (SHA-256 pinned from the QR code).
/// * Tries the address found by mDNS discovery first, then the last working IPs, then the QR host.
/// * Handles pairing approval, removal, a keep-alive watchdog and automatic reconnects.
class Connection extends ChangeNotifier {
  Connection(this.laptop, this.identity, this.discovery, {required this.onLaptopChanged}) {
    discovery.addListener(_onDiscovery);
  }

  final Laptop laptop;
  final Identity identity;
  final Discovery discovery;
  final void Function(Laptop) onLaptopChanged; // persist learned fingerprint / IPs

  LinkState state = LinkState.offline;
  String laptopOs = 'win';
  String? lastError;
  String? address; // the address currently connected to

  final _messages = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get messages => _messages.stream;

  WebSocket? _ws;
  Timer? _retryTimer, _watchdog;
  int _retry = 0;
  DateTime _lastSeen = DateTime.now();
  bool _stopped = false;

  bool get isConnected => state == LinkState.connected;

  void _set(LinkState s) {
    if (state == s) return;
    state = s;
    notifyListeners();
  }

  void _onDiscovery() {
    // the laptop just showed up on the network: don't wait for the next retry
    if (!isConnected && state != LinkState.connecting && discovery.found.containsKey(laptop.id) &&
        state != LinkState.declined && state != LinkState.removed) {
      reconnectNow();
    }
  }

  List<String> _candidates() {
    final list = <String>[];
    final f = discovery.found[laptop.id];
    if (f != null) list.add(f.ip);
    list.addAll(laptop.ips);
    list.add(laptop.host);
    return list.toSet().toList();
  }

  bool _checkCert(X509Certificate cert) {
    final fp = sha256.convert(cert.der).toString();
    if (laptop.fp.isEmpty) {
      laptop.fp = fp; // older QR without fingerprint: trust on first use, then pin
      onLaptopChanged(laptop);
      return true;
    }
    return fp == laptop.fp;
  }

  Future<void> connect() async {
    _stopped = false;
    if (state == LinkState.connecting) return;
    _retryTimer?.cancel();
    _set(LinkState.connecting);
    final q = Uri(queryParameters: {'t': laptop.token, 'd': identity.id, 'k': identity.key, 'n': identity.name}).query;
    var wrongCert = false;
    for (final addr in _candidates()) {
      if (_stopped) return;
      final client = HttpClient()
        ..connectionTimeout = const Duration(seconds: 4)
        ..badCertificateCallback = (cert, host, port) => _checkCert(cert);
      try {
        final ws = await WebSocket.connect('wss://$addr:${laptop.port}/ws?$q', customClient: client)
            .timeout(const Duration(seconds: 6));
        _attach(ws, addr);
        return;
      } on WebSocketException catch (e) {
        // reached the laptop but it refused the upgrade (HTTP 403): pairing code no longer valid
        // and this phone isn't trusted (removed, or a new pairing code was made)
        lastError = '$addr: $e';
        if ('$e'.contains('not upgraded')) {
          _set(LinkState.removed);
          return;
        }
      } on HandshakeException catch (e) {
        // something answered, but with a different certificate: not our laptop (keep looking)
        lastError = 'certificate does not match ($addr): $e';
        wrongCert = true;
      } catch (e) {
        lastError = '$addr: $e';
      }
    }
    _set(wrongCert ? LinkState.wrongLaptop : LinkState.offline);
    _scheduleRetry();
  }

  void _attach(WebSocket ws, String addr) {
    _resetQuality();
    _ws = ws;
    address = addr;
    _retry = 0;
    _lastSeen = DateTime.now();
    ws.pingInterval = const Duration(seconds: 10);
    if (!laptop.ips.contains(addr) && RegExp(r'^\d+\.\d+\.\d+\.\d+$').hasMatch(addr)) {
      laptop.ips = [addr, ...laptop.ips.where((a) => a != addr)].take(4).toList();
      onLaptopChanged(laptop);
    }
    ws.listen(
      (data) {
        _lastSeen = DateTime.now();
        if (data is! String) return;
        final Map<String, dynamic> m;
        try {
          m = jsonDecode(data) as Map<String, dynamic>;
        } catch (_) {
          return;
        }
        switch (m['t']) {
          case 'pong':
            final id = m['id'];
            if (id is int && _pending.remove(id)) {
              _addSample(DateTime.now().millisecondsSinceEpoch - id);
            }
          case 'pair_wait':
            _set(LinkState.waitingApproval);
          case 'hello':
            laptopOs = (m['os'] ?? 'win') as String;
            _set(LinkState.connected);
            _saveNativeLink();
        }
        _messages.add(m);
      },
      onDone: () => _onClosed(ws),
      onError: (_) => _onClosed(ws),
      cancelOnError: true,
    );
    _watchdog?.cancel();
    _watchdog = Timer.periodic(const Duration(seconds: 3), (_) {
      if (_ws != ws) return;
      if (DateTime.now().difference(_lastSeen) > const Duration(seconds: 9)) {
        ws.close(); // silently dead (Wi-Fi switch, laptop asleep): reconnect
        return;
      }
      // a ping still unanswered after 3 s counts as lost
      for (var i = 0; i < _pending.length; i++) {
        _addSample(_lost);
      }
      _pending.clear();
      final id = DateTime.now().millisecondsSinceEpoch;
      if (send({'t': 'ping', 'id': id})) _pending.add(id);
    });
  }

  // ---------- link quality (phone <-> laptop over the local Wi-Fi) ----------
  /// Weak Wi-Fi between phone and laptop: slow answers or lost pings. The UI asks to move closer to
  /// the router; the laptop is told too.
  bool weak = false;
  int? rttMs; // typical round trip of the last pings
  static const _lost = 3000;
  final _pending = <int>{};
  final _samples = <int>[];

  void _addSample(int ms) {
    _samples.add(ms);
    if (_samples.length > 5) _samples.removeAt(0);
    if (_samples.length < 3) return;
    final sorted = [..._samples]..sort();
    final median = sorted[sorted.length ~/ 2];
    final lost = _samples.where((s) => s >= _lost).length;
    rttMs = median;
    // turn weak quickly, back to good only when clearly fine (no flicker on the edge)
    final nowWeak = weak ? !(median < 150 && lost == 0) : (median > 300 || lost >= 2);
    if (nowWeak != weak) {
      weak = nowWeak;
      send({'t': 'link', 'weak': weak, 'rtt': median});
      notifyListeners();
    }
  }

  void _resetQuality() {
    _pending.clear();
    _samples.clear();
    rttMs = null;
    weak = false;
  }

  void _onClosed(WebSocket ws) {
    if (_ws != ws) return;
    _ws = null;
    _watchdog?.cancel();
    _resetQuality();
    final code = ws.closeCode;
    if (code == 4003) {
      _set(LinkState.declined);
    } else if (code == 4004) {
      _set(LinkState.removed);
    } else {
      _set(LinkState.offline);
      _scheduleRetry();
    }
  }

  void _scheduleRetry() {
    if (_stopped) return;
    _retryTimer?.cancel();
    final delay = Duration(milliseconds: (300 * (1 << _retry.clamp(0, 4))).clamp(300, 4000));
    _retry++;
    _retryTimer = Timer(delay, connect);
  }

  void reconnectNow() {
    _retry = 0;
    final old = _ws;
    _ws = null;
    old?.close();
    state = LinkState.offline;
    connect();
  }

  /// Sends a message; returns false when not connected.
  bool send(Map<String, dynamic> m) {
    final ws = _ws;
    if (ws == null || ws.readyState != WebSocket.open) return false;
    if (state != LinkState.connected && m['t'] != 'ping') return false;
    ws.add(jsonEncode(m));
    return true;
  }

  static const _link = MethodChannel('fasway/link');

  /// Tells the Android side how to reach this laptop, for "Copy to laptop" in other apps' text menu
  /// (which runs without the Flutter app). The address that works now goes first.
  void _saveNativeLink() {
    if (laptop.fp.isEmpty) return; // only ever talk to a pinned certificate
    final hosts = {?address, ..._candidates()}.toList();
    _link.invokeMethod('save', {
      'hosts': hosts,
      'port': laptop.port,
      'fp': laptop.fp,
      'id': identity.id,
      'key': identity.key,
    }).catchError((Object _) => null); // tests / non-Android: no native side
  }

  static void clearNativeLink() => _link.invokeMethod('clear').catchError((Object _) => null);

  /// The ongoing "Send clipboard" notification (Android only lets apps read the clipboard while on
  /// screen, so this is the one-tap way to send what was copied in another app).
  static void clipNotification(bool show, String laptop) =>
      _link.invokeMethod(show ? 'notify' : 'unnotify', {'laptop': laptop}).catchError((Object _) => null);

  /// HTTPS to the connected laptop (file transfers): same pinned certificate as the websocket.
  HttpClient httpClient() => HttpClient()
    ..connectionTimeout = const Duration(seconds: 6)
    ..badCertificateCallback = (cert, host, port) => _checkCert(cert);

  /// URL on the connected laptop, or null while not connected.
  Uri? httpUri(String path, [Map<String, String>? query]) {
    final a = address;
    if (a == null || !isConnected) return null;
    return Uri(scheme: 'https', host: a, port: laptop.port, path: path, queryParameters: query);
  }

  /// Proves to the laptop that a request comes from this trusted phone.
  Map<String, String> get authHeaders => {'X-Fasway-Device': identity.id, 'X-Fasway-Key': identity.key};

  void disconnect() {
    _stopped = true;
    _retryTimer?.cancel();
    _watchdog?.cancel();
    _ws?.close();
    _ws = null;
    _set(LinkState.offline);
  }

  @override
  void dispose() {
    discovery.removeListener(_onDiscovery);
    disconnect();
    _messages.close();
    super.dispose();
  }
}
