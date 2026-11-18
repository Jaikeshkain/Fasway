import 'dart:async';

import 'package:flutter/material.dart';

import '../core/agent.dart';
import '../core/app_state.dart';
import '../core/connection.dart';
import '../core/files.dart';
import '../core/wake.dart';
import 'agent_screen.dart';
import 'ai_effects.dart';
import 'floating_assistant.dart';
import 'whats_new.dart';
import 'apps_tab.dart';
import 'common.dart';
import 'connect_screen.dart';
import 'controls_tab.dart';
import 'files_tab.dart';
import 'keyboard_tab.dart';
import 'laptops_sheet.dart';
import 'screen_preview.dart';
import 'settings_sheet.dart';
import 'touchpad_tab.dart';
import 'voice_tab.dart';

/// Everything for one connection to one laptop. Switching laptops builds a new one (see main.dart);
/// the old one still shows while it fades out, on its closed connection.
class HomeScreen extends StatefulWidget {
  const HomeScreen(this.state, {super.key});
  final AppState state;
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  late final Connection conn;
  late PreviewController _preview;
  late FileTransfers _files;
  late AgentController _agent;
  bool _agentOpen = false;
  LinkState? _lastState;
  bool _wasWeak = false;
  String? _notified; // laptop shown in the "Send clipboard" notification
  bool _resumed = true;

  AppState get s => widget.state;
  int get _tab => s.tab;
  set _tab(int i) => s.tab = i;

  @override
  void initState() {
    super.initState();
    conn = s.connection!;
    WidgetsBinding.instance.addObserver(this);
    _preview = PreviewController(conn, s.settings);
    _files = _newFiles();
    _agent = _newAgent();
    conn.addListener(_sync);
    s.settings.addListener(_sync);
    conn.messages.listen((m) {
      if (!mounted) return;
      if (m['t'] == 'alert' || m['t'] == 'toast') toast(context, '${m['msg']}', ms: m['t'] == 'alert' ? 5000 : 1800);
    });
    _sync();
    // once after each update: show what's new, so new features get found (not in dev builds and tests)
    if (appVersion != 'dev' && s.settings.whatsNewSeen != appVersion) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        s.settings.set('whatsNewSeen', appVersion);
        showWhatsNew(
          context,
          onAssistant: _openAgent,
          onLive: () => _openAgent(live: true),
          onScreen: () {
            s.settings.set('screenOn', true);
            setState(() => _tab = 1); // the Keyboard tab: the screen, with room for its touchpad below
            _sync();
          },
        );
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    conn.removeListener(_sync);
    s.settings.removeListener(_sync);
    _preview.dispose();
    _files.dispose();
    _agent.dispose();
    Connection.agentNotification(null); // an approval from the laptop we just left can't be answered
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState st) {
    // inactive = still on screen but lost focus (notification shade, a dialog on top): keep streaming
    _resumed = st == AppLifecycleState.resumed || st == AppLifecycleState.inactive;
    if (st == AppLifecycleState.resumed && !conn.isConnected) conn.reconnectNow(); // back from the home screen
    _sync();
  }

  FileTransfers _newFiles() => FileTransfers(conn)
    ..onNotice = (text) {
      if (mounted) toast(context, text);
    }
    ..onFinished = (t) => t.state == TransferState.done ? Fx.success() : Fx.heavy();

  /// Leaving this laptop ends its file transfers: ask first.
  Future<bool> _canLeave() async {
    final n = _files.active.length;
    return n == 0 ||
        await confirm(context, 'Stop file transfers?',
            'Switching laptops stops ${n == 1 ? 'the transfer' : 'the $n transfers'} still running on ${conn.laptop.name}.',
            ok: 'Switch', danger: true);
  }

  Future<void> _addLaptop() async {
    Fx.tap();
    if (!await _canLeave() || !mounted) return;
    Navigator.push(context, MaterialPageRoute(builder: (_) => ConnectScreen(s, canGoBack: true)));
  }

