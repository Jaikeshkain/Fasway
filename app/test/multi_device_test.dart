// Several paired laptops: the saved list, switching, forgetting and the laptop switcher.
// The live group needs two Fasway test servers and their certificate fingerprints:
//   flutter test test/multi_device_test.dart --dart-define=FASWAY_TEST_FP_A=<sha256> --dart-define=FASWAY_TEST_PORT_A=<port>
//     --dart-define=FASWAY_TEST_FP_B=<sha256> --dart-define=FASWAY_TEST_PORT_B=<port>
// (skipped when they are not set)
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:fasway/core/app_state.dart';
import 'package:fasway/core/connection.dart';
import 'package:fasway/core/laptop.dart';
import 'package:fasway/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

const fpA = String.fromEnvironment('FASWAY_TEST_FP_A');
const fpB = String.fromEnvironment('FASWAY_TEST_FP_B');
const portA = int.fromEnvironment('FASWAY_TEST_PORT_A');
const portB = int.fromEnvironment('FASWAY_TEST_PORT_B');

// port 1 just refuses: these tests never reach a laptop
Laptop unreachable(String id, {String? name}) => Laptop(id: id, host: '127.0.0.1', port: 1, token: 't', fp: 'ab' * 32, name: name);

Future<AppState> start(Map<String, Object> saved) async {
  SharedPreferences.setMockInitialValues({'flutter.identity_in_prefs': true, ...saved});
  return AppState.load();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => HttpOverrides.global = null); // real sockets

  group('saved laptops', () {
    test('a laptop saved by an older version is kept, with the key it is trusted with', () async {
      final s = await start({'flutter.laptop': unreachable('old', name: 'Old one').encode()});
      expect(s.laptops.map((l) => l.id), ['old']);
      expect(s.laptop!.id, 'old');
      expect(s.laptop!.key, isEmpty);
      expect(s.connection!.authHeaders['X-Fasway-Key'], s.identity.key);
      expect(s.prefs.getString('laptop'), isNull);
      s.connection!.dispose();
      final again = await AppState.load();
      expect(again.laptops.map((l) => l.name), ['Old one']);
      again.connection!.dispose();
    });

    test('adding keeps the others and switches; each new laptop gets its own key', () async {
      final s = await start({});
      expect(s.laptop, isNull);
      s.pair(unreachable('a'));
      final first = s.connection!;
      s.pair(unreachable('b'));
      expect(s.laptops.map((l) => l.id), ['a', 'b']);
      expect(s.laptop!.id, 'b');
      expect(s.connection, isNot(first));
      final keys = {s.laptops[0].key, s.laptops[1].key, s.identity.key};
      expect(keys.length, 3);
      expect(s.laptops[1].key.length, greaterThanOrEqualTo(20)); // the laptop refuses shorter ones
      s.connection!.dispose();

      final again = await AppState.load();
      expect(again.laptop!.id, 'b'); // the laptop in use is still current after a restart
      expect(again.laptops.length, 2);
      again.connection!.dispose();
    });

    test('scanning a known laptop again updates it instead of adding it', () async {
      final s = await start({});
      s.pair(unreachable('a'));
      s.laptop!.ips = ['10.0.0.9'];
      s.rename(s.laptop!, 'Office');
      final key = s.laptop!.key;
      s.pair(Laptop(id: 'a', host: '127.0.0.1', port: 1, token: 'new', ips: ['10.0.0.1']));
      expect(s.laptops.length, 1);
      expect(s.laptop!.token, 'new');
      expect(s.laptop!.key, key);
      expect(s.laptop!.name, 'Office');
      expect(s.laptop!.renamed, isTrue);
      expect(s.laptop!.fp, 'ab' * 32);
      expect(s.laptop!.ips, ['10.0.0.1', '10.0.0.9']);
      s.connection!.dispose();
    });

    test('switching replaces the connection; the old one stays down', () async {
      final s = await start({});
      s.pair(unreachable('a'));
      s.pair(unreachable('b'));
      final old = s.connection!;
      s.switchTo(s.laptops.first);
      expect(s.laptop!.id, 'a');
      expect(s.connection!.laptop.id, 'a');
      expect(old.state, LinkState.offline);
      await old.connect(); // e.g. a tap on the fading old screen
      expect(old.state, LinkState.offline);
      final same = s.connection;
      s.switchTo(s.laptops.first); // already current: nothing happens
      expect(s.connection, same);
      s.connection!.dispose();
    });

    test('forgetting moves on to the next laptop; the last one leaves none', () async {
      final s = await start({});
      s.pair(unreachable('a'));
      s.pair(unreachable('b'));
      s.pair(unreachable('c')); // current
      s.forget(s.laptops[1]); // not current: nothing else changes
      expect(s.laptops.map((l) => l.id), ['a', 'c']);
      expect(s.laptop!.id, 'c');
      s.forget(s.laptop!);
      expect(s.laptop!.id, 'a');
      expect(s.connection!.laptop.id, 'a');
      s.forget(s.laptop!);
      expect(s.laptops, isEmpty);
      expect(s.laptop, isNull);
      expect(s.connection, isNull);
      expect(jsonDecode(s.prefs.getString('laptops')!), isEmpty);
      expect(s.prefs.getString('activeLaptop'), isNull);
    });
  });

  testWidgets('the switcher lists laptops, switches, renames and forgets', (tester) async {
    final saved = [unreachable('a', name: 'Home PC'), unreachable('b', name: 'Office Mac')];
    SharedPreferences.setMockInitialValues({'flutter.laptops': jsonEncode(saved), 'flutter.identity_in_prefs': true});
    await tester.binding.setSurfaceSize(const Size(400, 860));
    await tester.pumpWidget(const FaswayApp());
    for (var i = 0; i < 30 && find.text('Touchpad').evaluate().isEmpty; i++) {
      await tester.runAsync(() => Future.delayed(const Duration(milliseconds: 100)));
      await tester.pump(const Duration(milliseconds: 100));
    }
    Future<void> settle() async {
      for (var i = 0; i < 12; i++) {
        await tester.pump(const Duration(milliseconds: 80));
      }
    }

    await tester.tap(find.text('Keyboard'));
    await settle();

    // the title names the current laptop and opens the list
    expect(find.text('Home PC'), findsOneWidget);
    await tester.tap(find.text('Home PC'));
    await settle();
    expect(find.text('Office Mac'), findsOneWidget);
    expect(find.text('Add a laptop'), findsOneWidget);

    // switch: the old screen goes, the title changes, the open tab stays
    await tester.tap(find.text('Office Mac'));
    await settle();
    expect(tester.takeException(), isNull);
    expect(find.text('Office Mac'), findsOneWidget);
    expect(find.text('Home PC'), findsNothing);
    final nav = tester.widget<NavigationBar>(find.byType(NavigationBar).first);
    expect(nav.selectedIndex, 1);

    // rename
    await tester.tap(find.text('Office Mac'));
    await settle();
    await tester.tap(find.byTooltip('Options for Office Mac'));
    await settle();
    await tester.tap(find.text('Rename'));
    await settle();
    await tester.enterText(find.byType(TextField).last, 'Work laptop');
    await tester.tap(find.text('Save'));
    await settle();
    expect(find.text('Work laptop'), findsWidgets);

    // forget the current laptop: back to the other one
    await tester.tap(find.byTooltip('Options for Work laptop'));
    await settle();
    await tester.tap(find.text('Forget'));
    await settle();
    await tester.tap(find.widgetWithText(FilledButton, 'Forget'));
    await settle();
    expect(tester.takeException(), isNull);
    expect(find.text('Home PC'), findsOneWidget);
    expect(find.text('Work laptop'), findsNothing);

    // forget the last one: the first-run screen
    await tester.tap(find.text('Home PC'));
    await settle();
    await tester.tap(find.byTooltip('Options for Home PC'));
    await settle();
    await tester.tap(find.text('Forget'));
    await settle();
    await tester.tap(find.widgetWithText(FilledButton, 'Forget'));
    await settle();
    expect(tester.takeException(), isNull);
    expect(find.text('Scan QR code'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 2));
  });

  group('live servers', skip: fpA.isEmpty || fpB.isEmpty ? 'set FASWAY_TEST_FP_A / _B and the ports' : null, () {
    Laptop live(String id, int port, String fp) => Laptop(id: id, host: '127.0.0.1', port: port, token: 'apptok', fp: fp);

    Future<void> connected(AppState s) async {
      final end = DateTime.now().add(const Duration(seconds: 10));
      while (s.connection?.isConnected != true && DateTime.now().isBefore(end)) {
        await Future.delayed(const Duration(milliseconds: 50));
      }
      expect(s.connection!.state, LinkState.connected, reason: '${s.connection!.lastError}');
    }

    test('pairs with both, switches between them, and each knows only its own key', () async {
      final s = await start({});
      s.pair(live('lapa', portA, fpA));
      await connected(s);
      expect(s.laptop!.name, 'Test laptop'); // from the server's hello
      s.pair(live('lapb', portB, fpB));
      await connected(s);
      expect(s.connection!.laptop.id, 'lapb');

      // back and forth without asking again: both trust this phone now
      for (final i in [0, 1, 0]) {
        s.switchTo(s.laptops[i]);
        await connected(s);
        expect(s.connection!.address, '127.0.0.1');
        final pong = s.connection!.messages.firstWhere((m) => m['t'] == 'pong').timeout(const Duration(seconds: 5));
        s.connection!.send({'t': 'ping', 'id': 7});
        expect((await pong)['id'], 7);
      }

      // what laptop A saw of this phone does not log in to laptop B
      final a = s.laptops[0], b = s.laptops[1];
      final stolen = Connection(
        Laptop(id: b.id, host: b.host, port: b.port, token: 'WRONG', fp: b.fp, key: a.key),
        s.identity,
        s.discovery,
        onLaptopChanged: (_) {},
      );
      final end = DateTime.now().add(const Duration(seconds: 10));
      unawaited(stolen.connect());
      while (stolen.state != LinkState.removed && DateTime.now().isBefore(end)) {
        await Future.delayed(const Duration(milliseconds: 50));
      }
      expect(stolen.state, LinkState.removed);
      stolen.dispose();
      s.connection!.dispose();
    }, timeout: const Timeout(Duration(seconds: 60)));
  });
}
