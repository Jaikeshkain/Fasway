import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

import '../core/connection.dart';
import '../core/settings.dart';
import 'common.dart';
import 'live_typing.dart';

/// Owns the WebRTC stream of the laptop screen (+ optional laptop sound) and the cursor feed.
/// Shared by the inline preview (Touchpad / Keyboard tabs) and the full-screen page.
class PreviewController extends ChangeNotifier {
  PreviewController(this.conn, this.settings) {
    _sub = conn.messages.listen(_onMessage);
    settings.addListener(_onSettings);
    _lastQuality = settings.screenQuality;
  }

  final Connection conn;
  final Settings settings;
  RTCVideoRenderer renderer = RTCVideoRenderer();
  bool _rendererReady = false;
  RTCPeerConnection? _pc;
  MediaStreamTrack? _audioTrack;
  late final StreamSubscription _sub;
  bool _active = false, _disposed = false;
  // Every start and stop gets a new number; work left over from an older start (a slow setup, the
  // laptop's answer to a replaced offer) sees the number changed and drops out. Before, quickly
  // turning the screen off and on could apply an old answer to the new connection: black screen.
  int _gen = 0, _offerId = 0;
  Future<void>? _rendererInit;
  Timer? _retry;
  String _lastQuality = 'medium';

  String? message = 'Connecting to screen…';
  Offset? cursor; // laptop cursor as a fraction of the shown screen
  bool audioOn = false, audioSupported = true;
  int fullscreenUsers = 0; // the full-screen page keeps the stream alive

  int get videoW => renderer.videoWidth;
  int get videoH => renderer.videoHeight;
  bool get hasVideo => videoW > 0 && videoH > 0;

  void setActive(bool want) {
    want = want || fullscreenUsers > 0;
    if (want == _active) return;
    _active = want;
    want ? _start() : _stop(notifyLaptop: true);
  }

  Future<void> _start() async {
    if (_disposed) return;
    final gen = ++_gen;
    _retry?.cancel();
    message = 'Connecting to screen…';
    notifyListeners();
    try {
      final r = renderer;
      await (_rendererInit ??= r.initialize());
      if (gen != _gen) return;
      r.onResize = notifyListeners;
      _rendererReady = true;
      // play laptop sound like media (speaker / Bluetooth), not like a phone call through the earpiece,
      // and don't steal audio focus from the phone's own music
      await Helper.setAndroidAudioConfiguration(AndroidAudioConfiguration(
        manageAudioFocus: false,
        androidAudioMode: AndroidAudioMode.normal,
        androidAudioStreamType: AndroidAudioStreamType.music,
        androidAudioAttributesUsageType: AndroidAudioAttributesUsageType.media,
        androidAudioAttributesContentType: AndroidAudioAttributesContentType.movie,
      ));
      if (gen != _gen) return;
      final pc = await createPeerConnection({'iceServers': [], 'sdpSemantics': 'unified-plan'});
      if (gen != _gen) {
        await pc.close();
        return;
      }
      _pc = pc;
      await pc.addTransceiver(
          kind: RTCRtpMediaType.RTCRtpMediaTypeVideo,
          init: RTCRtpTransceiverInit(direction: TransceiverDirection.RecvOnly));
      await pc.addTransceiver(
          kind: RTCRtpMediaType.RTCRtpMediaTypeAudio,
          init: RTCRtpTransceiverInit(direction: TransceiverDirection.RecvOnly));
      pc.onTrack = (e) {
        if (_pc != pc) return;
        if (e.track.kind == 'video' && e.streams.isNotEmpty) {
          renderer.srcObject = e.streams.first;
        } else if (e.track.kind == 'audio') {
          _audioTrack = e.track;
          e.track.enabled = audioOn;
        }
      };
      pc.onConnectionState = (st) {
        if (_pc != pc) return;
        if (st == RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
          message = null;
          notifyListeners();
        } else if (st == RTCPeerConnectionState.RTCPeerConnectionStateFailed ||
            st == RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
          message = 'Screen connection lost – retrying…';
          notifyListeners();
          _stop(notifyLaptop: false);
          _retry = Timer(const Duration(milliseconds: 1500), () {
            if (_active) _start();
          });
        }
      };
      final gathered = Completer<void>();
      pc.onIceGatheringState = (st) {
        if (st == RTCIceGatheringState.RTCIceGatheringStateComplete && !gathered.isCompleted) gathered.complete();
      };
      await pc.setLocalDescription(await pc.createOffer());
      // the laptop doesn't trickle ICE: send the offer with all candidates (max ~1.5 s wait)
      await gathered.future.timeout(const Duration(milliseconds: 1500), onTimeout: () {});
      if (_pc != pc || gen != _gen || !_active) return;
      final desc = await pc.getLocalDescription();
      final q = Settings.quality[settings.screenQuality] ?? Settings.quality['medium']!;
      _offerId = gen;
      conn.send({'t': 'rtc_offer', 'sdp': desc!.sdp, 'type': desc.type, 'w': q.w, 'fps': q.fps, 'id': gen});
      // no picture after a while (offer lost in a reconnect, laptop busy…): start over instead of staying black
      _retry = Timer(const Duration(seconds: 10), () {
        if (gen == _gen && _active && pc.connectionState != RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
          _stop(notifyLaptop: true);
          _start();
        }
      });
    } catch (e) {
      if (gen != _gen) return;
      message = 'Screen error: $e';
      notifyListeners();
    }
  }

