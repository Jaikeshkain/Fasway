import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/connection.dart';
import '../core/files.dart';
import 'apps_tab.dart';
import 'common.dart';
import 'connect_screen.dart';
import 'controls_tab.dart';
import 'files_tab.dart';
import 'keyboard_tab.dart';
import 'screen_preview.dart';
import 'settings_sheet.dart';
import 'touchpad_tab.dart';
import 'voice_tab.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen(this.state, {super.key});
  final AppState state;
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  int _tab = 0;
  late PreviewController _preview;
  late FileTransfers _files;
  LinkState? _lastState;
  bool _wasWeak = false;
  String? _notified; // laptop shown in the "Send clipboard" notification
  bool _resumed = true;

  AppState get s => widget.state;
  Connection get conn => s.connection!;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _preview = PreviewController(conn, s.settings);
    _files = _newFiles();
    conn.addListener(_sync);
    s.settings.addListener(_sync);
    conn.messages.listen((m) {
      if (!mounted) return;
      if (m['t'] == 'alert' || m['t'] == 'toast') toast(context, '${m['msg']}', ms: m['t'] == 'alert' ? 5000 : 1800);
    });
    _sync();
  }

  @override
  void didUpdateWidget(HomeScreen old) {
    super.didUpdateWidget(old);
    if (old.state.connection != s.connection) {
      // re-paired with another laptop
      old.state.connection?.removeListener(_sync);
      _preview.dispose();
      _preview = PreviewController(conn, s.settings);
      _files.dispose();
      _files = _newFiles();
      conn.addListener(_sync);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    s.connection?.removeListener(_sync);
    s.settings.removeListener(_sync);
    _preview.dispose();
    _files.dispose();
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
    _preview.setActive(allowed && (_tab == 0 || _tab == 1),
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
      appBar: AppBar(
        backgroundColor: C.bg,
        titleSpacing: 16,
        title: const Text('Fasway', style: TextStyle(fontWeight: FontWeight.w700)),
        actions: [
          _StatusChip(conn),
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
            onPressed: () => showSettings(context, s, onPairNew: () {
              Fx.tap();
              Navigator.push(context, MaterialPageRoute(builder: (_) => ConnectScreen(s, canGoBack: true)));
            }),
          ),
        ],
      ),
      body: Column(children: [
        _WeakWifiBanner(conn),
        Expanded(
          child: Stack(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
              child: _TabStack(index: _tab, children: tabs),
            ),
            Positioned.fill(
              child: AnimatedSwitcher(duration: Motion.medium, child: _PairingOverlay(s, key: ValueKey(conn.state))),
            ),
          ]),
        ),
      ]),
      bottomNavigationBar: NavigationBar(
        backgroundColor: const Color(0xFF0C0E12),
        height: 64,
        labelTextStyle: const WidgetStatePropertyAll(TextStyle(fontSize: 11, fontWeight: FontWeight.w500)),
        selectedIndex: _tab,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        animationDuration: Motion.slow,
        onDestinationSelected: (i) {
          if (i != _tab) Fx.select();
          FocusScope.of(context).unfocus();
          setState(() => _tab = i);
          _sync();
        },
        destinations: [
          const NavigationDestination(icon: Icon(Icons.mouse_rounded), label: 'Touchpad'),
          const NavigationDestination(icon: Icon(Icons.keyboard_rounded), label: 'Keyboard'),
          const NavigationDestination(icon: Icon(Icons.mic_rounded), label: 'Voice'),
          const NavigationDestination(icon: Icon(Icons.apps_rounded), label: 'Apps'),
          NavigationDestination(
            icon: ListenableBuilder(
              listenable: _files,
              builder: (_, _) {
                final n = _files.active.length;
                return Badge(isLabelVisible: n > 0, label: Text('$n'), child: const Icon(Icons.swap_vert_rounded));
              },
            ),
            label: 'Files',
          ),
          const NavigationDestination(icon: Icon(Icons.tune_rounded), label: 'Controls'),
        ],
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip(this.conn);
  final Connection conn;

  @override
  Widget build(BuildContext context) {
    final (color, text) = switch (conn.state) {
      LinkState.connected => conn.weak ? (C.warn, 'Weak Wi-Fi') : (C.ok, 'Connected'),
      LinkState.connecting => (C.warn, 'Connecting…'),
      LinkState.waitingApproval => (C.warn, 'Waiting for approval'),
      LinkState.declined => (C.bad, 'Not allowed'),
      LinkState.removed => (C.bad, 'Removed'),
      LinkState.wrongLaptop => (C.bad, 'Wrong laptop'),
      LinkState.offline => (C.bad, 'Offline'),
    };
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
  const _PairingOverlay(this.s, {super.key});
  final AppState s;

  @override
  Widget build(BuildContext context) {
    final conn = s.connection!;
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