  AgentController _newAgent() {
    final c = conn;
    final agent = AgentController(
        messages: c.messages, send: c.send, connected: () => c.isConnected, link: c, deviceId: c.identity.id);
    agent.onApprovalChanged = (a) {
      if (a == null) {
        Connection.agentNotification(null);
        return;
      }
      Fx.heavy();
      // another app is on screen: the card on the assistant screen can't be seen from there
      if (WidgetsBinding.instance.lifecycleState != AppLifecycleState.resumed) Connection.agentNotification(a.action);
    };
    agent.addListener(() {
      if (mounted) setState(() {}); // the badge on the assistant button
    });
    return agent;
  }

  Widget _filesIcon() => ListenableBuilder(
        listenable: _files,
        builder: (_, _) {
          final n = _files.active.length;
          return Badge(isLabelVisible: n > 0, label: Text('$n'), child: const Icon(Icons.swap_vert_rounded));
        },
      );

  Future<void> _openAgent({bool live = false}) async {
    Fx.tap();
    _agentOpen = true; // the assistant shows the laptop screen too
    _sync();
    await Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => AgentScreen(agent: _agent, settings: s.settings, preview: _preview, startLive: live)));
    _agentOpen = false;
    _sync();
  }

  /// The floating bubble: the assistant's voice bar over whatever tab is showing.
  void _openAssistantBar() {
    Fx.tap();
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      enableDrag: false, // sliding up on the held mic cancels a recording: the sheet must not move then
      isDismissible: false, // a tap beside it doesn't close it: only its ✕ (or Back) does
      backgroundColor: Colors.transparent,
      barrierColor: Colors.black38,
      builder: (c) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(c).bottom), // above the keyboard
        child: AgentScreen(
          agent: _agent,
          settings: s.settings,
          compact: true,
          onOpenFull: (live) => _openAgent(live: live),
        ),
      ),
    );
  }

  /// The screen preview runs only while it is switched on, visible and connected (saves battery).
  void _sync() {
    if (!mounted) return;
    if (conn.state != _lastState) {
      if (conn.state == LinkState.connected && _lastState != null) Fx.success(); // back online
      _lastState = conn.state;
    }
    // "Send clipboard" notification: on once connected (if enabled), off when switched off
    final notify = s.settings.clipNotify && conn.isConnected;
    if ((notify && _notified != conn.laptop.name) || (!s.settings.clipNotify && _notified != null)) {
      _notified = s.settings.clipNotify ? conn.laptop.name : null;
      Connection.clipNotification(s.settings.clipNotify, conn.laptop.name);
    }
    if (conn.weak != _wasWeak) {
      _wasWeak = conn.weak;
      if (conn.weak) Fx.heavy(); // the banner appears: make it noticed
    }
    final allowed = s.settings.screenOn && _resumed && conn.isConnected;
    // on another tab the stream keeps running for a while: coming back shows the picture at once
    _preview.setActive(allowed && (_tab == 0 || _tab == 1 || _agentOpen),
        linger: allowed ? const Duration(seconds: 20) : Duration.zero);
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final tabs = [
      TouchpadTab(conn: conn, settings: s.settings, preview: _preview),
      KeyboardTab(conn: conn, settings: s.settings, preview: _preview),
      VoiceTab(conn: conn, settings: s.settings),
      AppsTab(conn: conn, settings: s.settings, active: _tab == 3),
      FilesTab(conn: conn, files: _files),
      ControlsTab(conn: conn, settings: s.settings, active: _tab == 5),
    ];
    return Scaffold(
      backgroundColor: C.bg,
      extendBody: true, // the tab bar floats over the page
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        titleSpacing: 16,
        title: Pressable(
          onTap: () => showLaptops(context, s, canLeave: _canLeave, onAdd: _addLaptop),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            const GradientText('FASWAY',
                style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: 2.6, height: 1.1)),
            Row(mainAxisSize: MainAxisSize.min, children: [
              Flexible(
                child: Text(conn.laptop.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    semanticsLabel: 'Laptop: ${conn.laptop.name}. Tap to switch',
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 19, height: 1.2)),
              ),
              const Icon(Icons.expand_more_rounded, color: C.muted),
            ]),
          ]),
        ),
        actions: [
          _StatusChip(conn),
          IconButton(
            tooltip: 'Assistant',
            icon: Badge(
              isLabelVisible: _agent.approvals.isNotEmpty,
              label: Text('${_agent.approvals.length}'),
              backgroundColor: C.warn,
              child: const AiSparkle(size: 24),
            ),
            onPressed: _openAgent,
          ),
          IconButton(
            tooltip: 'Laptop screen',
            icon: AnimatedScale(
              scale: s.settings.screenOn ? 1.08 : 1,
              duration: Motion.medium,
              curve: Motion.spring,
              child: TweenAnimationBuilder<Color?>(
                tween: ColorTween(end: s.settings.screenOn ? C.accent : C.muted),
                duration: Motion.medium,
                builder: (_, c, _) => Icon(Icons.desktop_windows_rounded, color: c),
              ),
            ),
            onPressed: () {
              Fx.select();
              s.settings.set('screenOn', !s.settings.screenOn);
            },
          ),
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_rounded),
            onPressed: () => showSettings(context, s, onPairNew: _addLaptop),
          ),
        ],
      ),
      body: Stack(children: [
        // the same drifting light as the assistant: one look across the app
        const Positioned.fill(child: AuraBackground()),
        Column(children: [
        _WeakWifiBanner(conn),
        _OfflineBanner(conn),
        Expanded(
          child: Stack(children: [
            Padding(
              // room at the bottom for the floating tab bar
              padding: EdgeInsets.fromLTRB(12, 0, 12, _GlassNav.height + 18 + MediaQuery.paddingOf(context).bottom),
              child: _TabStack(index: _tab, children: tabs),
            ),
            // the assistant, one tap away on every tab (under the pairing overlay, which covers it)
            Positioned.fill(
              child: Padding(
                padding: EdgeInsets.only(bottom: _GlassNav.height + 14 + MediaQuery.paddingOf(context).bottom),
                child: ListenableBuilder(
                  listenable: s.settings,
                  builder: (_, _) => FloatingAssistant(agent: _agent, settings: s.settings, onTap: _openAssistantBar),
                ),
              ),
            ),
            Positioned.fill(
              child: AnimatedSwitcher(duration: Motion.medium, child: _PairingOverlay(s, conn, key: ValueKey(conn.state))),
            ),
          ]),
        ),
      ]),
      ]),
      bottomNavigationBar: _GlassNav(
        index: _tab,
        items: [
          (const Icon(Icons.mouse_rounded), 'Touchpad'),
          (const Icon(Icons.keyboard_rounded), 'Keyboard'),
          (const Icon(Icons.mic_rounded), 'Voice'),
          (const Icon(Icons.apps_rounded), 'Apps'),
          (_filesIcon(), 'Files'),
          (const Icon(Icons.tune_rounded), 'Controls'),
        ],
        onSelect: (i) {
          if (i != _tab) Fx.select();
          FocusScope.of(context).unfocus();
          setState(() => _tab = i);
          _sync();
        },
      ),
    );
  }
}

