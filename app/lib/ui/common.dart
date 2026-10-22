import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Colours shared with the web app.
class C {
  static const bg = Color(0xFF111318);
  static const panel = Color(0xFF1B1E25);
  static const panel2 = Color(0xFF242833);
  static const text = Color(0xFFE8EAF0);
  static const muted = Color(0xFF8B90A0);
  static const accent = Color(0xFF4F8CFF);
  static const ok = Color(0xFF2ECC71);
  static const bad = Color(0xFFFF5C5C);
  static const warn = Color(0xFFF5B041);
}

ThemeData faswayTheme() => ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: C.bg,
      colorScheme: const ColorScheme.dark(primary: C.accent, surface: C.panel, error: C.bad),
      useMaterial3: true,
      sliderTheme: const SliderThemeData(activeTrackColor: C.accent, thumbColor: C.accent),
    );

void haptic(bool on) {
  if (on) HapticFeedback.lightImpact();
}

/// A key-style button that never takes keyboard focus (so the phone keyboard stays open), fires on
/// press for instant feedback, and optionally auto-repeats while held (arrows, backspace...).
class KeyButton extends StatefulWidget {
  const KeyButton({
    super.key,
    required this.label,
    required this.onPress,
    this.onRelease,
    this.repeat = false,
    this.active = false,
    this.color,
    this.fontSize = 14,
    this.height = 42,
    this.flex = 1,
  });

  final String label;
  final VoidCallback onPress;
  final VoidCallback? onRelease;
  final bool repeat, active;
  final Color? color;
  final double fontSize, height;
  final int flex;

  @override
  State<KeyButton> createState() => _KeyButtonState();
}

class _KeyButtonState extends State<KeyButton> {
  Timer? _t;
  bool _down = false;

  void _start(_) {
    setState(() => _down = true);
    widget.onPress();
    if (widget.repeat) {
      _t = Timer(const Duration(milliseconds: 400), () {
        _t = Timer.periodic(const Duration(milliseconds: 70), (_) => widget.onPress());
      });
    }
  }

  void _stop(_) {
    _t?.cancel();
    _t = null;
    if (_down) widget.onRelease?.call();
    setState(() => _down = false);
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bg = widget.active ? C.accent : (widget.color ?? C.panel2);
    return Expanded(
      flex: widget.flex,
      child: Listener(
        onPointerDown: _start,
        onPointerUp: _stop,
        onPointerCancel: _stop,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 80),
          height: widget.height,
          margin: const EdgeInsets.all(3),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: _down ? Color.lerp(bg, Colors.white, 0.18) : bg,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(widget.label,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: widget.fontSize, color: C.text)),
        ),
      ),
    );
  }
}

/// Rounded panel with an optional title row (like the web app's cards).
class Panel extends StatelessWidget {
  const Panel({super.key, this.title, this.trailing, required this.child});
  final String? title;
  final Widget? trailing;
  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
        decoration: BoxDecoration(color: C.panel, borderRadius: BorderRadius.circular(16)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (title != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Row(children: [
                Expanded(
                    child: Text(title!,
                        style: const TextStyle(color: C.muted, fontWeight: FontWeight.w600, fontSize: 14))),
                if (trailing != null) trailing!,
              ]),
            ),
          child,
        ]),
      );
}

void toast(BuildContext context, String msg, {int ms = 1800}) {
  final m = ScaffoldMessenger.maybeOf(context);
  m?.hideCurrentSnackBar();
  m?.showSnackBar(SnackBar(
    content: Text(msg),
    duration: Duration(milliseconds: ms),
    behavior: SnackBarBehavior.floating,
    backgroundColor: const Color(0xFF2B3140),
  ));
}

Future<bool> confirm(BuildContext context, String title, String body, {String ok = 'OK', bool danger = false}) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      backgroundColor: C.panel,
      title: Text(title),
      content: Text(body),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
        FilledButton(
          style: danger ? FilledButton.styleFrom(backgroundColor: C.bad) : null,
          onPressed: () => Navigator.pop(c, true),
          child: Text(ok),
        ),
      ],
    ),
  );
  return r ?? false;
}
