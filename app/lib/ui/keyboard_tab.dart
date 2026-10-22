import 'package:flutter/material.dart';

import '../core/connection.dart';
import '../core/settings.dart';
import 'common.dart';
import 'live_typing.dart';
import 'screen_preview.dart';

/// Live keyboard: typing appears on the laptop as you type, plus special keys and modifiers.
/// Modifiers: tap once = next key only, tap twice = locked, again = off.
class KeyboardTab extends StatefulWidget {
  const KeyboardTab({super.key, required this.conn, required this.settings, required this.preview});
  final Connection conn;
  final Settings settings;
  final PreviewController preview;
  @override
  State<KeyboardTab> createState() => _KeyboardTabState();
}

class _KeyboardTabState extends State<KeyboardTab> {
  final _focus = FocusNode();
  final _field = GlobalKey<LiveTypingFieldState>();
  final _mods = {'ctrl': 0, 'alt': 0, 'shift': 0, 'win': 0}; // 0 off, 1 once, 2 locked

  Connection get conn => widget.conn;

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  String get _prefix => ['ctrl', 'alt', 'shift', 'win'].where((m) => _mods[m]! > 0).map((m) => '$m+').join();

  void _releaseOnce() => setState(() => _mods.updateAll((_, v) => v == 1 ? 0 : v));

  void _sendKey(String k) {
    conn.send({'t': 'key', 'k': '$_prefix$k'});
    _releaseOnce();
  }

  bool _onCombo(String chars) {
    if (_mods['ctrl']! == 0 && _mods['alt']! == 0 && _mods['win']! == 0) {
      if (_mods['shift'] == 1) _releaseOnce(); // shift is applied by the phone keyboard itself
      return false;
    }
    for (final ch in chars.runes) {
      final s = String.fromCharCode(ch);
      _sendKey(s == ' ' ? 'space' : s.toLowerCase());
    }
    return true;
  }

  Widget _key(String label, String k, {bool repeat = false, double fs = 14}) => KeyButton(
        label: label,
        repeat: repeat,
        fontSize: fs,
        onPress: () {
          haptic(widget.settings.haptics);
          if (k == 'backspace' || k == 'delete') _field.currentState?.reset(); // field no longer mirrors the laptop
          _sendKey(k);
        },
      );

  Widget _mod(String m, String label) => KeyButton(
        label: label + (_mods[m] == 2 ? ' 🔒' : ''),
        active: _mods[m]! > 0,
        onPress: () {
          haptic(widget.settings.haptics);
          setState(() => _mods[m] = (_mods[m]! + 1) % 3);
        },
      );

  Widget _scrollRow(List<Widget> keys) => SizedBox(
        height: 48,
        child: ListView(scrollDirection: Axis.horizontal, children: [
          for (final k in keys) SizedBox(width: 74, child: Row(children: [k])),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final mac = conn.laptopOs == 'mac';
    // scrollable: with the phone keyboard up there is little height left
    return SingleChildScrollView(child: Column(children: [
      ScreenPreview(controller: widget.preview, settings: widget.settings),
      LiveTypingField(
        key: _field,
        conn: conn,
        focusNode: _focus,
        onCombo: _onCombo,
        onSpecialKey: _sendKey,
        decoration: InputDecoration(
          hintText: 'Tap here – typing goes live to the laptop',
          filled: true,
          fillColor: C.panel,
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
        ),
      ),
      const SizedBox(height: 6),
      Row(children: [
        _mod('ctrl', 'Ctrl'),
        _mod('alt', mac ? '⌥ Opt' : 'Alt'),
        _mod('shift', 'Shift'),
        _mod('win', mac ? '⌘ Cmd' : '⊞ Win'),
        _key('Esc', 'escape'),
        _key('Tab', 'tab'),
      ]),
      Row(children: [
        _key('←', 'left', repeat: true, fs: 18),
        _key('↑', 'up', repeat: true, fs: 18),
        _key('↓', 'down', repeat: true, fs: 18),
        _key('→', 'right', repeat: true, fs: 18),
        _key('⌫', 'backspace', repeat: true, fs: 18),
        _key('Del', 'delete', repeat: true),
      ]),
      _scrollRow([
        _key('Home', 'home'),
        _key('End', 'end'),
        _key('PgUp', 'pageup', repeat: true),
        _key('PgDn', 'pagedown', repeat: true),
        _key('Enter ⏎', 'enter'),
        for (var i = 1; i <= 12; i++) _key('F$i', 'f$i'),
        _key('Ins', 'insert'),
        _key('PrtSc', 'printscreen'),
      ]),
      _scrollRow([
        for (final (l, k) in [
          ('Copy', 'mod+c'),
          ('Paste', 'mod+v'),
          ('Cut', 'mod+x'),
          ('Undo', 'mod+z'),
          ('Redo', 'mod+y'),
          ('Select all', 'mod+a'),
          ('Save', 'mod+s'),
          ('Find', 'mod+f'),
        ])
          KeyButton(
            label: l,
            fontSize: 13,
            color: const Color(0xFF1F2A40),
            onPress: () {
              haptic(widget.settings.haptics);
              conn.send({'t': 'key', 'k': k});
            },
          ),
      ]),
    ]));
  }
}
