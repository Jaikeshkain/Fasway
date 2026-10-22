// Integration test of the app's connection layer against a real Fasway server.
// Start the test server first and pass its certificate fingerprint:
//   flutter test test/connection_test.dart --dart-define=FASWAY_TEST_FP=<sha256 hex>
// (skipped when FASWAY_TEST_FP is not set)
import 'dart:async';

import 'package:fasway/core/connection.dart';
import 'package:fasway/core/discovery.dart';
import 'package:fasway/core/identity.dart';
import 'package:fasway/core/laptop.dart';
import 'package:flutter_test/flutter_test.dart';

const fp = String.fromEnvironment('FASWAY_TEST_FP');
const port = 18470;

Future<void> waitFor(Connection c, bool Function() cond, {int seconds = 10}) async {
  final end = DateTime.now().add(Duration(seconds: seconds));
  while (!cond() && DateTime.now().isBefore(end)) {
    await Future.delayed(const Duration(milliseconds: 50));
  }
}

Connection make({String token = 'apptok', String fingerprint = fp, String devId = 'phoneTEST0001', String host = '127.0.0.1'}) =>
    Connection(
      Laptop(id: 'apptest', host: host, port: port, token: token, fp: fingerprint),
      Identity(devId, 'secret-key-for-$devId-0123456789', 'Test phone · Fasway app'),
      Discovery(),
      onLaptopChanged: (_) {},
    );

void main() {
  test('QR parsing: new format with id + fingerprint', () {
    final l = Laptop.fromQr('https://fasway-abc12.local:8443/#t=TOK&id=abc12&fp=ABCDEF')!;
    expect(l.host, 'fasway-abc12.local');
    expect(l.port, 8443);
    expect(l.token, 'TOK');
    expect(l.id, 'abc12');
    expect(l.fp, 'abcdef');
  });

  test('QR parsing: old format (token only) and non-Fasway codes', () {
    final l = Laptop.fromQr('https://192.168.20.109:8443/#t=TOK')!;
    expect(l.ips, ['192.168.20.109']);
    expect(l.fp, '');
    expect(Laptop.fromQr('https://example.com/'), isNull);
    expect(Laptop.fromQr('hello'), isNull);
  });

  group('live server', skip: fp.isEmpty ? 'set FASWAY_TEST_FP' : null, () {
    test('pins the certificate, pairs, and talks', () async {
      final c = make();
      final pong = c.messages.firstWhere((m) => m['t'] == 'pong').timeout(const Duration(seconds: 10));
      unawaited(c.connect());
      await waitFor(c, () => c.isConnected);
      expect(c.state, LinkState.connected);
      expect(c.address, '127.0.0.1');
      c.send({'t': 'ping', 'id': 7});
      expect((await pong)['id'], 7);
      c.dispose();
    });

    test('trusted phone logs in with its key even with a wrong pairing code', () async {
      final c = make(token: 'WRONG'); // same device id/key as the paired phone above
      unawaited(c.connect());
      await waitFor(c, () => c.isConnected);
      expect(c.state, LinkState.connected);
      c.dispose();
    });

    test('a different certificate is refused (impostor)', () async {
      final c = make(fingerprint: '0' * 64, devId: 'phoneTEST0002');
      unawaited(c.connect());
      await waitFor(c, () => c.state == LinkState.wrongLaptop, seconds: 15);
      expect(c.state, LinkState.wrongLaptop);
      c.dispose();
    });

    test('unknown phone with a wrong pairing code is rejected', () async {
      final c = make(token: 'WRONG', devId: 'phoneSTRANGER');
      unawaited(c.connect());
      await waitFor(c, () => c.state == LinkState.removed, seconds: 15);
      expect(c.state, LinkState.removed);
      c.dispose();
    });
  });
}
