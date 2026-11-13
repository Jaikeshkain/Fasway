import 'dart:async';

import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../core/agent.dart';
import '../core/connection.dart';
import '../core/settings.dart';
import '../core/speaker.dart';
import 'ai_effects.dart';
import 'common.dart';
import 'screen_preview.dart';

/// Ask the laptop to do things, by voice or text. The laptop does the work; this shows progress and
/// asks for approval when a step needs it.
class AgentScreen extends StatefulWidget {
  const AgentScreen(
      {super.key,
      required this.agent,
      required this.settings,
      this.preview,
      this.speech,
      this.speaker,
      this.compact = false,
      this.startLive = false,
      this.onOpenFull});

  /// The floating assistant's bar (from any screen): the newest answer and the input, nothing else.
  final bool compact;

  /// Open straight into Live (the bar's waveform button).
  final bool startLive;

  /// The bar asks for the full page; `live`: go straight into Live there.
  final void Function(bool live)? onOpenFull;
  final AgentController agent;
  final Settings settings;
  final PreviewController? preview; // the laptop screen, shared with the touchpad tab
  final SpeechToText? speech; // tests pass stand-ins for the phone's speech in and out
  final Speaker? speaker;
  @override
  State<AgentScreen> createState() => _AgentScreenState();
}

class _AgentScreenState extends State<AgentScreen> {
  static const _shortestPress = Duration(milliseconds: 350);

  final _text = TextEditingController();
  late final SpeechToText _stt = widget.speech ?? SpeechToText();
  bool _sttReady = false, _listening = false, _holding = false;
  String _heard = ''; // finished sentences while the mic is held (Android splits speech at pauses)
  bool _heldLongEnough = false;
  Offset _downAt = Offset.zero;
  bool _cancelArmed = false; // the finger slid away from the mic: letting go now throws the recording away
  static const _cancelDistance = 70.0;
  Timer? _pressTimer;
  Completer<void>? _lastWords;

  // ---- speaking back, and the hands-free conversation ----
  late final Speaker _speaker = widget.speaker ?? Speaker();
  static const _goodbyes = {'bas', 'bas karo', 'stop', 'bye', 'bye bye', 'ok bye', 'thank you', 'thanks', 'thats all',
    'that is all', 'alvida', 'बस', 'धन्यवाद', 'अलविदा'};
  bool _talk = false; // conversation mode: listen, send, answer aloud, listen again
  String _talkStatus = '';
  bool _talkHeard = false;
  int _talkMisses = 0;
  bool _byVoice = false; // the last request was spoken, so its answer is spoken too
  int _approvalsSeen = 0;

  AgentController get a => widget.agent;
  bool get _answerAloud => _talk || (_byVoice && widget.settings.speakReplies);

  @override
  void initState() {
    super.initState();
    Connection.agentPermission();
    a.onFinished = _onFinished;
    a.addListener(_onAgent);
    _approvalsSeen = a.approvals.length;
    _text.addListener(_onText);
    if (widget.startLive) WidgetsBinding.instance.addPostFrameCallback((_) => mounted ? _startTalk() : null);
  }

  bool _hadText = false;

  /// The send button appears with text; in Live, the words show as they're heard.
  void _onText() {
    final has = _text.text.trim().isNotEmpty;
    if (has != _hadText || _talk) setState(() => _hadText = has);
  }

  /// Live: tapping the light cuts a long answer short, and it listens again.
  void _interrupt() {
    if (_talkStatus != 'Speaking…') return;
    Fx.tap();
    _speaker.stop();
  }

  @override
  void dispose() {
    _holding = false;
    _talk = false;
    _pressTimer?.cancel();
    if (_listening || _talkStatus.isNotEmpty) _stt.cancel();
    // the bar closing while the full page opens: don't take the page's listener away with us
    if (a.onFinished == _onFinished) a.onFinished = null;
    a.removeListener(_onAgent);
    _speaker.dispose();
    _text.dispose();
    super.dispose();
  }

  bool _send([String? value, bool voice = false]) {
    final text = value ?? _text.text;
    if (!a.start(text)) {
      if (text.trim().isNotEmpty) toast(context, 'The laptop is not connected');
      return false;
    }
    Fx.tap();
    _byVoice = voice;
    _text.clear();
    return true;
  }

  Future<void> _onFinished(AgentTask t) async {
    if (!mounted || !_answerAloud) return;
    _byVoice = false;
    setState(() => _talkStatus = _talk ? 'Speaking…' : '');
    await _speaker.say(t.reply.isEmpty ? 'Done' : t.reply);
    if (!mounted) return;
    if (_talk) {
      _listenForTalk();
    } else {
      setState(() => _talkStatus = '');
    }
  }

  void _onAgent() {
    if (a.approvals.length > _approvalsSeen && _answerAloud) {
      _speaker.say('I need your OK on the phone screen first'); // never by voice: a misheard "yes" could shut the laptop down
    }
    _approvalsSeen = a.approvals.length;
    if (_talk && a.laptopOutdated) _endTalk();
  }