/// The tab bar: a glass pill floating above the page. A gradient light slides to the tab you pick, and its
/// icon pops in with a bounce.
class _GlassNav extends StatelessWidget {
  const _GlassNav({required this.index, required this.items, required this.onSelect});
  final int index;
  final List<(Widget, String)> items;
  final void Function(int) onSelect;

  static const height = 64.0;

  @override
  Widget build(BuildContext context) => SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
          child: Container(
            height: height,
            padding: const EdgeInsets.all(1),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(26),
              gradient: LinearGradient(colors: [
                Colors.white.withValues(alpha: 0.12),
                Ai.violet.withValues(alpha: 0.25),
                Ai.blue.withValues(alpha: 0.2),
              ]),
              boxShadow: [
                BoxShadow(color: Colors.black.withValues(alpha: 0.5), blurRadius: 24, offset: const Offset(0, 8)),
                BoxShadow(color: Ai.violet.withValues(alpha: 0.15), blurRadius: 30, spreadRadius: -8),
              ],
            ),
            child: Container(
              decoration: BoxDecoration(color: const Color(0xF0121419), borderRadius: BorderRadius.circular(25)),
              child: LayoutBuilder(builder: (context, box) {
                final w = box.maxWidth / items.length;
                return Stack(children: [
                  // the light behind the selected tab, sliding with a bounce
                  AnimatedPositioned(
                    duration: Motion.bounceTime,
                    curve: Motion.spring,
                    left: index * w + 6,
                    top: 6,
                    width: w - 12,
                    height: height - 14,
                    child: Container(
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(18),
                        gradient: LinearGradient(colors: [
                          Ai.blue.withValues(alpha: 0.28),
                          Ai.violet.withValues(alpha: 0.28),
                        ]),
                        border: Border.all(color: Ai.violet.withValues(alpha: 0.45)),
                      ),
                    ),
                  ),
                  Row(children: [
                    for (final (i, (icon, label)) in items.indexed)
                      Expanded(
                        child: Semantics(
                          button: true,
                          selected: i == index,
                          child: Pressable(
                            onTap: () => onSelect(i),
                            haptics: false,
                            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                              i == index
                                  ? BounceIn(
                                      child: ShaderMask(
                                        blendMode: BlendMode.srcIn,
                                        shaderCallback: (r) => Ai.gradient.createShader(Offset.zero & r.size),
                                        child: IconTheme(data: const IconThemeData(color: Colors.white, size: 24), child: icon),
                                      ),
                                    )
                                  : IconTheme(data: const IconThemeData(color: C.muted, size: 22), child: icon),
                              const SizedBox(height: 3),
                              Text(label,
                                  maxLines: 1,
                                  overflow: TextOverflow.fade,
                                  softWrap: false,
                                  style: TextStyle(
                                    fontSize: 10.5,
                                    fontWeight: i == index ? FontWeight.w700 : FontWeight.w500,
                                    color: i == index ? C.text : C.muted,
                                  )),
                            ]),
                          ),
                        ),
                      ),
                  ]),
                ]);
              }),
            ),
          ),
        ),
      );
}

