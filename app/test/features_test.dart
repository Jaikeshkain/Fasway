// Wake-on-LAN packets, the presentation remote and routines, with a connection that only records.
import 'package:fasway/core/connection.dart';
import 'package:fasway/core/discovery.dart';
import 'package:fasway/core/identity.dart';
import 'package:fasway/core/laptop.dart';
import 'package:fasway/core/settings.dart';
import 'package:fasway/core/wake.dart';
import 'package:fasway/ui/presentation_screen.dart';
import 'package:fasway/ui/routines_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class RecordingConnection extends Connection {
  RecordingConnection(Laptop l)
      : super(l, Identity('phoneTEST0001', 'k' * 32, 'Test phone'), Discovery(), onLaptopChanged: (_) {});
  final sent = <Map<String, dynamic>>[];
  @override
  bool send(Map<String, dynamic> m) {
    sent.add(m);
    return true;
  }

  List<String> get keys => [for (final m in sent) if (m['t'] == 'key') '${m['k']}'];
}

Laptop laptop() => Laptop(id: 'x', host: '127.0.0.1', port: 1, token: 't');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  group('Wake-on-LAN', () {
    test('magic packet: 6 × FF, then the card address 16 times', () {
      final p = Wake.magicPacket('AA-bb:01:02:03:FF')!;
      expect(p.length, 102);
      expect(p.sublist(0, 6), List.filled(6, 0xFF));
      for (var i = 0; i < 16; i++) {
        expect(p.sublist(6 + i * 6, 12 + i * 6), [0xAA, 0xBB, 0x01, 0x02, 0x03, 0xFF]);
      }
    });

    test('no card address yet: nothing to send', () async {
      expect(Wake.magicPacket(''), isNull);
      expect(Wake.magicPacket('zz:zz'), isNull);
      expect(await Wake.send(laptop()), isFalse);
    });

    test('the card address is remembered with the laptop', () {
      final l = laptop()
        ..mac = 'aa:bb:cc:dd:ee:ff'
        ..bcast = '192.168.1.255';
      final back = Laptop.decode(l.encode());
      expect((back.mac, back.bcast), ('aa:bb:cc:dd:ee:ff', '192.168.1.255'));
      expect(Wake.canWake(back), isTrue);
    });
  });

  group('presentation remote', () {
    late Settings settings;
    const keysCh = MethodChannel('fasway/keys');
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      settings = Settings(await SharedPreferences.getInstance());
    });

    testWidgets('Next / Back, start, black, laser, end — and the volume buttons', (tester) async {
      final volumeKeys = <Object?>[];
      messenger.setMockMethodCallHandler(keysCh, (call) async {
        if (call.method == 'volumeKeys') volumeKeys.add(call.arguments);
        return null;
      });
      addTearDown(() => messenger.setMockMethodCallHandler(keysCh, null));
      final c = RecordingConnection(laptop());
      await tester.binding.setSurfaceSize(const Size(400, 860));
      await tester.pumpWidget(MaterialApp(home: PresentationScreen(conn: c, settings: settings)));
      await tester.pump();
      expect(volumeKeys, [true]);

      await tester.tap(find.text('Start'));
      await tester.tap(find.text('Next'));
      await tester.tap(find.text('Next'));
      await tester.tap(find.text('Back'));
      await tester.tap(find.text('Black'));
      await tester.pump();
      await tester.tap(find.text('Laser'));
      await tester.pump();
      expect(find.textContaining('move the laser'), findsOneWidget);
      await tester.drag(find.byIcon(Icons.adjust_rounded), const Offset(60, 20));
      expect(c.sent.where((m) => m['t'] == 'm'), isNotEmpty);

      // the volume buttons arrive from Android
      await messenger.handlePlatformMessage(
          'fasway/keys', const StandardMethodCodec().encodeMethodCall(const MethodCall('volume', 'up')), (_) {});
      await messenger.handlePlatformMessage(
          'fasway/keys', const StandardMethodCodec().encodeMethodCall(const MethodCall('volume', 'down')), (_) {});
      await tester.tap(find.text('End'));
      await tester.pump();
      expect(c.keys, ['f5', 'right', 'right', 'left', 'b', 'ctrl+l', 'right', 'left', 'escape']);

      await tester.pumpWidget(const SizedBox()); // leaving gives the volume buttons back
      expect(volumeKeys, [true, false]);
    });
  });

  group('routines', () {
    test('steps read as plain words', () {
      expect(StepKind.describe({'tool': 'set_volume', 'input': {'percent': 30}}), 'Volume 30%');
      expect(StepKind.describe({'tool': 'mute', 'input': {'muted': true}}), 'Mute');
      expect(StepKind.describe({'tool': 'power', 'input': {'action': 'sleep'}}), 'Laptop: Sleep');
      expect(StepKind.describe({'tool': 'play_youtube', 'input': {'query': 'lofi'}}), 'Play on YouTube: lofi');
      expect(StepKind.describe({'tool': 'wait', 'input': {'seconds': 3}}), 'Wait 3s');
      expect(StepKind.describe({'tool': 'get_time', 'input': {}}), 'get_time'); // made by the AI: shown as is
    });

    testWidgets('lists the laptop\'s routines and runs one with a tap', (tester) async {
      final c = RecordingConnection(laptop());
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: RoutinesPanel(conn: c, active: true))));
      expect(c.sent.last, {'t': 'agent_routines'});
      // the laptop answers (as if it arrived over the socket)
      c.debugReceive({'t': 'agent_routines', 'items': [
        {'id': 'a', 'icon': '🌙', 'name': 'Good night', 'phrases': [], 'steps': [
          {'tool': 'power', 'input': {'action': 'sleep'}}
        ]}
      ]});
      await tester.pump();
      await tester.tap(find.text('Good night'));
      await tester.pump();
      expect(c.sent.last, {'t': 'agent_start', 'text': 'Good night'});
      expect(find.textContaining('approve the risky step'), findsOneWidget);
      await tester.pump(const Duration(seconds: 3));
    });
  });
}