  Future<void> _startTalk() async {
    Fx.tap();
    if (_talk) return _endTalk(goodbye: 'Okay');
    _speaker.stop();
    setState(() {
      _talk = true;
      _talkMisses = 0;
      _talkStatus = 'Starting…';
    });
    if (_stt.isListening) await _stt.stop();
    _sttReady = _sttReady || await _stt.initialize();
    if (!mounted || !_talk) return;
    if (!_sttReady) {
      _endTalk();
      toast(context, 'Speech recognition is not available');
      return;
    }
    await _listenForTalk();
  }

  Future<void> _listenForTalk() async {
    if (!_talk || !mounted) return;
    _talkHeard = false;
    _text.clear();
    setState(() => _talkStatus = 'Listening…');
    _stt.statusListener = (s) {
      if ((s == 'done' || s == 'notListening') && _talk && _talkStatus == 'Listening…' && !_talkHeard) _talkSilence();
    };
    _stt.errorListener = (e) {
      if (e.errorMsg.contains('permission') && mounted) {
        _endTalk();
        toast(context, 'Microphone permission denied');
      }
    };
    final hindi = widget.settings.lang == 'hi' || widget.settings.lang == 'mix-deva';
    await _stt.listen(
      onResult: _onTalkSpeech,
      listenOptions: SpeechListenOptions(
        localeId: hindi ? 'hi_IN' : 'en_IN',
        listenMode: ListenMode.confirmation,
        partialResults: true,
        cancelOnError: false,
        pauseFor: const Duration(seconds: 2), // a short pause ends the sentence: no button to press
        listenFor: const Duration(seconds: 20),
      ),
    );
  }

  void _onTalkSpeech(SpeechRecognitionResult r) {
    if (!_talk || !mounted) return;
    final words = r.recognizedWords.trim();
    if (words.isNotEmpty) _talkHeard = true;
    _text.text = words;
    if (!r.finalResult || words.isEmpty) return;
    _talkMisses = 0;
    final said = words.toLowerCase().replaceAll(RegExp(r"[^\p{L}\p{N}\s]", unicode: true), '').trim();
    if (_goodbyes.contains(said)) {
      _text.clear();
      _endTalk(goodbye: 'Okay, bye');
      return;
    }
    setState(() => _talkStatus = 'Working…');
    if (!_send(words, true)) _endTalk();
  }

  /// Listening ended with nothing said. Once may be a pause; twice in a row, the conversation is over.
  void _talkSilence() {
    if (++_talkMisses >= 2) {
      _endTalk();
      if (mounted) toast(context, 'Conversation ended');
      return;
    }
    Future.delayed(const Duration(milliseconds: 300), () {
      if (_talk && _talkStatus == 'Listening…' && !_talkHeard) _listenForTalk();
    });
  }

  void _endTalk({String? goodbye}) {
    if (!_talk && _talkStatus.isEmpty) return;
    _talk = false;
    _stt.cancel();
    _speaker.stop();
    if (mounted) setState(() => _talkStatus = '');
    if (goodbye != null) _speaker.say(goodbye);
  }

  // ---- microphone: push to talk. Hold to speak, release to send ----
  Future<void> _micDown() async {
    Fx.press();
    _endTalk(); // holding the mic takes over from a conversation, and interrupts a reply being read out
    _speaker.stop();
    _heldLongEnough = false;
    _pressTimer?.cancel();
    _pressTimer = Timer(_shortestPress, () => _heldLongEnough = true);
    _holding = true;
    _heard = '';
    _text.clear();
    setState(() => _listening = true);
    // the recognizer is shared with the Voice tab: take it over while the mic is held
    _stt.statusListener = _onSpeechStatus;
    _stt.errorListener = (e) {
      if (!mounted) return;
      if (e.errorMsg.contains('permission')) {
        _holding = false;
        setState(() => _listening = false);
        toast(context, 'Microphone permission denied');
      }
      // "no match" just means silence: the finger is still down, so keep listening (see _onSpeechStatus)
    };
    if (_stt.isListening) await _stt.stop();
    _sttReady = _sttReady || await _stt.initialize();
    if (!mounted || !_holding) return; // released while it was starting up
    if (!_sttReady) {
      _holding = false;
      setState(() => _listening = false);
      toast(context, 'Speech recognition is not available');
      return;
    }
    await _listen();
  }

  Future<void> _listen() async {
    final hindi = widget.settings.lang == 'hi' || widget.settings.lang == 'mix-deva';
    await _stt.listen(
      onResult: _onSpeech,
      listenOptions: SpeechListenOptions(
        localeId: hindi ? 'hi_IN' : 'en_IN',
        listenMode: ListenMode.dictation,
        partialResults: true,
        cancelOnError: false,
        pauseFor: const Duration(seconds: 30), // the finger decides when the sentence ends
        listenFor: const Duration(minutes: 1),
      ),
    );
  }