class _StatusChip extends StatelessWidget {
  const _StatusChip(this.conn);
  final Connection conn;

  @override
  Widget build(BuildContext context) {
    final (color, text) = linkStatus(conn);
    final busy = conn.state == LinkState.connecting || conn.state == LinkState.waitingApproval;
    return Pressable(
      onTap: conn.isConnected ? null : conn.reconnectNow,
      haptics: !conn.isConnected,
      child: AnimatedContainer(
        duration: Motion.medium,
        curve: Motion.curve,
        padding: const EdgeInsets.fromLTRB(9, 5, 11, 5),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(20)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          _Dot(color: color, pulsing: busy),
          const SizedBox(width: 7),
          AnimatedSwitcher(
            duration: Motion.medium,
            transitionBuilder: (c, a) => FadeTransition(
              opacity: a,
              child: SlideTransition(position: Tween(begin: const Offset(0, 0.4), end: Offset.zero).animate(a), child: c),
            ),
            child: Text(text, key: ValueKey(text), style: const TextStyle(color: C.text, fontSize: 12.5)),
          ),
        ]),
      ),
    );
  }
}

/// Amber bar under the title while the Wi-Fi between phone and laptop is weak.
class _WeakWifiBanner extends StatelessWidget {
  const _WeakWifiBanner(this.conn);
  final Connection conn;

