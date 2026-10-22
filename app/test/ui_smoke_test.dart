// Smoke test of the whole UI: starts the app with a paired (unreachable) laptop, goes through every
// tab, the settings sheet, the touchpad and the Files tab, and fails on any layout / animation error.
import 'dart:io';

import 'package:fasway/core/laptop.dart';
import 'package:fasway/main.dart';
import 'package:fasway/ui/common.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('scrolling that starts on a button does not press it; a tap does', (tester) async {
    var presses = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ListView(children: [
          for (var i = 0; i < 30; i++)
            Row(children: [KeyButton(label: 'B$i', onPress: () => presses++)]),
        ]),
      ),
    ));
    await tester.drag(find.text('B2'), const Offset(0, -200)); // scroll the list, starting on a button
    await tester.pumpAndSettle();
    expect(presses, 0);
    await tester.tap(find.text('B8'));
    await tester.pump();
    expect(presses, 1);
  });

  testWidgets('every tab and sheet builds and animates', (tester) async {
    HttpOverrides.global = null; // real sockets: the laptop at 127.0.0.1:1 just refuses (no fake HTTP)
    final laptop = Laptop(id: 'smoke', host: '127.0.0.1', port: 1, token: 't', fp: 'ab' * 32);
    SharedPreferences.setMockInitialValues({'flutter.laptop': laptop.encode(), 'flutter.identity_in_prefs': true});
    await tester.binding.setSurfaceSize(const Size(400, 860));

    await tester.pumpWidget(const FaswayApp());
    // startup runs on real async work (prefs, timeouts): let it finish
    for (var i = 0; i < 30 && find.text('Touchpad').evaluate().isEmpty; i++) {
      await tester.runAsync(() => Future.delayed(const Duration(milliseconds: 100)));
      await tester.pump(const Duration(milliseconds: 100));
    }
    await tester.pumpAndSettle(const Duration(milliseconds: 50), EnginePhase.sendSemanticsUpdate, const Duration(seconds: 5))
        .catchError((_) => 0); // the status dot keeps pulsing while it tries to connect
    expect(find.text('Touchpad'), findsOneWidget);

    // touchpad: finger down / move / tap -> glow and ripple
    final pad = find.textContaining('1 finger: move');
    final g = await tester.startGesture(tester.getCenter(pad));
    await tester.pump(const Duration(milliseconds: 50));
    await g.moveBy(const Offset(30, 10));
    await tester.pump(const Duration(milliseconds: 50));
    await g.up();
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    for (final tab in ['Keyboard', 'Voice', 'Apps', 'Files', 'Controls', 'Touchpad']) {
      await tester.tap(find.text(tab));
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 80)); // tab slide + fade
      }
      final ex = tester.takeException();
      if (ex is FlutterError) debugPrint(ex.toStringDeep());
      expect(ex, isNull, reason: 'tab $tab');
    }

    // Files tab content
    await tester.tap(find.text('Files'));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Send to laptop'), findsOneWidget);
    expect(find.text('No transfers yet'), findsOneWidget);

    // settings sheet opens with its animation and the haptics switch toggles
    await tester.tap(find.byTooltip('Settings'));
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 80));
    }
    expect(find.text('Vibration'), findsOneWidget);
    await tester.tap(find.text('Vibration'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(const SizedBox()); // dispose everything (timers, tickers)
    await tester.pump(const Duration(seconds: 2));
  });
}