  void _onSpeechStatus(String status) {
    if (status != 'done' && status != 'notListening') return;
    if (_holding) {
      // Android stops by itself after a pause, even with the finger still down: carry on
      Future.delayed(const Duration(milliseconds: 100), () {
        if (_holding && mounted) _listen();
      });
    } else if (_lastWords != null) {
      Future.delayed(const Duration(milliseconds: 150), () => _lastWords?.complete());
    }
  }

  void _onSpeech(SpeechRecognitionResult r) {
    if (!mounted) return;
    final words = r.recognizedWords.trim();
    _text.text = [_heard, words].where((s) => s.isNotEmpty).join(' ');
    if (r.finalResult) {
      _heard = _text.text;
      _lastWords?.complete();
    }
  }

  /// Slide the finger away from the mic (left or up) to arm cancelling; slide back to undo.
  void _micMove(PointerMoveEvent e) {
    if (!_holding) return;
    final d = e.position - _downAt;
    final armed = d.dx < -_cancelDistance || d.dy < -_cancelDistance;
    if (armed != _cancelArmed) {
      armed ? Fx.heavy() : Fx.select();
      setState(() => _cancelArmed = armed);
    }
  }

  Future<void> _micUp() async {
    if (!_holding) return;
    _holding = false;
    _pressTimer?.cancel();
    final cancelled = _cancelArmed;
    setState(() {
      _listening = false;
      _cancelArmed = false;
    });
    if (cancelled) {   // let go over the bin: thrown away, nothing sent
      await _stt.cancel();
      _text.clear();
      if (mounted) toast(context, 'Cancelled');
      return;
    }
    if (!_heldLongEnough) {
      await _stt.cancel();
      _text.clear();
      if (mounted) toast(context, 'Hold the mic while you speak, then let go');
      return;
    }
    // the last words arrive just after the mic stops
    final done = _lastWords = Completer<void>();
    await _stt.stop();
    await done.future.timeout(const Duration(milliseconds: 1500), onTimeout: () {});
    _lastWords = null;
    if (!mounted) return;
    if (_text.text.trim().isEmpty) {
      toast(context, 'I didn\'t hear anything');
    } else {
      _send(null, true);
    }
  }

  /// The system took the touch away (a call, a permission dialog): nothing is sent.
  void _micCancel() {
    if (!_holding) return;
    _holding = false;
    _pressTimer?.cancel();
    _stt.cancel();
    _text.clear();
    setState(() => _listening = false);
  }