  @override
  Widget build(BuildContext context) {
    final show = conn.isConnected && conn.weak;
    final rtt = conn.rttMs;
    return AnimatedSize(
      duration: Motion.medium,
      curve: Motion.curve,
      alignment: Alignment.topCenter,
      child: !show
          ? const SizedBox(width: double.infinity)
          : Container(
              width: double.infinity,
              margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
              decoration: BoxDecoration(
                color: C.warn.withValues(alpha: 0.14),
                border: Border.all(color: C.warn.withValues(alpha: 0.5)),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(children: [
                const Icon(Icons.network_wifi_1_bar_rounded, color: C.warn),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(
                      rtt == null || rtt >= 3000 ? 'Weak Wi-Fi: messages are getting lost' : 'Weak Wi-Fi: slow connection ($rtt ms)',
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
                    ),
                    const SizedBox(height: 2),
                    const Text(
                      'Move closer to your Wi-Fi router (or move the laptop closer). Controls may lag until it improves.',
                      style: TextStyle(color: C.muted, fontSize: 12),
                    ),
                  ]),
                ),
              ]),
            ),
    );
  }
}

/// After a few seconds without the laptop: "Laptop not reachable", with Wake laptop (Wake-on-LAN) once
/// the phone knows the laptop's network card.
class _OfflineBanner extends StatefulWidget {
  const _OfflineBanner(this.conn);
  final Connection conn;
  @override
  State<_OfflineBanner> createState() => _OfflineBannerState();
}

class _OfflineBannerState extends State<_OfflineBanner> {
  Timer? _delay;
  bool _show = false, _sending = false;

  Connection get conn => widget.conn;
  bool get _away => conn.state == LinkState.offline || conn.state == LinkState.connecting;

  @override
  void initState() {
    super.initState();
    conn.addListener(_onState);
    _onState();
  }

  @override
  void dispose() {
    conn.removeListener(_onState);
    _delay?.cancel();
    super.dispose();
  }

  void _onState() {
    if (!_away) {
      _delay?.cancel();
      _delay = null;
      if (_show && mounted) setState(() => _show = false);
    } else if (!_show && _delay == null) {
      // reconnects after a Wi-Fi blip take a second or two: only a real absence gets the banner
      _delay = Timer(const Duration(seconds: 6), () {
        _delay = null;
        if (mounted && _away) setState(() => _show = true);
      });
    }
  }

  Future<void> _wake() async {
    Fx.heavy();
    setState(() => _sending = true);
    final ok = await Wake.send(conn.laptop);
    if (!mounted) return;
    setState(() => _sending = false);
    toast(context, ok ? 'Wake-up sent. It can take 10–20 seconds…' : 'Connect to this laptop once first', ms: 3500);
    conn.reconnectNow();
  }

  @override
  Widget build(BuildContext context) {
    final canWake = Wake.canWake(conn.laptop);
    return AnimatedSize(
      duration: Motion.medium,
      curve: Motion.curve,
      alignment: Alignment.topCenter,
      child: !_show
          ? const SizedBox(width: double.infinity)
          : Container(
              width: double.infinity,
              margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
              padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
              decoration: BoxDecoration(
                color: C.panel2,
                border: Border.all(color: C.bad.withValues(alpha: 0.45)),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(children: [
                const Icon(Icons.bedtime_rounded, color: C.muted),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('${conn.laptop.name} isn\'t reachable', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
                    const SizedBox(height: 2),
                    Text(
                      canWake
                          ? 'Asleep, or on another Wi-Fi? Wake it from here.'
                          : 'Is it on and on the same Wi-Fi as this phone?',
                      style: const TextStyle(color: C.muted, fontSize: 12),
                    ),
                  ]),
                ),
                if (canWake)
                  FilledButton.tonal(
                    onPressed: _sending ? null : _wake,
                    child: Text(_sending ? 'Waking…' : 'Wake laptop'),
                  ),
              ]),
            ),
    );
  }
}

/// Status dot; breathes while connecting.
class _Dot extends StatefulWidget {
  const _Dot({required this.color, required this.pulsing});
  final Color color;
  final bool pulsing;
  @override
  State<_Dot> createState() => _DotState();
}