  Future<void> _onMessage(Map<String, dynamic> m) async {
    switch (m['t']) {
      case 'rtc_answer':
        final pc = _pc;
        if (pc == null) return;
        if (m['id'] != null && m['id'] != _offerId) return; // answer to an offer that was replaced
        final signaling = await pc.getSignalingState();
        if (_pc != pc || signaling != RTCSignalingState.RTCSignalingStateHaveLocalOffer) return; // already answered
        if (m['warn'] != null) message = m['warn'] as String;
        audioSupported = m['audio'] != false;
        if (audioOn) conn.send({'t': 'audio', 'on': true}); // re-enable after a reconnect
        try {
          await pc.setRemoteDescription(RTCSessionDescription(m['sdp'] as String, m['type'] as String));
        } catch (e) {
          message = 'Screen error: $e';
        }
        notifyListeners();
      case 'cur':
        cursor = Offset((m['x'] as num).toDouble(), (m['y'] as num).toDouble());
        notifyListeners();
      case 'hello':
        if (_active) {
          _stop(notifyLaptop: false); // fresh connection: renegotiate
          _start();
        }
    }
  }

  void _onSettings() {
    if (settings.screenQuality != _lastQuality) {
      _lastQuality = settings.screenQuality;
      final q = Settings.quality[_lastQuality]!;
      if (_pc != null) conn.send({'t': 'rtc_cfg', 'w': q.w, 'fps': q.fps}); // applied live
    }
  }

  void toggleAudio() {
    audioOn = !audioOn;
    _audioTrack?.enabled = audioOn;
    conn.send({'t': 'audio', 'on': audioOn});
    notifyListeners();
  }

  void _stop({required bool notifyLaptop}) {
    _gen++;
    _retry?.cancel();
    if (notifyLaptop) conn.send({'t': 'rtc_stop'});
    final pc = _pc;
    _pc = null;
    _audioTrack = null;
    pc?.close();
    if (_rendererReady) _retireRenderer();
    cursor = null;
    if (!_disposed) notifyListeners();
  }

  /// A renderer forgets the video size when its stream is replaced and isn't told it again when the
  /// new stream has the same size, so after switching tabs the picture came back squashed. Every
  /// stream gets a fresh renderer instead.
  void _retireRenderer() {
    final old = renderer;
    old.onResize = null;
    renderer = RTCVideoRenderer();
    _rendererReady = false;
    _rendererInit = null;
    // the old view can still be on screen this frame: release it a moment later
    Timer(const Duration(seconds: 1), () {
      old.srcObject = null;
      old.dispose();
    });
  }

  @override
  void dispose() {
    _disposed = true;
    _sub.cancel();
    settings.removeListener(_onSettings);
    _stop(notifyLaptop: true);
    if (_rendererReady) renderer.dispose();
    super.dispose();
  }
}

