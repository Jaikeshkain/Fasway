import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/connection.dart';
import 'apps_tab.dart';
import 'common.dart';
import 'connect_screen.dart';
import 'controls_tab.dart';
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
  bool _resumed = true;

  AppState get s => widget.state;
  Connection get conn => s.connection!;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _preview = PreviewController(conn, s.settings);
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
      conn.addListener(_sync);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    s.connection?.removeListener(_sync);
    s.settings.removeListener(_sync);
    _preview.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState st) {
    _resumed = st == AppLifecycleState.resumed;
    if (_resumed && !conn.isConnected) conn.reconnectNow(); // back from the home screen
    _sync();
  }

  /// The screen preview runs only while it is switched on, visible and connected (saves battery).
  void _sync() {
    if (!mounted) return;
    final want = s.settings.screenOn && _resumed && conn.isConnected && (_tab == 0 || _tab == 1);
    _preview.setActive(want);
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final tabs = [
      TouchpadTab(conn: conn, settings: s.settings, preview: _preview),
      KeyboardTab(conn: conn, settings: s.settings, preview: _preview),
      VoiceTab(conn: conn, settings: s.settings),
      AppsTab(conn: conn, settings: s.settings, active: _tab == 3),
      ControlsTab(conn: conn, settings: s.settings, active: _tab == 4),
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
            icon: Icon(Icons.desktop_windows_rounded, color: s.settings.screenOn ? C.accent : C.muted),
            onPressed: () => s.settings.set('screenOn', !s.settings.screenOn),
          ),
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_rounded),
            onPressed: () => showSettings(context, s, onPairNew: () {
              Navigator.push(context, MaterialPageRoute(builder: (_) => ConnectScreen(s, canGoBack: true)));
            }),
          ),
        ],
      ),
      body: Stack(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          child: IndexedStack(index: _tab, children: tabs),
        ),
        _PairingOverlay(s),
      ]),
      bottomNavigationBar: NavigationBar(
        backgroundColor: const Color(0xFF0C0E12),
        height: 64,
        selectedIndex: _tab,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        onDestinationSelected: (i) {
          FocusScope.of(context).unfocus();
          setState(() => _tab = i);
          _sync();
        },
        destinations: const [
          NavigationDestination(icon: Icon(Icons.mouse_rounded), label: 'Touchpad'),
          NavigationDestination(icon: Icon(Icons.keyboard_rounded), label: 'Keyboard'),
          NavigationDestination(icon: Icon(Icons.mic_rounded), label: 'Voice'),
          NavigationDestination(icon: Icon(Icons.apps_rounded), label: 'Apps'),
          NavigationDestination(icon: Icon(Icons.tune_rounded), label: 'Controls'),
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
      LinkState.connected => (C.ok, 'Connected'),
      LinkState.connecting => (C.warn, 'Connecting…'),
      LinkState.waitingApproval => (C.warn, 'Waiting for approval'),
      LinkState.declined => (C.bad, 'Not allowed'),
      LinkState.removed => (C.bad, 'Removed'),
      LinkState.wrongLaptop => (C.bad, 'Wrong laptop'),
      LinkState.offline => (C.bad, 'Offline'),
    };
    return GestureDetector(
      onTap: conn.isConnected ? null : conn.reconnectNow,
      child: Row(children: [
        Container(width: 9, height: 9, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 6),
        Text(text, style: const TextStyle(color: C.muted, fontSize: 13)),
        const SizedBox(width: 4),
      ]),
    );
  }
}

/// Full-screen messages for pairing: waiting for approval, declined, removed, wrong laptop.
class _PairingOverlay extends StatelessWidget {
  const _PairingOverlay(this.s);
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
    return Positioned.fill(
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