class _DotState extends State<_Dot> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 900));

  @override
  void initState() {
    super.initState();
    if (widget.pulsing) _c.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(_Dot old) {
    super.didUpdateWidget(old);
    if (widget.pulsing && !_c.isAnimating) _c.repeat(reverse: true);
    if (!widget.pulsing && _c.isAnimating) _c.animateTo(0, duration: Motion.medium);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (_, _) => TweenAnimationBuilder<Color?>(
          tween: ColorTween(end: widget.color),
          duration: Motion.medium,
          builder: (_, c, _) => Container(
            width: 9,
            height: 9,
            decoration: BoxDecoration(color: c, shape: BoxShape.circle, boxShadow: [
              BoxShadow(color: (c ?? widget.color).withValues(alpha: 0.6 * _c.value + 0.25), blurRadius: 4 + 6 * _c.value),
            ]),
          ),
        ),
      );
}

/// IndexedStack (every tab keeps its state) whose newly selected tab fades and slides in from the
/// side it was picked on.
class _TabStack extends StatefulWidget {
  const _TabStack({required this.index, required this.children});
  final int index;
  final List<Widget> children;
  @override
  State<_TabStack> createState() => _TabStackState();
}

class _TabStackState extends State<_TabStack> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: Motion.medium, value: 1);
  late final _a = CurvedAnimation(parent: _c, curve: Motion.curve);
  double _dir = 1;

  @override
  void didUpdateWidget(_TabStack old) {
    super.didUpdateWidget(old);
    if (old.index != widget.index) {
      _dir = widget.index > old.index ? 1 : -1;
      _c.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => IndexedStack(index: widget.index, children: [
        // same wrappers for every tab at all times, so switching never rebuilds a tab from scratch
        for (var i = 0; i < widget.children.length; i++)
          FadeTransition(
            opacity: i == widget.index ? _a : kAlwaysCompleteAnimation,
            child: SlideTransition(
              position: i == widget.index
                  ? Tween(begin: Offset(0.05 * _dir, 0), end: Offset.zero).animate(_a)
                  : const AlwaysStoppedAnimation(Offset.zero),
              child: widget.children[i],
            ),
          ),
      ]);
}
/// Full-screen messages for pairing: waiting for approval, declined, removed, wrong laptop.
class _PairingOverlay extends StatelessWidget {
  const _PairingOverlay(this.s, this.conn, {super.key});
  final AppState s;
  final Connection conn;

  @override
  Widget build(BuildContext context) {
    final info = switch (conn.state) {
      LinkState.waitingApproval => (
          '💻',
          'Approve this phone on your laptop',
          'A window opened on the laptop. Click Allow there to finish pairing.',
          false
        ),
      LinkState.declined => ('🚫', 'Not allowed', 'The laptop declined this phone (or nobody answered in time).', true),
      LinkState.removed => (
          '🔓',
          'Pair again',
          'This phone is not trusted by the laptop (it was removed, or a new pairing code was made). '
              'Scan the QR code in the Fasway window.',
          false
        ),
      LinkState.wrongLaptop => (
          '⚠️',
          'Different laptop',
          'Something answered on the laptop\'s address, but its security certificate does not match the one '
              'from the QR code. Scan the QR code again if you reinstalled Fasway.',
          true
        ),
      _ => null,
    };
    if (info == null) return const SizedBox.shrink();
    return SizedBox.expand(
      child: Container(
        color: C.bg,
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Text(info.$1, style: const TextStyle(fontSize: 56)),
          const SizedBox(height: 12),
          Text(info.$2, textAlign: TextAlign.center, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          Text(info.$3, textAlign: TextAlign.center, style: const TextStyle(color: C.muted, height: 1.5)),
          const SizedBox(height: 20),
          if (info.$4) FilledButton(onPressed: conn.reconnectNow, child: const Text('Try again')),
          TextButton(
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ConnectScreen(s, canGoBack: true))),
            child: const Text('Scan QR code'),
          ),
        ]),
      ),
    );
  }
}