// ----------------------------------------------------------------------------------------------

/// Inline preview: shown above the touchpad / keyboard when the 🖥 button is on.
class ScreenPreview extends StatelessWidget {
  const ScreenPreview({super.key, required this.controller, required this.settings, this.allowLarge = false});
  final PreviewController controller;
  final Settings settings;
  final bool allowLarge;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: settings,
        builder: (context, _) {
          final large = allowLarge && settings.screenLarge;
          final h = MediaQuery.sizeOf(context).height;
          // switching the preview on / off: it grows open and folds away instead of popping
          return AnimatedSize(
            duration: Motion.medium,
            curve: Motion.curve,
            alignment: Alignment.topCenter,
            child: !settings.screenOn
                ? const SizedBox(width: double.infinity)
                : Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: ConstrainedBox(
              constraints: BoxConstraints(maxHeight: large ? h * 0.5 : h * 0.3),
              child: AspectRatio(
                aspectRatio: large ? 16 / 12 : 16 / 9,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(14),
                  child: PreviewSurface(
                    controller: controller,
                    settings: settings,
                    toolbar: [
                      _ToolBtn(
                          icon: Icons.fullscreen_rounded,
                          onTap: () => Navigator.push(
                              context,
                              PageRouteBuilder(
                                pageBuilder: (_, _, _) => FullscreenPreview(controller: controller, settings: settings),
                                transitionDuration: Duration.zero,
                              ))),
                      if (allowLarge)
                        _ToolBtn(
                            icon: large ? Icons.unfold_less_rounded : Icons.unfold_more_rounded,
                            onTap: () => settings.set('screenLarge', !settings.screenLarge)),
                    ],
                  ),
                ),
              ),
            ),
          ),
          );
        },
      );
}

/// Real full screen in landscape (Android immersive mode) with the same touch controls.
class FullscreenPreview extends StatefulWidget {
  const FullscreenPreview({super.key, required this.controller, required this.settings});
  final PreviewController controller;
  final Settings settings;
  @override
  State<FullscreenPreview> createState() => _FullscreenPreviewState();
}

class _FullscreenPreviewState extends State<FullscreenPreview> {
  final _typingFocus = FocusNode();
  bool _rotated = false; // false = landscape (default)

  @override
  void initState() {
    super.initState();
    widget.controller.fullscreenUsers++;
    widget.controller.setActive(true);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    _orient();
  }

  void _orient() => SystemChrome.setPreferredOrientations(_rotated
      ? [DeviceOrientation.portraitUp]
      : [DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]);

  @override
  void dispose() {
    widget.controller.fullscreenUsers--;
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    SystemChrome.setPreferredOrientations([]);
    _typingFocus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: Colors.black,
        body: Stack(children: [
          // invisible input: the ⌨ button opens the phone keyboard and typing goes live to the laptop
          Positioned(
            left: 0,
            top: 0,
            width: 1,
            height: 1,
            child: Opacity(opacity: 0, child: LiveTypingField(conn: widget.controller.conn, focusNode: _typingFocus)),
          ),
          Positioned.fill(
            child: PreviewSurface(
              controller: widget.controller,
              settings: widget.settings,
              toolbar: [
                _ToolBtn(
                  icon: Icons.keyboard_rounded,
                  onTap: () => _typingFocus.hasFocus ? _typingFocus.unfocus() : _typingFocus.requestFocus(),
                ),
                _ToolBtn(
                  icon: Icons.screen_rotation_rounded,
                  onTap: () {
                    setState(() => _rotated = !_rotated);
                    _orient();
                  },
                ),
                _ToolBtn(icon: Icons.fullscreen_exit_rounded, onTap: () => Navigator.pop(context)),
              ],
            ),
          ),
        ]),
      );
}

class _ToolBtn extends StatelessWidget {
  const _ToolBtn({required this.icon, required this.onTap, this.dim = false});
  final IconData icon;
  final VoidCallback onTap;
  final bool dim;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(left: 6),
        child: Material(
          color: Colors.black54,
          borderRadius: BorderRadius.circular(9),
          child: InkWell(
            borderRadius: BorderRadius.circular(9),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.all(7),
              child: Icon(icon, size: 20, color: dim ? Colors.white54 : Colors.white),
            ),
          ),
        ),
      );
}

