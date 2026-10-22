import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/connection.dart';
import '../core/settings.dart';
import 'common.dart';

/// Laptop status, Now Playing, volume / brightness, clipboard sync and power.
class ControlsTab extends StatefulWidget {
  const ControlsTab({super.key, required this.conn, required this.settings, required this.active});
  final Connection conn;
  final Settings settings;
  final bool active;
  @override
  State<ControlsTab> createState() => _ControlsTabState();
}

class _ControlsTabState extends State<ControlsTab> with WidgetsBindingObserver {
  late final StreamSubscription _sub;
  Timer? _poll, _tick;
  Map<String, dynamic>? _sys, _status;
  // now playing
  Map<String, dynamic>? _np;
  String? _npSel;
  final _art = <String, Uint8List>{};
  DateTime _npAt = DateTime.now();
  double? _seekDrag;
  // sliders being dragged (don't overwrite with laptop values)
  double? _volDrag, _brightDrag;
  DateTime _lastVolSend = DateTime(0), _lastBrightSend = DateTime(0);
  // clipboard
  final _clips = <(String, bool)>[]; // (text, fromLaptop)
  String? _lastPhoneClip; // newest text both sides already have: never sent back and forth again

  Connection get conn => widget.conn;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // what's already on the phone clipboard when the app starts is old: only send later copies
    Clipboard.getData(Clipboard.kTextPlain).then((d) => _lastPhoneClip ??= d?.text, onError: (_) {});
    _sub = conn.messages.listen(_onMessage);
    _poll = Timer.periodic(const Duration(milliseconds: 1500), (_) => _refresh());
    _tick = Timer.periodic(const Duration(milliseconds: 250), (_) {
      if (widget.active && _cur()?['status'] == 'playing' && _seekDrag == null) setState(() {});
    });
  }

  @override
  void didUpdateWidget(ControlsTab old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) _refresh(all: true);
  }

  int _n = 0;
  void _refresh({bool all = false}) {
    if (!widget.active) return;
    conn.send({'t': 'np_get', 'have': _art.keys.toList()});
    if (all || _n++ % 2 == 0) conn.send({'t': 'sys_get'}); // volume / battery every ~3 s
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _sub.cancel();
    _poll?.cancel();
    _tick?.cancel();
    super.dispose();
  }

  void _onMessage(Map<String, dynamic> m) {
    switch (m['t']) {
      case 'sys':
        setState(() {
          _sys = m;
          _status = (m['status'] as Map?)?.cast<String, dynamic>();
        });
      case 'np':
        (m['art'] as Map?)?.forEach((k, v) => _art[k as String] = base64Decode(v as String));
        setState(() {
          _np = m;
          _npAt = DateTime.now();
        });
      case 'clip':
        final text = (m['v'] ?? '') as String;
        if (text.isEmpty) return;
        setState(() {
          _clips.removeWhere((c) => c.$1 == text);
          _clips.insert(0, (text, true));
          if (_clips.length > 10) _clips.removeLast();
        });
        if (m['manual'] != true && widget.settings.clipAuto) {
          _lastPhoneClip = text; // don't send it back to the laptop on the next return to the app
          Clipboard.setData(ClipboardData(text: text)); // native: always works, unlike the browser
          if (mounted) toast(context, '📋 Laptop clipboard copied to phone');
        }
      case 'clip_ok':
        if (mounted) {
          toast(context, m['ok'] != true ? "Couldn't set the laptop clipboard" : m['paste'] == true ? 'Pasted on laptop' : 'Sent to laptop clipboard');
        }
    }
  }

  // ---------- now playing ----------
  Map<String, dynamic>? _cur() {
    final ss = (_np?['sessions'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    if (ss.isEmpty) return null;
    return ss.firstWhere((s) => s['id'] == _npSel,
        orElse: () => ss.firstWhere((s) => s['id'] == _np!['current'], orElse: () => ss.first));
  }

  double _pos(Map<String, dynamic> cur) {
    final dur = (cur['dur'] as num).toDouble();
    var p = (cur['pos'] as num).toDouble();
    if (cur['status'] == 'playing') p += DateTime.now().difference(_npAt).inMilliseconds / 1000;
    return p.clamp(0, dur);
  }

  static String _fmt(double s) {
    final t = s.floor(), h = t ~/ 3600, m = (t % 3600) ~/ 60, x = (t % 60).toString().padLeft(2, '0');
    return h > 0 ? '$h:${m.toString().padLeft(2, '0')}:$x' : '$m:$x';
  }

  void _npCmd(String a, {double? pos}) {
    final cur = _cur();
    if (cur == null) {
      conn.send({'t': 'media', 'k': {'play_pause': 'playpause', 'next': 'nexttrack', 'prev': 'prevtrack'}[a]});
    } else {
      conn.send({'t': 'np_cmd', 'id': cur['id'], 'a': a, if (pos != null) 'pos': pos, 'have': _art.keys.toList()});
      if (a == 'play_pause') setState(() => cur['status'] = cur['status'] == 'playing' ? 'paused' : 'playing');
    }
    haptic(widget.settings.haptics);
  }

  Widget _nowPlaying() {
    final cur = _cur();
    final sessions = (_np?['sessions'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    final art = cur?['art'] != null ? _art[cur!['art']] : null;
    final dur = (cur?['dur'] as num?)?.toDouble() ?? 0;
    final pos = cur == null ? 0.0 : (_seekDrag ?? _pos(cur));
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (sessions.length > 1)
        SizedBox(
          height: 34,
          child: ListView(scrollDirection: Axis.horizontal, children: [
            for (final s in sessions)
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text('${s['status'] == 'playing' ? '▶ ' : ''}${s['app']}'),
                  selected: s['id'] == cur?['id'],
                  onSelected: (_) {
                    Fx.select();
                    setState(() => _npSel = s['id'] as String);
                  },
                ),
              ),
          ]),
        ),
      const SizedBox(height: 6),
      Row(children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Container(
            width: 64,
            height: 64,
            color: C.panel2,
            child: art != null ? Image.memory(art, fit: BoxFit.cover, gaplessPlayback: true) : const Center(child: Text('🎵', style: TextStyle(fontSize: 26))),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(cur == null ? 'Nothing playing' : ((cur['title'] as String).isEmpty ? 'Unknown title' : cur['title'] as String),
                maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
            Text(cur == null ? 'Play something on the laptop' : [cur['artist'], cur['album']].where((x) => (x as String).isNotEmpty).join(' — '),
                maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: C.muted, fontSize: 13)),
            if (cur != null) Text(cur['app'] as String, style: const TextStyle(color: C.accent, fontSize: 11)),
          ]),
        ),
      ]),
      if (cur != null && dur > 0)
        Row(children: [
          Text(_fmt(pos), style: const TextStyle(fontSize: 11, color: C.muted)),
          Expanded(
            child: Slider(
              value: pos.clamp(0, dur),
              max: dur,
              onChanged: cur['can_seek'] == true ? (v) => setState(() => _seekDrag = v) : null,
              onChangeEnd: (v) {
                cur['pos'] = v;
                _npAt = DateTime.now();
                _seekDrag = null;
                _npCmd('seek', pos: v);
              },
            ),
          ),
          Text(_fmt(dur), style: const TextStyle(fontSize: 11, color: C.muted)),
        ]),
      Row(children: [
        KeyButton(label: '⏮', fontSize: 22, height: 50, onPress: () => _npCmd('prev')),
        KeyButton(
            label: cur?['status'] == 'playing' ? '⏸' : '▶',
            fontSize: 22,
            height: 50,
            flex: 2,
            color: C.accent,
            onPress: () => _npCmd('play_pause')),
        KeyButton(label: '⏭', fontSize: 22, height: 50, onPress: () => _npCmd('next')),
      ]),
    ]);
  }

  // ---------- sliders ----------
  Widget _sliders() {
    final vol = (_volDrag ?? (_sys?['vol'] as num?)?.toDouble());
    final bright = (_brightDrag ?? (_sys?['bright'] as num?)?.toDouble());
    final muted = _sys?['muted'] == true;
    return Column(children: [
      Row(children: [
        IconButton(
          icon: Icon(muted ? Icons.volume_off_rounded : Icons.volume_up_rounded),
          onPressed: () => conn.send({'t': 'vol', 'mute': 'toggle'}),
        ),
        Expanded(
          child: Slider(
            value: (vol ?? 0).clamp(0, 100),
            max: 100,
            onChanged: vol == null
                ? null
                : (v) {
                    if ((v / 10).floor() != ((_volDrag ?? vol) / 10).floor()) Fx.select(); // tick every 10 %
                    setState(() => _volDrag = v);
                    if (DateTime.now().difference(_lastVolSend).inMilliseconds > 120) {
                      _lastVolSend = DateTime.now();
                      conn.send({'t': 'vol', 'v': v.round()});
                    }
                  },
            onChangeEnd: (v) {
              conn.send({'t': 'vol', 'v': v.round()});
              _volDrag = null;
            },
          ),
        ),
        SizedBox(width: 34, child: Text(vol == null ? '–' : '${vol.round()}', style: const TextStyle(color: C.muted))),
      ]),
      Row(children: [
        IconButton(icon: const Icon(Icons.brightness_low_rounded), onPressed: () => conn.send({'t': 'bright', 'up': false})),
        Expanded(
          child: bright == null
              ? const Text('Brightness: use − / +', style: TextStyle(color: C.muted, fontSize: 13))
              : Slider(
                  value: bright.clamp(0, 100),
                  max: 100,
                  onChanged: (v) {
                    if ((v / 10).floor() != ((_brightDrag ?? bright) / 10).floor()) Fx.select();
                    setState(() => _brightDrag = v);
                    if (DateTime.now().difference(_lastBrightSend).inMilliseconds > 300) {
                      _lastBrightSend = DateTime.now();
                      conn.send({'t': 'bright', 'v': v.round()});
                    }
                  },
                  onChangeEnd: (v) {
                    conn.send({'t': 'bright', 'v': v.round()});
                    _brightDrag = null;
                  },
                ),
        ),
        IconButton(icon: const Icon(Icons.brightness_high_rounded), onPressed: () => conn.send({'t': 'bright', 'up': true})),
      ]),
    ]);
  }

  // ---------- status ----------
  Widget _stat(String label, String value, double? frac, {String? sub, bool lowIsBad = false}) {
    Color col = C.ok;
    if (frac != null) {
      final p = frac * 100;
      if (lowIsBad ? p <= 15 : p >= 90) {
        col = C.bad;
      } else if (lowIsBad ? p <= 30 : p >= 70) {
        col = C.warn;
      }
    }
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(color: C.muted, fontSize: 12)),
        Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: LinearProgressIndicator(value: frac ?? 0, minHeight: 6, color: col, backgroundColor: const Color(0xFF2E3340)),
        ),
        if (sub != null) Padding(padding: const EdgeInsets.only(top: 3), child: Text(sub, style: const TextStyle(color: C.muted, fontSize: 11))),
      ]),
    );
  }

  Widget _statusRow() {
    final st = _status;
    if (st == null) return const Text('…', style: TextStyle(color: C.muted));
    final bat = st['battery'] as int?;
    final plugged = st['plugged'] == true;
    final left = st['secsleft'] as int?;
    String fmtLeft(int s) => s >= 3600 ? '${s ~/ 3600}h ${(s % 3600) ~/ 60}m left' : '${s ~/ 60}m left';
    return Row(children: [
      _stat(plugged ? '🔌 Battery' : '🔋 Battery', bat == null ? '—' : '$bat%', bat == null ? null : bat / 100,
          sub: bat == null ? 'no battery' : plugged ? (bat >= 100 ? 'Fully charged' : 'Charging') : (left != null ? fmtLeft(left) : 'On battery'),
          lowIsBad: true),
      const SizedBox(width: 10),
      _stat('🧠 CPU', '${st['cpu']}%', (st['cpu'] as num) / 100),
      const SizedBox(width: 10),
      _stat('💾 RAM', '${st['ram']}%', (st['ram'] as num) / 100, sub: '${st['ram_used']} / ${st['ram_total']} GB'),
    ]);
  }

  // ---------- clipboard ----------
  Future<void> _sendPhoneClipboard({required bool paste}) async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final text = data?.text ?? '';
    if (text.isEmpty) {
      if (mounted) toast(context, 'Phone clipboard is empty');
      return;
    }
    _sendClip(text, paste: paste);
  }

  bool _sendClip(String text, {bool paste = false}) {
    if (!conn.send({'t': 'clip_set', 'v': text, 'paste': paste})) return false;
    _lastPhoneClip = text;
    if (mounted) {
      setState(() {
        _clips.removeWhere((c) => c.$1 == text);
        _clips.insert(0, (text, false));
        if (_clips.length > 10) _clips.removeLast();
      });
    }
    return true;
  }

  /// Phone -> laptop auto-copy. Android only lets the app in front read the clipboard (no background
  /// watching), so whatever was copied in another app is sent when you come back to Fasway.
  Future<void> _syncPhoneClipboard() async {
    if (!widget.settings.clipAuto) return;
    await Future<void>.delayed(const Duration(milliseconds: 400)); // the window needs focus first
    if (!mounted || !widget.settings.clipAuto) return;
    final text = (await Clipboard.getData(Clipboard.kTextPlain))?.text ?? '';
    if (text.isEmpty || text == _lastPhoneClip) return;
    _sendClip(text); // the laptop answers with "Sent to laptop clipboard"
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _syncPhoneClipboard();
  }

  Widget _clipboard() => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          KeyButton(label: '📤 Send phone clipboard', fontSize: 13, height: 46, onPress: () => _sendPhoneClipboard(paste: false)),
          KeyButton(label: '📋 Paste on laptop', fontSize: 13, height: 46, onPress: () => _sendPhoneClipboard(paste: true)),
        ]),
        if (_clips.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('Copy on the laptop and it shows up here. With Auto-copy on, what you copy on the phone '
                'is sent to the laptop when you come back to Fasway.', style: TextStyle(color: C.muted, fontSize: 13)),
          ),
        for (final (text, fromLaptop) in _clips)
          Container(
            margin: const EdgeInsets.only(top: 6),
            padding: const EdgeInsets.fromLTRB(10, 6, 4, 6),
            decoration: BoxDecoration(color: C.panel2, borderRadius: BorderRadius.circular(10)),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(text, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13)),
                  Text(fromLaptop ? 'from laptop' : 'sent from phone', style: const TextStyle(color: C.muted, fontSize: 11)),
                ]),
              ),
              IconButton(
                tooltip: 'Copy',
                icon: const Icon(Icons.copy_rounded, size: 20),
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: text));
                  toast(context, 'Copied to phone');
                },
              ),
              IconButton(
                tooltip: 'Paste on laptop',
                icon: const Icon(Icons.content_paste_go_rounded, size: 20),
                onPressed: () => conn.send({'t': 'clip_set', 'v': text, 'paste': true}),
              ),
            ]),
          ),
        TextButton(onPressed: () => conn.send({'t': 'clip_get'}), child: const Text('Get current laptop clipboard')),
      ]);

  // ---------- power ----------
  Widget _power() {
    Widget b(String label, String a, {String? confirmText, bool danger = false}) => KeyButton(
          label: label,
          height: 46,
          color: danger ? const Color(0xFF3A1F24) : null,
          onPress: () async {
            if (confirmText != null && !await confirm(context, label, confirmText, ok: label, danger: danger)) return;
            if (conn.send({'t': 'power', 'a': a}) && mounted) toast(context, '$label sent');
          },
        );
    return Column(children: [
      Row(children: [b('🔒 Lock', 'lock'), b('🌑 Display off', 'display_off')]),
      Row(children: [
        b('😴 Sleep', 'sleep', confirmText: 'Put the laptop to sleep?'),
        b('🚪 Sign out', 'signout', confirmText: 'Sign out? Unsaved work will be lost.'),
      ]),
      Row(children: [
        b('🔄 Restart', 'restart', confirmText: 'Restart the laptop now? Unsaved work will be lost.', danger: true),
        b('⏻ Shut down', 'shutdown', confirmText: 'Shut down the laptop now? Unsaved work will be lost.', danger: true),
      ]),
    ]);
  }

  @override
  Widget build(BuildContext context) => ListView(children: [
        Panel(title: 'Laptop status', child: _statusRow()),
        Panel(title: 'Media', child: Column(children: [_nowPlaying(), const SizedBox(height: 4), _sliders()])),
        Panel(
          title: 'Clipboard',
          trailing: Row(mainAxisSize: MainAxisSize.min, children: [
            const Text('Auto-copy', style: TextStyle(fontSize: 12, color: C.muted)),
            Switch(
                value: widget.settings.clipAuto,
                onChanged: (v) {
                  Fx.select();
                  setState(() => widget.settings.set('clipAuto', v));
                }),
          ]),
          child: _clipboard(),
        ),
        Panel(title: 'Power', child: _power()),
      ]);
}