  // ---- menus ----
  Future<void> _budgets() async {
    final task = TextEditingController(text: '${a.taskBudget}');
    final day = TextEditingController(text: '${a.dailyBudget}');
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('AI spending limits'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
              controller: task,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Per task (₹)')),
          const SizedBox(height: 8),
          TextField(
              controller: day,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Per day (₹)')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Save')),
        ],
      ),
    );
    final t = int.tryParse(task.text.trim()), d = int.tryParse(day.text.trim());
    task.dispose();
    day.dispose();
    if (ok == true && t != null && d != null && t > 0 && d > 0) a.setBudgets(t, d);
  }

  // ---- the page ----
  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: Listenable.merge([a, widget.settings]), // settings: Live makes room when the touchpad opens
        builder: (context, _) {
          final active = a.activeTask;
          // a new route-like page, but kept in this state so listening and speaking carry straight on
          return AnimatedSwitcher(
            duration: Motion.slow,
            reverseDuration: Motion.fast,
            switchInCurve: Motion.curve,
            transitionBuilder: (child, anim) => FadeTransition(
              opacity: anim,
              child: ScaleTransition(scale: Tween(begin: 0.96, end: 1.0).animate(anim), child: child),
            ),
            child: widget.compact
                ? _bar(active)
                : _talk
                    ? _live(key: const ValueKey('live'))
                    : _chat(active, key: const ValueKey('chat')),
          );
        },
      );

  Widget _chat(AgentTask? active, {Key? key}) {
    final keyboard = MediaQuery.viewInsetsOf(context).bottom > 0;
    return Scaffold(
      key: key,
      backgroundColor: C.bg,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        centerTitle: true,
        title: _ModelPill(a, onTap: _pickModel),
        actions: [
          if (widget.preview != null) _screenToggle(),
          ListenableBuilder(
            listenable: widget.settings,
            builder: (context, _) => IconButton(
              tooltip: widget.settings.speakReplies ? 'Spoken answers on' : 'Spoken answers off',
              icon: Icon(widget.settings.speakReplies ? Icons.volume_up_rounded : Icons.volume_off_rounded,
                  color: widget.settings.speakReplies ? Ai.violet : C.muted),
              onPressed: () {
                Fx.select();
                if (widget.settings.speakReplies) _speaker.stop();
                widget.settings.set('speakReplies', !widget.settings.speakReplies);
              },
            ),
          ),
          _menu(),
        ],
      ),
      body: Stack(children: [
        Positioned.fill(child: AuraBackground(busy: active != null || _listening)),
        SafeArea(
          top: false,
          child: Column(children: [
            // watch what the assistant does; hidden while typing, when the keyboard needs the room
            if (widget.preview != null && !keyboard) _ScreenCard(preview: widget.preview!, settings: widget.settings, busy: active != null),
            if (a.laptopOutdated) const _Banner(color: C.bad, text: _outdatedText),
            if (!keyboard && a.loaded && !a.hasKey && a.tasks.isEmpty) const _Banner(color: C.warn, text: _noKeyText),
            Expanded(child: a.tasks.isEmpty ? _greeting() : _feed()),
            if (a.approvals.isNotEmpty) _approvals(),
            _inputPill(active),
            if (a.loaded)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text('Today ₹${a.spentToday.toStringAsFixed(2)} of ₹${a.dailyBudget} · ${a.commandsToday} commands',
                    style: const TextStyle(color: C.muted, fontSize: 11)),
              ),
          ]),
        ),
      ]),
    );
  }

  static const _noKeyText = 'Everyday requests about volume, music, apps and search work now. For anything else, '
      'add an API key for the chosen model in the Fasway window on the laptop.';
  static const _outdatedText = 'This laptop isn\'t answering. It\'s probably running an older Fasway without the '
      'assistant: quit Fasway from the tray and start the newer copy.';

  Widget _screenToggle() => ListenableBuilder(
        listenable: widget.settings,
        builder: (context, _) => IconButton(
          tooltip: 'Laptop screen',
          icon: Icon(Icons.desktop_windows_rounded, color: widget.settings.screenOn ? Ai.blue : C.muted),
          onPressed: () {
            Fx.select();
            widget.settings.set('screenOn', !widget.settings.screenOn);
          },
        ),
      );

  Widget _menu() => PopupMenuButton<String>(
        onSelected: (v) {
          if (v == 'new') {
            a.newConversation();
            toast(context, 'Starting fresh: it won\'t remember earlier requests');
          } else {
            _budgets();
          }
        },
        itemBuilder: (_) => const [
          PopupMenuItem(value: 'new', child: Text('New conversation')),
          PopupMenuItem(value: 'budget', child: Text('Spending limits')),
        ],
      );

  Future<void> _pickModel() async {
    Fx.tap();
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: C.panel,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: ListenableBuilder(
          listenable: a,
          builder: (c, _) => Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text('Choose the AI', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            ),
            for (final (i, m) in a.models.indexed)
              Appear(
                delay: Duration(milliseconds: 40 * i),
                child: _ModelRow(
                  model: m,
                  selected: m.id == a.model,
                  onTap: () {
                    Fx.select();
                    a.setModel(m.id);
                    Navigator.pop(c);
                  },
                ),
              ),
            const SizedBox(height: 12),
          ]),
        ),
      ),
    );
  }

  Widget _greeting() => LayoutBuilder(
        builder: (context, box) => SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 12, 24, 16),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: box.maxHeight - 28),
            child: Column(mainAxisAlignment: MainAxisAlignment.end, crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Appear(child: GradientText('Hello!', style: TextStyle(fontSize: 38, fontWeight: FontWeight.w700, height: 1.1))),
              const Appear(
                delay: Duration(milliseconds: 80),
                child: Text('What should your laptop do?',
                    style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600, color: Color(0xFF5C6070), height: 1.25)),
              ),
              const SizedBox(height: 6),
              const Appear(
                delay: Duration(milliseconds: 140),
                child: Text('Say it in English, हिंदी or Hinglish.', style: TextStyle(color: C.muted)),
              ),
              const SizedBox(height: 20),
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final (i, (icon, text)) in _suggestions.indexed)
                  Appear(
                    delay: Duration(milliseconds: 200 + 60 * i),
                    child: _SuggestionCard(icon: icon, text: text, onTap: () => _send(text)),
                  ),
              ]),
            ]),
          ),
        ),
      );

  static const _suggestions = [
    (Icons.volume_down_rounded, 'Turn the sound down a bit'),
    (Icons.skip_next_rounded, 'gaana badlo'),
    (Icons.smart_display_rounded, 'Search cats on YouTube'),
    (Icons.battery_charging_full_rounded, 'battery kitni hai'),
    (Icons.auto_awesome_motion_rounded, 'volume 30 aur YouTube kholo'),
  ];

  Widget _feed() {
    final list = a.tasks.reversed.toList();
    return ListView.builder(
      reverse: true, // newest at the bottom, next to the input
      padding: const EdgeInsets.fromLTRB(14, 8, 14, 8),
      itemCount: list.length,
      itemBuilder: (_, i) => Appear(
        key: ValueKey(list[i].id),
        child: _Exchange(
          task: list[i],
          // misheard or worth repeating: back into the box to fix or send again
          onReuse: () {
            Fx.select();
            _text.text = list[i].goal; // no message: it would cover the send button; the text in the box says it
            _text.selection = TextSelection.collapsed(offset: _text.text.length);
          },
        ),
      ),
    );
  }

  Widget _approvals() => Flexible(
        child: SingleChildScrollView(
          child: Column(children: [
            for (final x in a.approvals) _ApprovalCard(key: ValueKey(x.id), approval: x, agent: a),
          ]),
        ),
      );

  Widget _inputPill(AgentTask? active) {
    final hasText = _text.text.trim().isNotEmpty;
    final Widget trailing;
    if (active != null) {
      trailing = _RoundButton(
        key: const ValueKey('stop'),
        tooltip: 'Stop',
        icon: Icons.stop_rounded,
        color: C.bad,
        onTap: () {
          Fx.heavy();
          a.stop(active);
        },
      );
    } else if (hasText) {
      trailing = _RoundButton(key: const ValueKey('send'), tooltip: 'Send', icon: Icons.arrow_upward_rounded, gradient: true, onTap: _send);
    } else {
      trailing = _RoundButton(
          key: const ValueKey('live'),
          tooltip: 'Conversation: just talk, it answers aloud',
          icon: Icons.graphic_eq_rounded,
          gradient: true,
          onTap: widget.compact ? () => _openFull(live: true) : _startTalk);
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 6),
      child: AnimatedContainer(
        duration: Motion.medium,
        padding: EdgeInsets.fromLTRB(_listening ? 8 : 18, 4, 5, 4),
        decoration: BoxDecoration(
          // slid onto the bin: the whole bar fades to red, so letting go clearly throws it away
          color: _cancelArmed ? Color.lerp(C.panel, C.bad, 0.28) : C.panel,
          borderRadius: BorderRadius.circular(30),
          border: Border.all(
              color: _cancelArmed ? C.bad : (_listening ? Ai.pink : C.panel2), width: _listening ? 1.6 : 1),
          boxShadow: [
            BoxShadow(
                color: (_cancelArmed ? C.bad : (_listening ? Ai.pink : Ai.violet))
                    .withValues(alpha: _listening ? 0.45 : 0.12),
                blurRadius: _listening ? 22 : 14,
                spreadRadius: -4),
          ],
        ),
        child: Row(children: [
          // while the mic is held: the bin to slide to
          AnimatedSize(
            duration: Motion.medium,
            curve: Motion.spring,
            child: !_listening
                ? const SizedBox.shrink()
                : Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: AnimatedScale(
                      scale: _cancelArmed ? 1.35 : 1,
                      duration: Motion.bounceTime,
                      curve: Motion.bounce,
                      child: Container(
                        key: const ValueKey('agent-mic-bin'),
                        width: 36,
                        height: 36,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: _cancelArmed ? C.bad : C.bad.withValues(alpha: 0.12),
                        ),
                        child: Icon(Icons.delete_rounded, size: 20, color: _cancelArmed ? Colors.white : C.bad),
                      ),
                    ),
                  ),
          ),
          Expanded(
            child: TextField(
              controller: _text,
              minLines: 1,
              maxLines: 4,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _send(),
              // what was heard so far, struck through: it is about to be thrown away
              style: _cancelArmed ? const TextStyle(color: C.bad, decoration: TextDecoration.lineThrough) : null,
              decoration: InputDecoration(
                hintText: _cancelArmed
                    ? 'Let go to cancel'
                    : _listening
                        ? 'Listening… slide left to cancel'
                        : 'Ask Fasway, or hold the mic',
                hintStyle: _cancelArmed ? const TextStyle(color: C.bad, fontWeight: FontWeight.w600) : null,
                border: InputBorder.none,
                isDense: true,
              ),
            ),
          ),
          // raw pointer events: it listens from the moment of touch, with no long-press delay
          Listener(
            key: const ValueKey('agent-mic'),
            behavior: HitTestBehavior.opaque,
            onPointerDown: (e) {
              _downAt = e.position;
              _cancelArmed = false;
              _micDown();
            },
            onPointerMove: _micMove,
            onPointerUp: (_) => _micUp(),
            onPointerCancel: (_) => _micCancel(),
            child: Semantics(
              button: true,
              label: 'Hold to speak, let go to send',
              child: AnimatedScale(
                scale: _listening ? 1.22 : 1,
                duration: _listening ? Motion.fast : Motion.bounceTime,
                curve: _listening ? Motion.curve : Motion.bounce,
                child: AnimatedContainer(
                  duration: Motion.fast,
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    gradient: _listening ? const LinearGradient(colors: [Ai.pink, Ai.violet]) : null,
                    shape: BoxShape.circle,
                  ),
                  child: Icon(_listening ? Icons.mic_rounded : Icons.mic_none_rounded, color: _listening ? Colors.white : C.text),
                ),
              ),
            ),
          ),
          const SizedBox(width: 4),
          AnimatedSwitcher(
            duration: Motion.bounceTime,
            reverseDuration: Motion.fast, // the old button gets out of the way quickly
            switchInCurve: Motion.bounce,
            transitionBuilder: (child, anim) => ScaleTransition(scale: anim, child: child),
            child: trailing,
          ),
        ]),
      ),
    );
  }

  // ---- Live: the hands-free conversation, full screen ----
  Widget _live({Key? key}) {
    final phase = switch (_talkStatus) {
      'Listening…' => 'listening',
      'Working…' => 'working',
      'Speaking…' => 'speaking',
      _ => 'other',
    };
    final last = a.tasks.isEmpty ? null : a.tasks.last;
    final showScreen = widget.preview != null && widget.settings.screenOn;
    return Scaffold(
      key: key,
      backgroundColor: const Color(0xFF07080C),
      body: Stack(children: [
        const Positioned.fill(child: AuraBackground(busy: true)),
        SafeArea(
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 8, 0),
              child: Row(children: [
                const AiSparkle(size: 20, spinning: true),
                const SizedBox(width: 8),
                const GradientText('Live', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                const Spacer(),
                if (widget.preview != null) _screenToggle(),
              ]),
            ),
            if (showScreen)
              _ScreenCard(preview: widget.preview!, settings: widget.settings, busy: phase == 'working'),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 28),
                child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  AnimatedSwitcher(
                    duration: Motion.medium,
                    child: phase == 'working'
                        ? Shimmer(_talkStatus, key: const ValueKey('w'), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600))
                        : Text(_talkStatus,
                            key: ValueKey(_talkStatus), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
                  ),
                  const SizedBox(height: 14),
                  // what you're saying, then what it answered
                  AnimatedSwitcher(
                    duration: Motion.medium,
                    child: Text(
                      phase == 'listening' ? _text.text : (phase == 'speaking' && last != null ? last.reply : _text.text),
                      key: ValueKey('$phase${last?.id}'),
                      textAlign: TextAlign.center,
                      maxLines: showScreen ? 3 : 6,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 17, height: 1.35, color: phase == 'speaking' ? C.text : C.muted),
                    ),
                  ),
                ]),
              ),
            ),
            if (a.approvals.isNotEmpty) _approvals(),
            // tap the light to cut a long answer short and speak again
            Tooltip(
              message: 'Interrupt',
              child: GestureDetector(
                onTap: _interrupt,
                child: LiveOrb(phase: phase, size: !showScreen ? 190 : (widget.settings.padOpen ? 80 : 130)),
              ),
            ),
            const Text('Tap the light to interrupt · say "bas" to end', style: TextStyle(color: C.muted, fontSize: 12)),
            const SizedBox(height: 14),
            _RoundButton(
              tooltip: 'End conversation',
              icon: Icons.close_rounded,
              color: C.bad,
              size: 60,
              onTap: () => _endTalk(goodbye: 'Okay'),
            ),
            const SizedBox(height: 18),
          ]),
        ),
      ]),
    );
  }
}

