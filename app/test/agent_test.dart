// The assistant on the phone: mirrors what the laptop reports. Nothing here needs a laptop.
import 'dart:async';

import 'package:fasway/core/agent.dart';
import 'package:fasway/core/settings.dart';
import 'package:fasway/core/speaker.dart';
import 'package:fasway/ui/agent_screen.dart';
import 'package:fasway/ui/common.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

class Rig {
  Rig() {
    agent = AgentController(
      messages: incoming.stream,
      send: (m) {
        if (!online) return false;
        sent.add(m);
        return true;
      },
      connected: () => online,
      link: link,
      deviceId: 'me',
    );
  }

  final incoming = StreamController<Map<String, dynamic>>.broadcast();
  final sent = <Map<String, dynamic>>[];
  final link = ValueNotifier(0);
  bool online = true;
  late final AgentController agent;

  Future<void> receive(Map<String, dynamic> m) async {
    incoming.add(m);
    await Future<void>.delayed(Duration.zero);
  }
}

/// Android's recognizer, with the test deciding what was heard and when.
class FakeSpeech implements SpeechToText {
  int listens = 0, stops = 0, cancels = 0;
  void Function(SpeechRecognitionResult)? _onResult;
  @override
  SpeechStatusListener? statusListener;
  @override
  SpeechErrorListener? errorListener;

  void say(String words, {required bool done}) =>
      _onResult!(SpeechRecognitionResult(
          [SpeechRecognitionWords(words, null, 0.9)], done ? ResultType.finalResult.value : ResultType.partial.value));
  void status(String s) => statusListener!(s);
  void finish() => status('done');

  @override
  bool get isListening => false;

  @override
  dynamic noSuchMethod(Invocation i) {
    switch (i.memberName) {
      case #initialize:
        return Future.value(true);
      case #listen:
        listens++;
        _onResult = i.namedArguments[#onResult] as void Function(SpeechRecognitionResult);
        return Future<void>.value();
      case #stop:
        stops++;
        return Future<void>.value();
      case #cancel:
        cancels++;
        return Future<void>.value();
    }
    return super.noSuchMethod(i);
  }
}

const settingsMsg = {
  't': 'agent_settings',
  'model': 'claude-opus-5-5',
  'has_key': false,
  'models': [
    {'id': 'claude-opus-5-5', 'label': 'Claude Opus 5.5', 'hint': 'Smartest, for tricky requests'},
    {'id': 'claude-haiku-5-5', 'label': 'Claude Haiku 5.5', 'hint': 'Fastest and cheapest'},
  ],
  'task_budget_inr': 30,
  'daily_budget_inr': 150,
  'spent_today_inr': 1.5,
  'commands_today': 3,
};

Map<String, dynamic> task(String state,
        {String id = 'a', String reply = '', String device = 'me', List<Map<String, String>> steps = const []}) =>
    {
      't': 'agent_task',
      'task': {
        'id': id, 'goal': 'do it', 'device': device, 'state': state, 'source': 'ai', 'reply': reply, 'inr': 0.5,
        'steps': steps,
      },
    };

/// The phone's voice: records what it was asked to say. [hold] keeps it "speaking" until released.
class FakeSpeaker implements Speaker {
  final said = <String>[];
  int stops = 0;
  Completer<void>? hold;

  @override
  Future<void> say(String text) async {
    said.add(text);
    if (hold != null) await hold!.future;
  }

  @override
  void stop() => stops++;

  @override
  void dispose() {}