// ----------------------------------------------------------------------------------------------

/// The video plus touch control.
/// 🖱 trackpad (default): slide anywhere moves the cursor from where it is, tap = click at the cursor,
///    double-tap+slide = drag, long-press / 2-finger tap = right click, 2-finger slide = scroll,
///    pinch = zoom around the cursor (the view then follows the cursor).
/// 👆 direct: tap where you want to click, long-press = right click, drag = drag; pinch zooms.
/// 👁 view only: pinch / pan the picture.
class PreviewSurface extends StatefulWidget {
  const PreviewSurface({super.key, required this.controller, required this.settings, this.toolbar = const []});
  final PreviewController controller;
  final Settings settings;
  final List<Widget> toolbar;
  @override
  State<PreviewSurface> createState() => _PreviewSurfaceState();
}

class _PreviewSurfaceState extends State<PreviewSurface> {
  static const modes = {'trackpad': ('🖱', 'Trackpad – slide to move, tap to click'), 'direct': ('👆', 'Direct – tap where you want to click'), 'view': ('👁', 'View only – pinch to zoom')};
  static const longMs = 500, tpDoubleMs = 300;

  // view transform (zoom / pan of the picture)
  double _s = 1, _tx = 0, _ty = 0;
  Size _size = Size.zero;

  // gesture
  final _f = <int, Offset>{};
  String _g = 'none'; // tp-pending tp-move tp-drag pending1 drag pan1 pending2 zoom scroll done
  int _t0 = 0;
  Offset _start = Offset.zero, _last = Offset.zero;
  int _lastT = 0;
  bool _dragArmed = false;
  int _lastTapT = 0;
  Offset _lastTapPos = Offset.zero;
  Timer? _longTimer;
  // two-finger
  Offset _c0 = Offset.zero, _cLast = Offset.zero;
  double _d0 = 1, _s0 = 1, _tx0 = 0, _ty0 = 0;
  Offset? _anchor;
  Offset? _lastFrac;
  // outgoing
  double _relX = 0, _relY = 0, _scrX = 0, _scrY = 0;
  Timer? _flushT;
  String? _hint;
  Timer? _hintT;

  PreviewController get c => widget.controller;
  Settings get st => widget.settings;
  Connection get conn => c.conn;
  String get mode => modes.containsKey(st.screenMode) ? st.screenMode : 'trackpad';
  int get _now => DateTime.now().millisecondsSinceEpoch;

  @override
  void initState() {
    super.initState();
    c.addListener(_onController);
  }

  @override
  void dispose() {
    c.removeListener(_onController);
    _longTimer?.cancel();
    _flushT?.cancel();
    _hintT?.cancel();
    super.dispose();
  }

  void _onController() {
    // zoomed in: keep the cursor in view
    if (_s > 1.02 && c.cursor != null && mode != 'view' && c.hasVideo) {
      final p = _fracToLocal(c.cursor!);
      final mx = _size.width * 0.2, my = _size.height * 0.2;
      if (p.dx < mx) {
        _tx += mx - p.dx;
      } else if (p.dx > _size.width - mx) {
        _tx -= p.dx - (_size.width - mx);
      }
      if (p.dy < my) {
        _ty += my - p.dy;
      } else if (p.dy > _size.height - my) {
        _ty -= p.dy - (_size.height - my);
      }
      _clampView();
    }
    if (mounted) setState(() {});
  }

  void _say(String msg) {
    setState(() => _hint = msg);
    _hintT?.cancel();
    _hintT = Timer(const Duration(milliseconds: 1400), () => mounted ? setState(() => _hint = null) : null);
  }

  // ---- geometry ----
  ({double cw, double ch, double ox, double oy}) _box() {
    final w = _size.width, h = _size.height;
    if (!c.hasVideo) return (cw: w, ch: h, ox: 0, oy: 0);
    final k = min(w / c.videoW, h / c.videoH);
    final cw = c.videoW * k, ch = c.videoH * k;
    return (cw: cw, ch: ch, ox: (w - cw) / 2, oy: (h - ch) / 2);
  }