extension on _AgentScreenState {
  void _openFull({bool live = false}) {
    Fx.tap();
    _endTalk();
    _speaker.stop();
    Navigator.pop(context); // the bar goes; the page comes
    widget.onOpenFull?.call(live);
  }

  /// The floating assistant: a bar over whatever screen you're on.
  Widget _bar(AgentTask? active) {
    final last = a.tasks.isEmpty ? null : a.tasks.last;
    return Container(
      key: const ValueKey('bar'),
      padding: const EdgeInsets.fromLTRB(4, 8, 4, 4),
      decoration: BoxDecoration(
        color: C.bg,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(26)),
        border: Border.all(color: Ai.violet.withValues(alpha: 0.35)),
        boxShadow: [BoxShadow(color: Ai.violet.withValues(alpha: 0.3), blurRadius: 30, spreadRadius: -6)],
      ),
      child: SafeArea(
        top: false,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            const SizedBox(width: 14),
            Flexible(child: _ModelPill(a, onTap: _pickModel)),
            const Spacer(),
            IconButton(
              tooltip: 'Open assistant',
              icon: const Icon(Icons.open_in_full_rounded, size: 20),
              onPressed: () => _openFull(),
            ),
            IconButton(
              tooltip: 'Close',
              icon: const Icon(Icons.close_rounded),
              onPressed: () => Navigator.pop(context),
            ),
          ]),
          if (a.laptopOutdated) const _Banner(color: C.bad, text: _AgentScreenState._outdatedText),
          // the newest exchange, so you can see the answer without leaving this screen
          AnimatedSize(
            duration: Motion.bounceTime,
            curve: Motion.spring,
            alignment: Alignment.bottomCenter,
            child: last == null
                ? const Padding(
                    padding: EdgeInsets.fromLTRB(18, 2, 18, 10),
                    child: GradientText('Hold the mic and ask anything about your laptop',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                  )
                : ConstrainedBox(
                    constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.3),
                    child: SingleChildScrollView(
                      reverse: true,
                      padding: const EdgeInsets.fromLTRB(14, 4, 14, 0),
                      child: Appear(key: ValueKey(last.id), child: _Exchange(task: last, onReuse: () {
                        _text.text = last.goal;
                        _text.selection = TextSelection.collapsed(offset: _text.text.length);
                      })),
                    ),
                  ),
          ),
          if (a.approvals.isNotEmpty)
            for (final x in a.approvals) _ApprovalCard(key: ValueKey(x.id), approval: x, agent: a),
          _inputPill(active),
        ]),
      ),
    );
  }
}

