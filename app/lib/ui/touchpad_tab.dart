import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../core/connection.dart';
import '../core/settings.dart';
import 'common.dart';
import 'screen_preview.dart';

/// The phone as a laptop touchpad (same gestures as the web app):
/// 1 finger move · tap = click · 2-finger tap = right click · 3-finger tap = middle
/// 2-finger drag = scroll · double-tap and drag = drag · hold Left/Right buttons.
class TouchpadTab extends StatelessWidget {
  const TouchpadTab({super.key, required this.conn, required this.settings, required this.preview});
  final Connection conn;
  final Settings settings;
  final PreviewController preview;

  @override
  Widget build(BuildContext context) => Column(children: [
        ScreenPreview(controller: preview, settings: settings, allowLarge: true),
        Expanded(child: Touchpad(conn: conn, settings: settings)),
        const SizedBox(height: 8),
        Row(children: [
          for (final b in ['left', 'middle', 'right'])
            KeyButton(
              label: b == 'middle' ? '●' : '${b[0].toUpperCase()}${b.substring(1)}',
              flex: b == 'middle' ? 1 : 3,
              height: 60,
              fontSize: 16,
              onPress: () {
                haptic(settings.haptics);
                conn.send({'t': 'b', 'b': b, 'a': 'down'});
              },
              onRelease: () => conn.send({'t': 'b', 'b': b, 'a': 'up'}),
            ),
        ]),
      ]);
}

class Touchpad extends StatefulWidget {
  const Touchpad({super.key, required this.conn, required this.settings});
  final Connection conn;
  final Settings settings;
  @override
  State<Touchpad> createState() => _TouchpadState();
}

class _Finger {
  _Finger(this.pos, this.t);
  Offset pos;
  int t;
}

class _Ripple {
  _Ripple(this.pos, this.color);
  final Offset pos;
  final Color color;
  final born = DateTime.now();
  double get age => DateTime.now().difference(born).inMilliseconds / 450; // 0..1
}

class _TouchpadState extends State<Touchpad> with SingleTickerProviderStateMixin {
  final _fingers = <int, _Finger>{};
  final _ripples = <_Ripple>[];
  late final Ticker _ticker = createTicker((_) {
    _ripples.removeWhere((r) => r.age >= 1);
    if (_ripples.isEmpty) _ticker.stop();
    setState(() {});
  });

  /// Click feedback you can see: a ring spreading from the finger.
  void _ripple(Offset pos, Color color) {
    _ripples.add(_Ripple(pos, color));
    if (!_ticker.isActive) _ticker.start();
  }
  double _accX = 0, _accY = 0, _scrX = 0, _scrY = 0;
  Timer? _flushTimer;
  // current gesture
  int _t0 = 0, _max = 0;
  double _moved = 0;
  bool _active = false, _dragPending = false, _dragging = false;
  int _lastTapT = 0;
  Offset _lastTapPos = Offset.zero;

  static const tapMs = 220, tapMove = 10.0, doubleMs = 300;

  Connection get conn => widget.conn;
  Settings get s => widget.settings;
  int get _now => DateTime.now().millisecondsSinceEpoch;

  void _scheduleFlush() {
    _flushTimer ??= Timer(const Duration(milliseconds: 12), _flush);
  }

  void _flush() {
    _flushTimer = null;
    final mx = _accX.truncate(), my = _accY.truncate();
    if (mx != 0 || my != 0) {
      if (conn.send({'t': 'm', 'x': mx, 'y': my})) {
        _accX -= mx;
        _accY -= my;
      } else {
        _accX = _accY = 0;
      }
    }
    final sx = _scrX.truncate(), sy = _scrY.truncate();
    if (sx != 0 || sy != 0) {
      conn.send({'t': 's', 'x': sx, 'y': sy});
      _scrX -= sx;
      _scrY -= sy;
    }
  }

  void _down(PointerDownEvent e) {
    final now = _now;
    _fingers[e.pointer] = _Finger(e.localPosition, now);
    if (!_active) {
      _active = true;
      _t0 = now;
      _max = 0;
      _moved = 0;
      // a second touch right after a tap, near it -> double-tap-and-drag
      _dragPending = now - _lastTapT < doubleMs && (e.localPosition - _lastTapPos).distance < 60;
    }
    _max = max(_max, _fingers.length);
    if (_fingers.length > 1) _dragPending = false;
    setState(() {}); // finger glow
  }