  Offset _fracToLocal(Offset f) {
    final b = _box();
    return Offset((b.ox + f.dx * b.cw) * _s + _tx, (b.oy + f.dy * b.ch) * _s + _ty);
  }

  Offset? _toFrac(Offset p, {bool clamp = false}) {
    if (!c.hasVideo) return null;
    final b = _box();
    var fx = ((p.dx - _tx) / _s - b.ox) / b.cw, fy = ((p.dy - _ty) / _s - b.oy) / b.ch;
    if (clamp) {
      fx = fx.clamp(0.0, 1.0);
      fy = fy.clamp(0.0, 1.0);
    } else if (fx < 0 || fx > 1 || fy < 0 || fy > 1) {
      return null;
    }
    return Offset(fx, fy);
  }

  void _clampView() {
    _s = _s.clamp(1.0, 6.0);
    _tx = _tx.clamp(_size.width - _size.width * _s, 0.0);
    _ty = _ty.clamp(_size.height - _size.height * _s, 0.0);
  }

  void _resetView() => setState(() {
        _s = 1;
        _tx = _ty = 0;
      });

  // ---- sending ----
  void _point(Offset f, [String? a]) =>
      conn.send({'t': 'point', 'x': f.dx, 'y': f.dy, if (a != null) 'a': a});

  void _queueRel(double dx, double dy) {
    if (!c.hasVideo) return;
    final b = _box();
    _relX += dx / (b.cw * _s);
    _relY += dy / (b.ch * _s);
    _flushT ??= Timer(const Duration(milliseconds: 12), _flush);
  }

  void _queueScroll(double dx, double dy) {
    final k = st.scrollSpeed * 2.5, dir = st.natural ? 1 : -1;
    _scrY += dy * k * dir;
    _scrX += -dx * k * dir;
    _flushT ??= Timer(const Duration(milliseconds: 12), _flush);
  }

  void _flush() {
    _flushT = null;
    if (_relX != 0 || _relY != 0) {
      if (conn.send({'t': 'rel', 'x': double.parse(_relX.toStringAsFixed(5)), 'y': double.parse(_relY.toStringAsFixed(5))})) {
        _relX = _relY = 0;
      }
    }
    final sx = _scrX.truncate(), sy = _scrY.truncate();
    if (sx != 0 || sy != 0) {
      conn.send({'t': 's', 'x': sx, 'y': sy});
      _scrX -= sx;
      _scrY -= sy;
    }
  }

  void _btn(String b, String a) {
    _flush(); // movement first, so the click lands where the cursor ended up
    conn.send({'t': 'b', 'b': b, 'a': a});
  }

  // ---- touch handling ----
  (Offset, double) _two() {
    final p = _f.values.take(2).toList();
    return ((p[0] + p[1]) / 2, (p[0] - p[1]).distance);
  }

  void _down(PointerDownEvent e) {
    _f[e.pointer] = e.localPosition;
    final now = _now;
    if (_f.length == 1 && _g == 'none') {
      _start = _last = e.localPosition;
      _t0 = _lastT = now;
      _lastFrac = null;
      if (mode == 'trackpad') {
        _g = 'tp-pending';
        _dragArmed = now - _lastTapT < tpDoubleMs && (e.localPosition - _lastTapPos).distance < 60;
        _longTimer = Timer(const Duration(milliseconds: longMs), () {
          if (_g == 'tp-pending' && !_dragArmed) {
            _btn('right', 'click');
            haptic(st.haptics);
            _say('Right click');
            _g = 'done';
          }
        });
      } else {
        _g = 'pending1';
        if (mode == 'direct') {
          final p = e.localPosition;
          _longTimer = Timer(const Duration(milliseconds: longMs), () {
            if (_g != 'pending1') return;
            final f = _toFrac(p);
            if (f != null) {
              _point(f, 'rclick');
              haptic(st.haptics);
              _say('Right click');
            }
            _g = 'done';
          });
        }
      }
    } else if (_f.length == 2) {
      _longTimer?.cancel();
      if (_g == 'tp-drag') {
        _btn('left', 'up');
      } else if (_g == 'drag') {
        _endDirectDrag();
      }
      final (cen, d) = _two();
      _c0 = _cLast = cen;
      _d0 = max(d, 1);
      _s0 = _s;
      _tx0 = _tx;
      _ty0 = _ty;
      _anchor = null;
      _t0 = now;
      _g = 'pending2';
    }
  }