class _ModelPill extends StatelessWidget {
  const _ModelPill(this.a, {required this.onTap});
  final AgentController a;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final current = a.models.where((m) => m.id == a.model).firstOrNull;
    final name = (current?.label ?? 'Assistant').replaceFirst('Claude ', '');
    return Tooltip(
      message: 'Choose AI model',
      child: Pressable(
        onTap: a.models.isEmpty ? null : onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 7, 8, 7),
          decoration: BoxDecoration(color: C.panel, borderRadius: BorderRadius.circular(20), border: Border.all(color: C.panel2)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            const AiSparkle(size: 16),
            const SizedBox(width: 6),
            // between the back button and three icons on a narrow phone: shorten rather than spill over
            Flexible(
              child: Text(name,
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
            ),
            if (a.models.isNotEmpty) const Icon(Icons.expand_more_rounded, size: 20, color: C.muted),
          ]),
        ),
      ),
    );
  }
}

class _ModelRow extends StatelessWidget {
  const _ModelRow({required this.model, required this.selected, required this.onTap});
  final AgentModel model;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: Container(
          margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          decoration: BoxDecoration(
            color: selected ? Ai.violet.withValues(alpha: 0.14) : C.panel2,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: selected ? Ai.violet.withValues(alpha: 0.7) : Colors.transparent),
          ),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(model.label, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                const SizedBox(height: 2),
                Text(model.hasKey ? model.hint : '${model.hint}. Needs its API key on the laptop.',
                    style: const TextStyle(color: C.muted, fontSize: 12.5)),
              ]),
            ),
            if (selected) const Icon(Icons.check_circle_rounded, color: Ai.violet),
          ]),
        ),
      );
}