  @override
  dynamic noSuchMethod(Invocation i) => super.noSuchMethod(i);
}

const approval = {'t': 'agent_approval', 'id': 'q', 'task': 'a', 'action': 'Shut down the laptop', 'why': 'this affects the whole laptop', 'seconds': 120};

void main() {
  group('controller', () {
    test('asks for everything on connect and again after a reconnect', () async {
      final r = Rig();
      expect(r.sent.where((m) => m['t'] == 'agent_list').length, 1);
      r.online = false;
      r.link.value++;
      r.online = true;
      r.link.value++;
      expect(r.sent.where((m) => m['t'] == 'agent_list').length, 2);
    });

    test('tasks update in place and the active one is known', () async {
      final r = Rig();
      await r.receive(task('running'));
      expect(r.agent.activeTask?.id, 'a');
      await r.receive(task('done', reply: 'ok', steps: [
        {'text': 'Volume 30%', 'status': 'done'}
      ]));
      expect(r.agent.tasks.length, 1);
      expect(r.agent.tasks.single.reply, 'ok');
      expect(r.agent.tasks.single.steps.single.text, 'Volume 30%');
      expect(r.agent.activeTask, isNull);
    });

    test('approvals: answered once, cleared when another phone answers', () async {
      final r = Rig();
      final events = <AgentApproval?>[];
      r.agent.onApprovalChanged = events.add;
      await r.receive(approval);
      await r.receive(approval); // repeated: still one card
      expect(r.agent.approvals.length, 1);
      r.agent.answer(r.agent.approvals.single, true, remember: true);
      expect(r.sent.last, {'t': 'agent_approve', 'id': 'q', 'ok': true, 'remember': true});
      expect(r.agent.approvals, isEmpty);
      await r.receive(approval);
      await r.receive({'t': 'agent_approval_done', 'id': 'q'});
      expect(r.agent.approvals, isEmpty);
      expect(events.last, isNull);
    });

    test('an answer that could not be sent keeps the card', () async {
      final r = Rig();
      await r.receive(approval);
      r.online = false;
      r.agent.answer(r.agent.approvals.single, true);
      expect(r.agent.approvals.length, 1);
    });

    test('settings, model choice, and empty text', () async {
      final r = Rig();
      await r.receive(Map<String, dynamic>.from(settingsMsg));
      expect(r.agent.hasKey, false);
      expect(r.agent.models.length, 2);
      expect(r.agent.spentToday, 1.5);
      r.agent.setModel('claude-haiku-5-5');
      expect(r.sent.last, {'t': 'agent_set', 'model': 'claude-haiku-5-5'});
      expect(r.agent.start('   '), false);
      expect(r.agent.start(' volume 30 '), true);
      expect(r.sent.last, {'t': 'agent_start', 'text': 'volume 30'});
    });

    test('only this phone\'s requests are announced as finished, and only as they finish', () async {
      final r = Rig();
      final finished = <String>[];
      r.agent.onFinished = (t) => finished.add(t.id);
      await r.receive(task('running', id: 'mine'));
      await r.receive(task('running', id: 'other', device: 'tablet'));
      await r.receive(task('done', id: 'other', device: 'tablet'));
      await r.receive(task('done', id: 'old')); // already finished when first seen (catching up)
      expect(finished, isEmpty);
      await r.receive(task('done', id: 'mine', reply: 'Volume 30%'));
      await r.receive(task('done', id: 'mine', reply: 'Volume 30%')); // repeated: once only
      expect(finished, ['mine']);
    });

    test('replies are made fit to be heard', () {
      expect(Speaker.spoken('Volume 30%'), 'Volume 30 percent');
      expect(Speaker.spoken('📶 **Done**'), 'Done');
      expect(Speaker.spoken('Opened Claude and ChatGPT'), 'Opened Clawd and Chat G P T');
      expect(Speaker.spoken('claude kholo'), 'Clawd kholo');
      expect(Speaker.spoken('GPT-6 Luna'), 'G P T-6 Luna');
      expect(Speaker.spoken('क्लाउड खोल दिया'), 'क्लॉड खोल दिया');
    });

    test('a catch-up list replaces what the phone knew', () async {
      final r = Rig();
      await r.receive(task('running'));
      await r.receive({
        ...settingsMsg,
        't': 'agent_list',
        'tasks': [(task('stopped', id: 'b')['task'])],
        'approvals': const [],
      });
      expect(r.agent.tasks.single.id, 'b');
      expect(r.agent.activeTask, isNull);
    });
  });

  group('screen', () {
    Future<void> feed(WidgetTester tester, Rig r, Map<String, dynamic> m) async {
      r.incoming.add(m);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
    }

    Future<(Rig, Settings)> open(WidgetTester tester, {Size size = const Size(360, 700)}) async {
      SharedPreferences.setMockInitialValues({});
      final settings = Settings((await tester.runAsync(SharedPreferences.getInstance))!);
      await tester.binding.setSurfaceSize(size);
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final r = Rig();
      await tester.pumpWidget(MaterialApp(theme: faswayTheme(), home: AgentScreen(agent: r.agent, settings: settings)));
      await feed(tester, r, Map<String, dynamic>.from(settingsMsg));
      return (r, settings);
    }

    testWidgets('no key: explains, and examples still work', (tester) async {
      final (r, _) = await open(tester);
      expect(find.textContaining('add an API key'), findsOneWidget);
      await tester.ensureVisible(find.text('gaana badlo'));
      await tester.pump(const Duration(seconds: 1));
      await tester.tap(find.text('gaana badlo'));
      await tester.pump();
      expect(r.sent.last, {'t': 'agent_start', 'text': 'gaana badlo'});
      await feed(tester, r, task('done', reply: 'Next track'));
    });

    testWidgets('tapping an earlier request puts it back to fix or resend', (tester) async {
      final (r, _) = await open(tester);
      await feed(tester, r, task('failed', reply: 'not understood'));
      await tester.tap(find.text('do it'));
      await tester.pump();
      expect(find.widgetWithText(TextField, 'do it'), findsOneWidget);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600)); // the send button pops in
      await tester.tap(find.byTooltip('Send'));
      await tester.pump();
      expect(r.sent.last, {'t': 'agent_start', 'text': 'do it'});
      await feed(tester, r, task('done', id: 'b'));
      await tester.pump(const Duration(seconds: 3));
    });

    testWidgets('a laptop that never answers is explained, and an answer clears it', (tester) async {
      final (r, _) = await open(tester);
      expect(r.agent.start('volume 30'), true);
      await tester.pump(AgentController.replyTimeout + const Duration(milliseconds: 100));
      expect(find.textContaining('older Fasway'), findsOneWidget);
      await feed(tester, r, task('done'));
      expect(find.textContaining('older Fasway'), findsNothing);
    });

    final voice = FakeSpeaker();
    Future<(Rig, FakeSpeech)> openWithMic(WidgetTester tester, {bool speakReplies = true}) async {
      SharedPreferences.setMockInitialValues({'flutter.speakReplies': speakReplies});
      final settings = Settings((await tester.runAsync(SharedPreferences.getInstance))!);
      await tester.binding.setSurfaceSize(const Size(360, 700));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final r = Rig();
      final stt = FakeSpeech();
      voice
        ..said.clear()
        ..stops = 0
        ..hold = null;
      await tester.pumpWidget(MaterialApp(
          theme: faswayTheme(), home: AgentScreen(agent: r.agent, settings: settings, speech: stt, speaker: voice)));
      await feed(tester, r, Map<String, dynamic>.from(settingsMsg));
      r.sent.clear();
      return (r, stt);
    }

    group('floating assistant bar', () {
      Future<(Rig, FakeSpeech, List<bool>)> openBar(WidgetTester tester) async {
        SharedPreferences.setMockInitialValues({});
        final settings = Settings((await tester.runAsync(SharedPreferences.getInstance))!);
        await tester.binding.setSurfaceSize(const Size(360, 700));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        final r = Rig();
        final stt = FakeSpeech();
        final opened = <bool>[];
        await tester.pumpWidget(MaterialApp(
          theme: faswayTheme(),
          home: Builder(
            builder: (context) => Scaffold(
              body: Center(
                child: TextButton(
                  onPressed: () => showModalBottomSheet<void>(
                    context: context,
                    isScrollControlled: true,
                    enableDrag: false,
                    backgroundColor: Colors.transparent,
                    builder: (_) => AgentScreen(
                        agent: r.agent, settings: settings, speech: stt, speaker: FakeSpeaker(), compact: true, onOpenFull: opened.add),
                  ),
                  child: const Text('open bar'),
                ),
              ),
            ),
          ),
        ));
        await feed(tester, r, Map<String, dynamic>.from(settingsMsg));
        await tester.tap(find.text('open bar'));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 600));
        r.sent.clear();
        return (r, stt, opened);
      }

      testWidgets('ask by holding the mic, see the answer, without leaving the screen', (tester) async {
        final (r, stt, _) = await openBar(tester);
        expect(find.textContaining('ask anything about your laptop'), findsOneWidget);
        final g = await tester.startGesture(tester.getCenter(find.byKey(const ValueKey('agent-mic'))));
        await tester.pump(const Duration(seconds: 1));
        stt.say('volume 30', done: true);
        await g.up();
        await tester.pump(const Duration(seconds: 2));
        expect(r.sent.last, {'t': 'agent_start', 'text': 'volume 30'});
        await feed(tester, r, task('running'));
        await feed(tester, r, task('done', reply: 'Volume 30%'));
        expect(find.text('Volume 30%'), findsOneWidget);
        expect(find.text('open bar'), findsOneWidget); // the screen underneath is still there
        await tester.tap(find.byTooltip('Close'));
        await tester.pump();
        await tester.pump(const Duration(seconds: 3));
        expect(find.byKey(const ValueKey('agent-mic')), findsNothing);
      });

      testWidgets('the waveform opens full Live; the expand button opens the full page', (tester) async {
        var (_, _, opened) = await openBar(tester);
        await tester.tap(find.byTooltip('Conversation: just talk, it answers aloud'));
        await tester.pump();
        await tester.pump(const Duration(seconds: 1));
        expect(opened, [true]);
        expect(find.byKey(const ValueKey('agent-mic')), findsNothing); // the bar made way
        (_, _, opened) = await openBar(tester);
        await tester.tap(find.byTooltip('Open assistant'));
        await tester.pump();
        await tester.pump(const Duration(seconds: 1));
        expect(opened, [false]);
        await tester.pump(const Duration(seconds: 3));
      });
    });

    group('talking back', () {
      final talk = find.byTooltip('Conversation: just talk, it answers aloud');
      final mic = find.byKey(const ValueKey('agent-mic'));
      List<Map<String, dynamic>> starts(Rig r) => r.sent.where((m) => m['t'] == 'agent_start').toList();

      Future<void> holdAndSay(WidgetTester tester, FakeSpeech stt, String words) async {
        final g = await tester.startGesture(tester.getCenter(mic));
        await tester.pump(const Duration(seconds: 1));
        stt.say(words, done: true);
        await g.up();
        await tester.pump(const Duration(seconds: 2));
      }

      testWidgets('a spoken request is answered aloud; a typed one is not', (tester) async {
        final (r, stt) = await openWithMic(tester);
        await holdAndSay(tester, stt, 'battery kitni hai');
        await feed(tester, r, task('running'));
        await feed(tester, r, task('done', reply: 'Battery 80%'));
        expect(voice.said, ['Battery 80%']);
        await tester.enterText(find.byType(TextField), 'volume 30');
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 600)); // the send button pops in
        await tester.tap(find.byTooltip('Send'));
        await feed(tester, r, task('running', id: 'b'));
        await feed(tester, r, task('done', id: 'b', reply: 'Volume 30%'));
        expect(voice.said, ['Battery 80%']);
        await tester.pump(const Duration(seconds: 3));
      });

      testWidgets('spoken answers can be switched off', (tester) async {
        final (r, stt) = await openWithMic(tester, speakReplies: false);
        await holdAndSay(tester, stt, 'battery kitni hai');
        await feed(tester, r, task('running'));
        await feed(tester, r, task('done', reply: 'Battery 80%'));
        expect(voice.said, isEmpty);
        await tester.tap(find.byTooltip('Spoken answers off'));
        await tester.pump();
        expect(find.byTooltip('Spoken answers on'), findsOneWidget);
        await tester.pump(const Duration(seconds: 3));
      });

      testWidgets('conversation: listens, sends, answers aloud, listens again, ends on "bas"', (tester) async {
        final (r, stt) = await openWithMic(tester);
        await tester.tap(talk);
        await tester.pump();
        expect(stt.listens, 1);
        expect(find.text('Listening…'), findsOneWidget);
        stt.say('volume thoda kam karo', done: false);
        stt.say('volume thoda kam karo', done: true); // a pause ended the sentence: no button involved
        await tester.pump();
        expect(starts(r).single['text'], 'volume thoda kam karo');
        expect(find.text('Working…'), findsOneWidget);
        await feed(tester, r, task('running'));
        voice.hold = Completer();
        r.incoming.add(task('done', reply: 'Volume down'));
        await tester.pump();
        expect(find.text('Speaking…'), findsOneWidget);
        expect(stt.listens, 1); // not while it is talking: it would hear itself
        voice.hold!.complete();
        voice.hold = null;
        await tester.pump(const Duration(milliseconds: 100));
        expect(voice.said, ['Volume down']);
        expect(stt.listens, 2);
        stt.say('bas', done: true);
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300)); // Live fades away
        expect(find.byTooltip('End conversation'), findsNothing);
        expect(voice.said.last, 'Okay, bye');
        expect(starts(r).length, 1); // "bas" ends it; it isn't sent as a command
        await tester.pump(const Duration(seconds: 3));
        expect(stt.listens, 2);
      });

      testWidgets('conversation: silence never ends it; only the user does', (tester) async {
        final (r, stt) = await openWithMic(tester);
        await tester.tap(talk);
        await tester.pump();
        for (var i = 0; i < 5; i++) {
          stt.finish(); // gave up listening: nothing said
          await tester.pump(const Duration(milliseconds: 400));
        }
        expect(stt.listens, 6); // listening again every time
        expect(find.byTooltip('End conversation'), findsOneWidget);
        expect(starts(r), isEmpty);
        await tester.tap(find.byTooltip('End conversation'));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 500));
        expect(find.byTooltip('End conversation'), findsNothing);
        await tester.pump(const Duration(seconds: 3));
      });

      testWidgets('conversation: an approval is asked for on screen, never by voice', (tester) async {
        final (r, stt) = await openWithMic(tester);
        await tester.tap(talk);
        await tester.pump();
        stt.say('laptop band kar do', done: true);
        await tester.pump();
        await feed(tester, r, task('waiting_approval'));
        await feed(tester, r, Map<String, dynamic>.from(approval));
        expect(voice.said.last, contains('OK on the phone screen'));
        expect(r.sent.where((m) => m['t'] == 'agent_approve'), isEmpty);
        await tester.tap(find.byTooltip('End conversation'));
        await tester.pump(const Duration(seconds: 3));
      });

      testWidgets('Live: tapping the light cuts a long answer short and it listens again', (tester) async {
        final (r, stt) = await openWithMic(tester);
        await tester.tap(talk);
        await tester.pump(const Duration(milliseconds: 500));
        stt.say('ek lambi kahani sunao', done: true);
        await tester.pump();
        await feed(tester, r, task('running'));
        voice.hold = Completer(); // a long answer, still being read out
        r.incoming.add(task('done', reply: 'Once upon a time…'));
        await tester.pump(const Duration(milliseconds: 500));
        expect(find.text('Speaking…'), findsOneWidget);
        final stopsBefore = voice.stops;
        await tester.tap(find.byTooltip('Interrupt'));
        expect(voice.stops, greaterThan(stopsBefore));
        voice.hold!.complete(); // what the phone's voice does when stopped
        voice.hold = null;
        await tester.pump(const Duration(milliseconds: 500));
        expect(find.text('Listening…'), findsOneWidget);
        expect(stt.listens, 2);
        await tester.tap(find.byTooltip('End conversation'));
        await tester.pump(const Duration(seconds: 3));
      });
    });

    group('push to talk', () {

      final mic = find.byKey(const ValueKey('agent-mic'));
      List<Map<String, dynamic>> starts(Rig r) => r.sent.where((m) => m['t'] == 'agent_start').toList();

      testWidgets('nothing is sent until the finger lifts, then it is', (tester) async {
        final (r, stt) = await openWithMic(tester);
        final g = await tester.startGesture(tester.getCenter(mic));
        await tester.pump();
        expect(stt.listens, 1);
        expect(find.textContaining('slide left to cancel'), findsOneWidget);
        await tester.pump(const Duration(seconds: 1));
        stt.say('volume', done: false);
        stt.say('volume 30', done: true); // Android thinks the sentence ended; the finger says otherwise
        await tester.pump();
        expect(starts(r), isEmpty);
        await g.up();
        await tester.pump(const Duration(milliseconds: 100));
        stt.finish();
        await tester.pump(const Duration(seconds: 2));
        expect(starts(r).single['text'], 'volume 30');
        expect(stt.stops, 1);
        await feed(tester, r, task('done'));
      });

      testWidgets('a pause while holding keeps listening and joins the words', (tester) async {
        final (r, stt) = await openWithMic(tester);
        final g = await tester.startGesture(tester.getCenter(mic));
        await tester.pump(const Duration(seconds: 1));
        stt.say('volume kam karo', done: true);
        stt.status('done');
        await tester.pump(const Duration(milliseconds: 200));
        expect(stt.listens, 2); // back to listening on its own
        stt.say('aur youtube kholo', done: false);
        await g.up();
        await tester.pump(const Duration(milliseconds: 100));
        stt.say('aur youtube kholo', done: true);
        await tester.pump(const Duration(seconds: 2));
        expect(starts(r).single['text'], 'volume kam karo aur youtube kholo');
        await feed(tester, r, task('done'));
      });

      testWidgets('a quick tap sends nothing and explains', (tester) async {
        final (r, stt) = await openWithMic(tester);
        final g = await tester.startGesture(tester.getCenter(mic));
        await tester.pump(const Duration(milliseconds: 50));
        await g.up();
        await tester.pump(const Duration(milliseconds: 100));
        expect(starts(r), isEmpty);
        expect(stt.cancels, 1);
        expect(find.textContaining('Hold the mic'), findsOneWidget);
        await tester.pump(const Duration(seconds: 3));
      });

      testWidgets('silence sends nothing', (tester) async {
        final (r, stt) = await openWithMic(tester);
        final g = await tester.startGesture(tester.getCenter(mic));
        await tester.pump(const Duration(seconds: 1));
        await g.up();
        await tester.pump(const Duration(seconds: 2));
        expect(starts(r), isEmpty);
        expect(find.textContaining("didn't hear"), findsOneWidget);
        expect(stt.listens, 1);
        await tester.pump(const Duration(seconds: 3));
      });

      testWidgets('sliding onto the bin and letting go throws the recording away', (tester) async {
        final (r, stt) = await openWithMic(tester);
        final g = await tester.startGesture(tester.getCenter(mic));
        await tester.pump();
        await tester.pump(const Duration(seconds: 1));
        final bin = find.byKey(const ValueKey('agent-mic-bin'));
        expect(bin, findsOneWidget); // the bin appears while holding
        Color binColor() => ((tester.widget<Container>(bin).decoration as BoxDecoration).color)!;
        stt.say('laptop band kar do', done: false);
        await g.moveBy(const Offset(-40, 0));
        await tester.pump(const Duration(milliseconds: 100));
        expect(binColor(), isNot(C.bad)); // not far enough yet
        await g.moveBy(const Offset(-60, 0));
        await tester.pump(const Duration(milliseconds: 100));
        expect(binColor(), C.bad); // armed: red
        await g.moveBy(const Offset(80, 0)); // changed my mind: back towards the mic
        await tester.pump(const Duration(milliseconds: 100));
        expect(binColor(), isNot(C.bad));
        await g.moveBy(const Offset(0, -120)); // sliding up works too
        await tester.pump(const Duration(milliseconds: 100));
        expect(binColor(), C.bad);
        await g.up();
        await tester.pump();
        await tester.pump(const Duration(seconds: 2));
        expect(starts(r), isEmpty);
        expect(stt.cancels, 1);
        expect(stt.stops, 0);
        expect(find.text('Cancelled'), findsOneWidget);
        expect(bin, findsNothing);
        await tester.pump(const Duration(seconds: 3));
      });

      testWidgets('a cancelled touch sends nothing', (tester) async {
        final (r, stt) = await openWithMic(tester);
        final g = await tester.startGesture(tester.getCenter(mic));
        await tester.pump(const Duration(seconds: 1));
        stt.say('shutdown', done: false);
        await g.cancel();
        await tester.pump(const Duration(seconds: 2));
        expect(starts(r), isEmpty);
        expect(stt.cancels, 1);
      });
    });

    testWidgets('choosing a model tells the laptop', (tester) async {
      final (r, _) = await open(tester);
      expect(find.text('Opus 5.5'), findsOneWidget); // the pill at the top
      await tester.tap(find.byTooltip('Choose AI model'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('Fastest and cheapest'), findsOneWidget);
      await tester.tap(find.text('Claude Haiku 5.5'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
      expect(r.sent.last, {'t': 'agent_set', 'model': 'claude-haiku-5-5'});
      expect(find.text('Haiku 5.5'), findsOneWidget); // the pill shows the new choice
    });

    testWidgets('approval card: allow and deny', (tester) async {
      final (r, _) = await open(tester);
      await feed(tester, r, Map<String, dynamic>.from(approval));
      expect(find.text('Shut down the laptop'), findsOneWidget);
      expect(find.text('Asking because this affects the whole laptop'), findsOneWidget);
      await tester.tap(find.text("Don't allow"));
      await tester.pump();
      expect(r.sent.last, {'t': 'agent_approve', 'id': 'q', 'ok': false, 'remember': false});
      expect(find.text('Shut down the laptop'), findsNothing);
      // Allow first asks "Confirm it's you" on the phone: a "no" sends nothing
      var lockSays = false;
      const lock = MethodChannel('fasway/lock');
      final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(lock, (call) async => lockSays);
      addTearDown(() => messenger.setMockMethodCallHandler(lock, null));
      await feed(tester, r, Map<String, dynamic>.from(approval));
      final before = r.sent.length;
      await tester.tap(find.text('Allow'));
      await tester.pump();
      await tester.pump();
      expect(r.sent.length, before);
      lockSays = true;
      await tester.tap(find.text('Allow'));
      await tester.pump();
      await tester.pump();
      expect(r.sent.last['ok'], true);
    });

    testWidgets('STOP shows only while a task runs', (tester) async {
      final (r, _) = await open(tester);
      expect(find.byTooltip('Stop'), findsNothing);
      await feed(tester, r, task('running', steps: [
        {'text': 'Opening notepad', 'status': 'running'}
      ]));
      await tester.tap(find.byTooltip('Stop'));
      await tester.pump();
      expect(r.sent.last, {'t': 'agent_stop', 'task': 'a'});
      await feed(tester, r, task('stopped', reply: 'Stopped.'));
      expect(find.byTooltip('Stop'), findsNothing);
      expect(find.text('Stopped.'), findsOneWidget);
    });

    testWidgets('a busy screen fits a small phone', (tester) async {
      final (r, _) = await open(tester, size: const Size(320, 560));
      for (var i = 0; i < 12; i++) {
        await feed(tester, r, task('done', id: 't$i', reply: 'Long reply ' * 12, steps: [
          {'text': 'A long step description that needs to wrap on a small phone screen', 'status': 'done'},
          {'text': 'Declined step', 'status': 'declined'},
        ]));
      }
      await feed(tester, r, task('waiting_approval', id: 'z'));
      await feed(tester, r, Map<String, dynamic>.from(approval));
      expect(tester.takeException(), isNull);
    });
  });
}