  void _endDirectDrag() {
    final f = _lastFrac ?? _toFrac(_start, clamp: true);
    if (f != null) _point(f, 'up');
    _g = 'done';
  }

  void _move(PointerMoveEvent e) {
    if (!_f.containsKey(e.pointer)) return;
    _f[e.pointer] = e.localPosition;
    final p = e.localPosition, now = _now;
    if (_f.length == 1) {
      if (_g.startsWith('tp-')) {
        if (_g == 'tp-pending') {
          if ((p - _start).distance < 8) return;
          _longTimer?.cancel();
          if (_dragArmed) {
            _btn('left', 'down');
            _g = 'tp-drag';
            haptic(st.haptics);
          } else {
            _g = 'tp-move';
          }
        }
        // 1:1 with the picture, a little faster for quick flicks
        final d = p - _last;
        final v = d.distance / max(1, now - _lastT);
        final gain = 1 + 0.6 * min(max(v - 0.3, 0), 2);
        _queueRel(d.dx * gain, d.dy * gain);
        _last = p;
        _lastT = now;
        return;
      }
      if (_g == 'pending1') {
        if ((p - _start).distance < 10) return;
        _longTimer?.cancel();
        if (mode == 'view') {
          _g = 'pan1';
          _tx0 = _tx;
          _ty0 = _ty;
        } else {
          final f0 = _toFrac(_start);
          if (f0 == null) {
            _g = 'done';
            return;
          }
          _point(f0, 'down');
          _g = 'drag';
          haptic(st.haptics);
        }
      }
      if (_g == 'drag') {
        final f = _toFrac(p, clamp: true);
        if (f != null) {
          _lastFrac = f;
          _point(f);
        }
      } else if (_g == 'pan1') {
        setState(() {
          _tx = _tx0 + p.dx - _start.dx;
          _ty = _ty0 + p.dy - _start.dy;
          _clampView();
        });
      }
      return;
    }
    if (_f.length >= 2) {
      final (cen, d) = _two();
      if (_g == 'pending2') {
        final dd = (d - _d0).abs(), dc = (cen - _c0).distance;
        if (dd > 14) {
          _g = 'zoom';
        } else if (dc > 10) {
          _g = mode == 'trackpad' ? 'scroll' : (_s > 1.02 || mode == 'view') ? 'zoom' : 'scroll';
          if (_g == 'scroll' && mode == 'direct') {
            final f = _toFrac(_c0, clamp: true);
            if (f != null) _point(f); // scroll the window under the fingers
          }
        } else {
          return;
        }
      }
      if (_g == 'zoom') {
        final s = (_s0 * d / _d0).clamp(1.0, 6.0);
        setState(() {
          if (mode == 'trackpad' && c.cursor != null) {
            _anchor ??= _fracToLocal(c.cursor!); // fingers can be anywhere: zoom around the cursor
            final px = (_anchor!.dx - _tx0) / _s0, py = (_anchor!.dy - _ty0) / _s0;
            _s = s;
            _tx = _anchor!.dx - px * s;
            _ty = _anchor!.dy - py * s;
          } else {
            final px = (_c0.dx - _tx0) / _s0, py = (_c0.dy - _ty0) / _s0;
            _s = s;
            _tx = cen.dx - px * s;
            _ty = cen.dy - py * s;
          }
          _clampView();
        });
      } else if (_g == 'scroll') {
        _queueScroll(cen.dx - _cLast.dx, cen.dy - _cLast.dy);
      }
      _cLast = cen;
    }
  }