/// The laptop screen, in a card that glows while the assistant is at work on it.
class _ScreenCard extends StatelessWidget {
  const _ScreenCard({required this.preview, required this.settings, required this.busy});
  final PreviewController preview;
  final Settings settings;
  final bool busy;

  @override
  Widget build(BuildContext context) => AnimatedContainer(
        duration: Motion.slow,
        margin: const EdgeInsets.fromLTRB(12, 4, 12, 4),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          boxShadow: settings.screenOn
              ? [BoxShadow(color: Ai.blue.withValues(alpha: busy ? 0.5 : 0.18), blurRadius: busy ? 24 : 12, spreadRadius: -6)]
              : null,
        ),
        child: ScreenPreview(controller: preview, settings: settings),
      );
}

class _Banner extends StatelessWidget {
  const _Banner({required this.color, required this.text});
  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) => Appear(
        child: Container(
          width: double.infinity,
          margin: const EdgeInsets.fromLTRB(12, 0, 12, 6),
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
          decoration: BoxDecoration(color: color.withValues(alpha: 0.13), borderRadius: BorderRadius.circular(16)),
          child: Text(text, style: const TextStyle(fontSize: 13)),
        ),
      );
}

class _SuggestionCard extends StatelessWidget {
  const _SuggestionCard({required this.icon, required this.text, required this.onTap});
  final IconData icon;
  final String text;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 10, 14, 10),
          decoration: BoxDecoration(
            color: C.panel.withValues(alpha: 0.9),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: C.panel2),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            ShaderMask(
              blendMode: BlendMode.srcIn,
              shaderCallback: (r) => Ai.gradient.createShader(Offset.zero & r.size),
              child: Icon(icon, size: 18, color: Colors.white),
            ),
            const SizedBox(width: 8),
            Flexible(child: Text(text, style: const TextStyle(fontSize: 14))),
          ]),
        ),
      );
}

class _RoundButton extends StatelessWidget {
  const _RoundButton(
      {super.key, required this.tooltip, required this.icon, required this.onTap, this.color, this.gradient = false, this.size = 44});
  final String tooltip;
  final IconData icon;
  final VoidCallback onTap;
  final Color? color;
  final bool gradient;
  final double size;

  @override
  Widget build(BuildContext context) => Tooltip(
        message: tooltip,
        child: Pressable(
          onTap: onTap,
          scale: 0.85,
          child: Container(
            width: size,
            height: size,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: gradient ? null : color,
              gradient: gradient ? Ai.gradient : null,
              boxShadow: [BoxShadow(color: (color ?? Ai.violet).withValues(alpha: 0.35), blurRadius: 12, spreadRadius: -4)],
            ),
            child: Icon(icon, color: Colors.white, size: size * 0.5),
          ),
        ),
      );
}