  void _move(PointerMoveEvent e) {
    final f = _fingers[e.pointer];
    if (f == null || !_active) return;
    final now = _now;
    final d = e.localPosition - f.pos;
    final dt = max(1, now - f.t);
    f.pos = e.localPosition;
    f.t = now;
    // average movement across fingers: each finger reports separately, so scale by count
    final n = _fingers.length;
    final dx = d.dx, dy = d.dy, dist = d.distance;
    _moved += dist / n;

    if (n >= 2) {
      // two-finger scroll (Windows wheel units: 120 per notch)
      final k = s.scrollSpeed * 2.5 / n, dir = s.natural ? 1 : -1;
      _scrY += dy * k * dir;
      _scrX += -dx * k * dir;
      _scheduleFlush();
      setState(() {});
      return;
    }
    if (_max > 1 && !_dragging) return; // leftover finger after a scroll / right-click

    if (_dragPending && _moved > 6) {
      _dragPending = false;
      _dragging = true;
      conn.send({'t': 'b', 'b': 'left', 'a': 'down'});
      Fx.press(); // grabbed
      _ripple(e.localPosition, C.accent);
    }
    final v = dist / dt; // logical px per ms
    final gain = s.speed * (1 + s.accel * min(max(v - 0.15, 0), 3));
    final dpr = MediaQuery.devicePixelRatioOf(context);
    _accX += dx * gain * dpr * 0.6;
    _accY += dy * gain * dpr * 0.6;
    _scheduleFlush();
    setState(() {});
  }

  void _up(PointerEvent e, {bool cancelled = false}) {
    final last = _fingers.remove(e.pointer);
    if (_fingers.isNotEmpty || !_active) return;
    _active = false;
    final now = _now;
    if (_dragging) {
      _flush();
      conn.send({'t': 'b', 'b': 'left', 'a': 'up'});
      _dragging = false;
    } else if (!cancelled && now - _t0 < tapMs + (_max > 1 ? 80 : 0) && _moved < tapMove) {
      final b = _max == 1 ? 'left' : _max == 2 ? 'right' : 'middle';
      conn.send({'t': 'b', 'b': b, 'a': 'click'});
      b == 'left' ? Fx.tap() : Fx.press();
      _ripple(last?.pos ?? e.localPosition, b == 'left' ? C.accent : b == 'right' ? C.warn : C.ok);
      if (b == 'left') {
        _lastTapT = now;
        _lastTapPos = last?.pos ?? Offset.zero;
      }
    }
    _dragPending = false;
    setState(() {});
  }

  @override
  void dispose() {
    _flushTimer?.cancel();
    _ticker.dispose();
    if (_dragging) conn.send({'t': 'b', 'b': 'left', 'a': 'up'}); // never leave the button held
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Listener(
        onPointerDown: _down,
        onPointerMove: _move,
        onPointerUp: _up,
        onPointerCancel: (e) => _up(e, cancelled: true),
        child: AnimatedContainer(
          duration: Motion.medium,
          curve: Motion.curve,
          width: double.infinity,
          decoration: BoxDecoration(
            color: _fingers.isEmpty ? C.panel : const Color(0xFF1E222B),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: _dragging ? C.accent : const Color(0xFF2A2F3A), width: _dragging ? 2 : 1),
            boxShadow: _dragging ? [BoxShadow(color: C.accent.withValues(alpha: 0.25), blurRadius: 18)] : null,
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(18),
            child: Stack(children: [
              Center(
                child: AnimatedOpacity(
                  opacity: _fingers.isEmpty ? 1 : 0.25,
                  duration: Motion.medium,
                  child: const Text(
                    '1 finger: move · tap: click\n2 fingers: scroll · 2-finger tap: right click\ndouble-tap & drag: drag',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Color(0xFF4A4F5C), fontSize: 13, height: 1.5),
                  ),
                ),
              ),
              Positioned.fill(
                child: IgnorePointer(
                  child: CustomPaint(painter: _PadPainter([for (final f in _fingers.values) f.pos], _ripples, _dragging)),
                ),
              ),
            ]),
          ),
        ),
      );
}

/// Glow under each finger and the click ripples.
class _PadPainter extends CustomPainter {
  _PadPainter(this.fingers, this.ripples, this.dragging);
  final List<Offset> fingers;
  final List<_Ripple> ripples;
  final bool dragging;

  @override
  void paint(Canvas canvas, Size size) {
    for (final p in fingers) {
      const r = 44.0;
      canvas.drawCircle(
        p,
        r,
        Paint()
          ..shader = RadialGradient(colors: [
            C.accent.withValues(alpha: dragging ? 0.45 : 0.28),
            C.accent.withValues(alpha: 0),
          ]).createShader(Rect.fromCircle(center: p, radius: r)),
      );
      canvas.drawCircle(p, 5, Paint()..color = C.accent.withValues(alpha: 0.7));
    }
    for (final rp in ripples) {
      final a = Curves.easeOutCubic.transform(rp.age.clamp(0.0, 1.0));
      final fade = 1 - a;
      canvas.drawCircle(rp.pos, 16 + 46 * a, Paint()..color = rp.color.withValues(alpha: 0.16 * fade));
      canvas.drawCircle(
        rp.pos,
        16 + 46 * a,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.5 * fade + 0.5
          ..color = rp.color.withValues(alpha: 0.75 * fade),
      );
    }
  }

  @override
  bool shouldRepaint(_PadPainter old) => true;
}