  void _up(PointerEvent e, {bool cancelled = false}) {
    _f.remove(e.pointer);
    if (_f.isNotEmpty) return; // wait until every finger is up
    _longTimer?.cancel();
    final dt = _now - _t0;
    if (_g == 'tp-pending' && dt < longMs && !cancelled) {
      _btn('left', 'click'); // click wherever the cursor is
      haptic(st.haptics);
      _lastTapT = _now;
      _lastTapPos = _start;
    } else if (_g == 'tp-drag') {
      _btn('left', 'up');
    } else if (_g == 'pending1' && mode == 'direct' && dt < longMs && !cancelled) {
      final f = _toFrac(_start);
      if (f != null) {
        _point(f, 'click');
        haptic(st.haptics);
      }
    } else if (_g == 'drag') {
      _endDirectDrag();
    } else if (_g == 'pending2' && dt < 300) {
      if (mode == 'trackpad') {
        _btn('right', 'click');
        haptic(st.haptics);
        _say('Right click');
      } else {
        _resetView();
        _say('Zoom reset');
      }
    }
    _g = 'none';
  }

  void _cycleMode() {
    final order = modes.keys.toList();
    final next = order[(order.indexOf(mode) + 1) % order.length];
    st.set('screenMode', next);
    _say(modes[next]!.$2);
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, box) {
        final size = Size(box.maxWidth, box.maxHeight);
        if (size != _size) {
          _size = size;
          _clampView();
        }
        final ring = (c.cursor != null && c.hasVideo && mode != 'view') ? _fracToLocal(c.cursor!) : null;
        return Container(
          color: Colors.black,
          child: Stack(children: [
            Positioned.fill(
              child: Transform(
                transform: Matrix4.identity()
                  ..translateByDouble(_tx, _ty, 0, 1)
                  ..scaleByDouble(_s, _s, 1, 1),
                child: RTCVideoView(c.renderer, key: ObjectKey(c.renderer), objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitContain),
              ),
            ),
            if (ring != null && ring.dx >= 0 && ring.dy >= 0 && ring.dx <= size.width && ring.dy <= size.height)
              Positioned(
                left: ring.dx - 13,
                top: ring.dy - 13,
                child: IgnorePointer(
                  child: Container(
                    width: 26,
                    height: 26,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: C.accent.withValues(alpha: _g == 'tp-drag' ? 0.55 : 0.18),
                      border: Border.all(color: C.accent.withValues(alpha: 0.95), width: 2),
                    ),
                  ),
                ),
              ),
            Positioned.fill(
              child: Listener(
                behavior: HitTestBehavior.opaque,
                onPointerDown: _down,
                onPointerMove: _move,
                onPointerUp: _up,
                onPointerCancel: (e) => _up(e, cancelled: true),
              ),
            ),
            if (c.message != null && !c.hasVideo)
              Center(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(c.message!, textAlign: TextAlign.center, style: const TextStyle(color: C.muted, fontSize: 13)),
                ),
              ),
            if (_hint != null)
              Positioned(
                top: 10,
                left: 0,
                right: 0,
                child: Center(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                    decoration: BoxDecoration(color: Colors.black87, borderRadius: BorderRadius.circular(99)),
                    child: Text(_hint!, style: const TextStyle(fontSize: 12)),
                  ),
                ),
              ),
            Positioned(
              right: 6,
              bottom: 6,
              child: Row(children: [
                _ToolBtn(
                  icon: c.audioOn ? Icons.volume_up_rounded : Icons.volume_off_rounded,
                  dim: !c.audioOn,
                  onTap: () {
                    if (!c.audioSupported) {
                      _say("Laptop sound isn't available on this laptop");
                      return;
                    }
                    c.toggleAudio();
                    _say(c.audioOn ? 'Laptop sound on' : 'Laptop sound off');
                  },
                ),
                Padding(
                  padding: const EdgeInsets.only(left: 6),
                  child: Material(
                    color: Colors.black54,
                    borderRadius: BorderRadius.circular(9),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(9),
                      onTap: _cycleMode,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                        child: Text(modes[mode]!.$1, style: const TextStyle(fontSize: 17)),
                      ),
                    ),
                  ),
                ),
                ...widget.toolbar,
              ]),
            ),
          ]),
        );
      });
}