class _ApprovalCard extends StatefulWidget {
  const _ApprovalCard({super.key, required this.approval, required this.agent});
  final AgentApproval approval;
  final AgentController agent;
  @override
  State<_ApprovalCard> createState() => _ApprovalCardState();
}

class _ApprovalCardState extends State<_ApprovalCard> {
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    _tick = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final x = widget.approval;
    final left = x.deadline.difference(DateTime.now()).inSeconds.clamp(0, 999);
    return Appear(
      child: Container(
        margin: const EdgeInsets.fromLTRB(12, 2, 12, 6),
        padding: const EdgeInsets.all(1.5), // a gradient border around the card
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(18),
          gradient: const LinearGradient(colors: [C.warn, Ai.pink]),
          boxShadow: [BoxShadow(color: C.warn.withValues(alpha: 0.25), blurRadius: 18, spreadRadius: -6)],
        ),
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 6),
          decoration: BoxDecoration(color: C.panel, borderRadius: BorderRadius.circular(16.5)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              const Icon(Icons.shield_outlined, color: C.warn, size: 18),
              const SizedBox(width: 6),
              const Expanded(child: Text('Allow this?', style: TextStyle(color: C.warn, fontWeight: FontWeight.w600))),
              Text('${left}s', style: const TextStyle(color: C.muted, fontSize: 12)),
            ]),
            const SizedBox(height: 6),
            Text(x.action, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
            if (x.why.isNotEmpty) ...[
              const SizedBox(height: 2),
              Text('Asking because ${x.why}', style: const TextStyle(color: C.muted, fontSize: 13)),
            ],
            const SizedBox(height: 10),
            Row(children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () {
                    Fx.tap();
                    widget.agent.answer(x, false);
                  },
                  child: const Text('Don\'t allow'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: FilledButton(
                  onPressed: () {
                    Fx.heavy();
                    widget.agent.answer(x, true);
                  },
                  child: const Text('Allow'),
                ),
              ),
            ]),
            TextButton(
              onPressed: () {
                Fx.heavy();
                widget.agent.answer(x, true, remember: true);
              },
              child: const Text('Allow, and don\'t ask again for this same step', style: TextStyle(fontSize: 12)),
            ),
          ]),
        ),
      ),
    );
  }
}

/// One request and its answer: yours in a bubble on the right, the assistant's beside its ✦ on the left.
class _Exchange extends StatelessWidget {
  const _Exchange({required this.task, required this.onReuse});
  final AgentTask task;
  final VoidCallback onReuse;

  static const _stateColor = {'failed': C.bad, 'over_budget': C.warn, 'stopped': C.muted};

  Widget _step(AgentStep s) {
    final (IconData icon, Color color) = switch (s.status) {
      'done' => (Icons.check_circle_rounded, C.ok),
      'failed' => (Icons.error_rounded, C.bad),
      'declined' => (Icons.block_rounded, C.warn),
      _ => (Icons.more_horiz_rounded, Ai.violet),
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 1), child: BounceIn(key: ValueKey(s.status), child: Icon(icon, size: 15, color: color))),
        const SizedBox(width: 6),
        Expanded(child: Text(s.text, style: const TextStyle(color: C.muted, fontSize: 13))),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Align(
            alignment: Alignment.centerRight,
            child: Pressable(
              onTap: onReuse,
              child: Container(
                margin: const EdgeInsets.only(left: 56, bottom: 10),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: const BoxDecoration(
                  color: C.panel2,
                  borderRadius: BorderRadius.only(
                    topLeft: Radius.circular(20),
                    topRight: Radius.circular(20),
                    bottomLeft: Radius.circular(20),
                    bottomRight: Radius.circular(6),
                  ),
                ),
                child: Text(task.goal, style: const TextStyle(fontSize: 15)),
              ),
            ),
          ),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.only(top: 2), child: AiSparkle(size: 22, spinning: task.active)),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final s in task.steps) _step(s),
                if (task.active && task.reply.isEmpty)
                  Shimmer(task.state == 'waiting_approval' ? 'Waiting for your OK…' : 'Working on it…'),
                if (task.reply.isNotEmpty)
                  Padding(
                    padding: EdgeInsets.only(top: task.steps.isEmpty ? 0 : 4),
                    child: Text(task.reply,
                        style: TextStyle(fontSize: 15.5, height: 1.35, color: _stateColor[task.state] ?? C.text)),
                  ),
                if (task.inr >= 0.01)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text('₹${task.inr.toStringAsFixed(2)}', style: const TextStyle(color: C.muted, fontSize: 11)),
                  ),
              ]),
            ),
          ]),
        ]),
      );
}
