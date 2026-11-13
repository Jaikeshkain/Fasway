// "What's new" fits a small phone, its "Try it" buttons act, and "Let's go" closes it.
import 'package:fasway/ui/common.dart';
import 'package:fasway/ui/whats_new.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('what\'s new: fits, tries, closes', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 560));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final tried = <String>[];
    await tester.pumpWidget(MaterialApp(
      theme: faswayTheme(),
      home: Builder(
        builder: (context) => Scaffold(
          body: TextButton(
            onPressed: () => showWhatsNew(context, onAssistant: () => tried.add('assistant'), onLive: () => tried.add('live')),
            child: const Text('show'),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('show'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 2));
    expect(find.text('What\'s new'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('Try it').first);
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(tried, ['assistant']);
    expect(find.text('What\'s new'), findsNothing);

    await tester.tap(find.text('show'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 2));
    await tester.ensureVisible(find.text('Let\'s go'));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.text('Let\'s go'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('What\'s new'), findsNothing);
    await tester.pump(const Duration(seconds: 3));
  });
}
