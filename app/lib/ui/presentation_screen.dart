import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/connection.dart';
import '../core/settings.dart';
import 'common.dart';

/// Presentation remote: big Next / Back, the phone's volume buttons as a clicker, a talk timer,
/// start / black screen / end, and a laser pointer moved with your finger (PowerPoint's Ctrl+L).
/// Uses plain keys, so it works in PowerPoint, Google Slides, Keynote and PDF viewers.
class PresentationScreen extends StatefulWidget {
  const PresentationScreen({super.key, required this.conn, required this.settings});
  final Connection conn;
  final Settings settings;
  @override
  State<PresentationScreen> createState() => _PresentationScreenState();
}

class _PresentationScreenState extends State<PresentationScreen> {
  static const _keys = MethodChannel('fasway/keys');
  final _clock = Stopwatch();
  Timer? _tick;
  bool _laser = false, _black = false;
  int _slide = 0; // presses of Next minus Back, since the start: a rough "where am I"
  double _accX = 0, _accY = 0;

  Connection get conn => widget.conn;
  bool get _mac => conn.laptopOs == 'mac';

  @override
  void initState() {
    super.initState();
    _keys.setMethodCallHandler((call) async {
      if (call.method == 'volume') call.arguments == 'up' ? _next() : _back();
    });
    _keys.invokeMethod('volumeKeys', true).catchError((Object _) => null);
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_clock.isRunning && mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _keys.invokeMethod('volumeKeys', false).catchError((Object _) => null);
    _keys.setMethodCallHandler(null);
    _tick?.cancel();
    if (_laser) _key(_mac ? 'escape' : 'ctrl+a'); // back to the normal pointer
    super.dispose();
  }

  bool _key(String k) => conn.send({'t': 'key', 'k': k});

  void _press(String k, {bool heavy = false}) {
    if (!_key(k)) {
      toast(context, 'Not connected to the laptop');
      return;
    }
    heavy ? Fx.heavy() : Fx.tap();
  }

  void _next() {
    _press('right');
    setState(() => _slide++);
  }

  void _back() {
    _press('left');
    setState(() => _slide = (_slide - 1).clamp(0, 9999));
  }

  void _start({bool fromHere = false}) {
    _press(_mac ? (fromHere ? 'cmd+enter' : 'cmd+shift+enter') : (fromHere ? 'shift+f5' : 'f5'), heavy: true);
    setState(() {
      if (!fromHere) _slide = 0;
      _black = false;
      _clock.start();
    });
  }

  void _end() {
    _press('escape', heavy: true);
    setState(() {
      _laser = false;
      _black = false;
      _clock.stop();
    });
  }

  void _toggleBlack() {
    _press('b');
    setState(() => _black = !_black);
  }

  void _toggleLaser() {
    _press(_laser ? 'ctrl+a' : 'ctrl+l');
    setState(() => _laser = !_laser);
  }

  void _move(DragUpdateDetails d) {
    final s = widget.settings.speed;
    _accX += d.delta.dx * s;
    _accY += d.delta.dy * s;
    final x = _accX.truncate(), y = _accY.truncate();
    if (x == 0 && y == 0) return;
    conn.send({'t': 'm', 'x': x, 'y': y});
    _accX -= x;
    _accY -= y;
  }

  String get _time {
    final e = _clock.elapsed;
    final m = e.inMinutes, s = e.inSeconds % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  Widget _chip(String label, IconData icon, VoidCallback onTap, {bool on = false, Color? color}) => Expanded(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 3),
          child: Material(
            color: on ? C.accent.withValues(alpha: 0.25) : C.panel2,
            borderRadius: BorderRadius.circular(14),
            child: InkWell(
              borderRadius: BorderRadius.circular(14),
              onTap: onTap,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 10),
                child: Column(children: [
                  Icon(icon, size: 22, color: color ?? (on ? C.accent : C.text)),
                  const SizedBox(height: 3),
                  Text(label, style: const TextStyle(fontSize: 11.5), maxLines: 1, overflow: TextOverflow.fade, softWrap: false),
                ]),
              ),
            ),
          ),
        ),
      );

  Widget _big(String label, IconData icon, VoidCallback onTap, {required bool primary}) => Material(
        color: primary ? C.accent : C.panel2,
        borderRadius: BorderRadius.circular(24),
        child: InkWell(
          borderRadius: BorderRadius.circular(24),
          onTap: onTap,
          child: Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(icon, size: primary ? 64 : 40, color: primary ? Colors.white : C.text),
              Text(label, style: TextStyle(fontSize: primary ? 20 : 15, fontWeight: FontWeight.w700,
                  color: primary ? Colors.white : C.text)),
            ]),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: C.bg,
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          title: const Text('Presentation'),
          actions: [
            Tooltip(
              message: 'Tap: pause or go on · hold: back to 00:00',
              child: GestureDetector(
                onTap: () {
                  Fx.tap();
                  setState(() => _clock.isRunning ? _clock.stop() : _clock.start());
                },
                onLongPress: () {
                  Fx.press();
                  setState(_clock.reset);
                },
                child: Container(
                  margin: const EdgeInsets.only(right: 12),
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: (_clock.isRunning ? C.ok : C.muted).withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(_clock.isRunning ? Icons.timer_rounded : Icons.timer_off_rounded, size: 18,
                        color: _clock.isRunning ? C.ok : C.muted),
                    const SizedBox(width: 6),
                    Text(_time, style: const TextStyle(fontSize: 17, fontFeatures: [FontFeature.tabularFigures()])),
                  ]),
                ),
              ),
            ),
          ],
        ),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                _chip('Start', Icons.play_arrow_rounded, _start),
                _chip('From here', Icons.slideshow_rounded, () => _start(fromHere: true)),
                _chip(_black ? 'Show' : 'Black', Icons.contrast_rounded, _toggleBlack, on: _black),
                if (!_mac) _chip('Laser', Icons.highlight_rounded, _toggleLaser, on: _laser, color: _laser ? C.bad : null),
                _chip('End', Icons.stop_rounded, _end, color: C.bad),
              ]),
              const SizedBox(height: 8),
              Text(
                _laser
                    ? 'Slide your finger on the pad to move the laser'
                    : 'Volume buttons: up = next, down = back${_slide > 0 ? ' · slide ${_slide + 1}' : ''}',
                textAlign: TextAlign.center,
                style: const TextStyle(color: C.muted, fontSize: 12),
              ),
              const SizedBox(height: 8),
              if (_laser)
                Expanded(
                  flex: 3,
                  child: GestureDetector(
                    onPanUpdate: _move,
                    child: Container(
                      decoration: BoxDecoration(
                        color: C.panel,
                        borderRadius: BorderRadius.circular(20),
                        border: Border.all(color: C.bad.withValues(alpha: 0.5)),
                      ),
                      child: const Center(child: Icon(Icons.adjust_rounded, color: C.bad, size: 36)),
                    ),
                  ),
                ),
              if (_laser) const SizedBox(height: 10),
              Expanded(
                flex: _laser ? 2 : 5,
                child: _big('Next', Icons.arrow_forward_rounded, _next, primary: true),
              ),
              const SizedBox(height: 10),
              Expanded(flex: _laser ? 1 : 2, child: _big('Back', Icons.arrow_back_rounded, _back, primary: false)),
            ]),
          ),
        ),
      );
}
