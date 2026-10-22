import 'dart:async';

import 'package:flutter/gestures.dart' show kTouchSlop;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Set by tool/build_apk.ps1 (--dart-define), shown in Settings.
const appVersion = String.fromEnvironment('FASWAY_VERSION', defaultValue: 'dev');
const appBuild = String.fromEnvironment('FASWAY_BUILD', defaultValue: '0');

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

/// Motion: one set of durations and curves so everything moves the same way.
class Motion {
  static const fast = Duration(milliseconds: 120);
  static const medium = Duration(milliseconds: 240);
  static const slow = Duration(milliseconds: 380);
  static const curve = Curves.easeOutCubic;
  static const spring = Curves.easeOutBack;
}

ThemeData faswayTheme() => ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: C.bg,
      colorScheme: const ColorScheme.dark(primary: C.accent, surface: C.panel, error: C.bad),
      useMaterial3: true,
      splashFactory: InkSparkle.splashFactory, // Android's sparkle ripple on every tappable
      sliderTheme: const SliderThemeData(activeTrackColor: C.accent, thumbColor: C.accent),
      pageTransitionsTheme: const PageTransitionsTheme(builders: {
        // pages slide and fade like Android 15 (and follow the predictive back gesture)
        TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
      }),
      navigationBarTheme: NavigationBarThemeData(
        indicatorColor: C.accent.withValues(alpha: 0.22),
        indicatorShape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        iconTheme: WidgetStateProperty.resolveWith(
            (s) => IconThemeData(color: s.contains(WidgetState.selected) ? C.accent : C.muted)),
      ),
      snackBarTheme: SnackBarThemeData(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        insetPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      ),
      dialogTheme: DialogThemeData(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22))),
    );

/// Haptic feedback, following the Vibration setting. Two calls within a few ms (a button that
/// vibrates plus the action it runs) give one buzz.
class Fx {
  static bool enabled = true;
  static DateTime _last = DateTime(0);

  static void _go(Future<void> Function() f) {
    final now = DateTime.now();
    if (!enabled || now.difference(_last).inMilliseconds < 40) return;
    _last = now;
    f();
  }

  static void tap() => _go(HapticFeedback.lightImpact); // buttons, keys, clicks
  static void select() => _go(HapticFeedback.selectionClick); // tabs, switches, pickers
  static void press() => _go(HapticFeedback.mediumImpact); // long press, start dragging
  static void heavy() => _go(HapticFeedback.heavyImpact); // important / destructive actions
  static void success() {
    // two short ticks: a transfer finished, something was sent
    _go(HapticFeedback.lightImpact);
    Future.delayed(const Duration(milliseconds: 90), () {
      if (enabled) HapticFeedback.lightImpact();
    });
  }
}

void haptic(bool on) {
  if (on) Fx.tap();
}

/// Fades and slides its child in the first time it is shown (list items, cards).
class Appear extends StatelessWidget {
  const Appear({super.key, required this.child, this.delay = Duration.zero, this.offset = 14});
  final Widget child;
  final Duration delay;
  final double offset;

  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: 1),
        duration: Motion.slow + delay,
        curve: Interval(delay.inMilliseconds / (Motion.slow + delay).inMilliseconds, 1, curve: Motion.curve),
        builder: (context, v, child) => Opacity(
          opacity: v,
          child: Transform.translate(offset: Offset(0, (1 - v) * offset), child: child),
        ),
        child: child,
      );
}

/// Shrinks a little while pressed and springs back: the touch feel of every custom tappable.
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.onTap, this.scale = 0.96, this.haptics = true});
  final Widget child;
  final VoidCallback? onTap;
  final double scale;
  final bool haptics;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;
  Offset _from = Offset.zero;

  void _set(bool v) {
    if (_down != v) setState(() => _down = v);
  }

  @override
  Widget build(BuildContext context) {
    Widget child = AnimatedScale(
      scale: _down ? widget.scale : 1,
      duration: _down ? Motion.fast : Motion.medium,
      curve: _down ? Curves.easeOut : Motion.spring,
      child: widget.child,
    );
    if (widget.onTap != null) child = GestureDetector(behavior: HitTestBehavior.opaque, onTap: widget.onTap, child: child);
    // raw pointer events: the press look works together with any InkWell / button inside
    return Listener(
      onPointerDown: (e) {
        _from = e.position;
        _set(true);
      },
      onPointerMove: (e) {
        if (_down && (e.position - _from).distance > kTouchSlop) _set(false); // scrolling, not pressing
      },
      onPointerUp: (_) {
        if (_down && widget.haptics) Fx.tap(); // buzz only for a real tap, not when a scroll starts here
        _set(false);
      },
      onPointerCancel: (_) => _set(false),
      child: child,
    );
  }
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
  Offset _from = Offset.zero;

  /// Keys that act while held (auto-repeat, keys with a release action) fire as soon as they are
  /// touched. Every other button fires when the finger lifts without having moved: a scroll that
  /// starts on a button must not press it.
  bool get _instant => widget.repeat || widget.onRelease != null;

  void _start(PointerDownEvent e) {
    _from = e.position;
    setState(() => _down = true);
    if (!_instant) return;
    Fx.tap();
    widget.onPress();
    if (widget.repeat) {
      _t = Timer(const Duration(milliseconds: 400), () {
        _t = Timer.periodic(const Duration(milliseconds: 70), (_) => widget.onPress());
      });
    }
  }

  void _move(PointerMoveEvent e) {
    if (_down && !_instant && (e.position - _from).distance > kTouchSlop) {
      setState(() => _down = false); // the finger is scrolling, not pressing
    }
  }

  void _stop(PointerEvent e) {
    _t?.cancel();
    _t = null;
    if (_down) {
      if (_instant) {
        widget.onRelease?.call();
      } else if (e is PointerUpEvent) {
        Fx.tap();
        widget.onPress();
      }
    }
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
        onPointerMove: _move,
        onPointerUp: _stop,
        onPointerCancel: _stop,
        child: AnimatedScale(
          // pressed: sinks in quickly; released: springs back
          scale: _down ? 0.93 : 1,
          duration: _down ? Motion.fast : Motion.medium,
          curve: _down ? Curves.easeOut : Motion.spring,
          child: AnimatedContainer(
            duration: _down ? const Duration(milliseconds: 60) : Motion.medium,
            curve: Motion.curve,
            height: widget.height,
            margin: const EdgeInsets.all(3),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: _down ? Color.lerp(bg, Colors.white, 0.18) : bg,
              borderRadius: BorderRadius.circular(_down ? 14 : 12),
              boxShadow: widget.active
                  ? [BoxShadow(color: C.accent.withValues(alpha: 0.35), blurRadius: 12, spreadRadius: -2)]
                  : null,
            ),
            child: Text(widget.label,
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: widget.fontSize, color: C.text)),
          ),
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
