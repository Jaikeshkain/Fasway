import 'package:flutter/material.dart';

import '../core/app_state.dart';
import 'common.dart';

/// Touchpad speed, scrolling, screen quality, haptics, and the paired laptop.
void showSettings(BuildContext context, AppState s, {required VoidCallback onPairNew}) {
  showModalBottomSheet(
    context: context,
    backgroundColor: C.panel,
    isScrollControlled: true,
    showDragHandle: true,
    sheetAnimationStyle: const AnimationStyle(duration: Motion.slow, reverseDuration: Motion.medium),
    builder: (c) => ListenableBuilder(
      listenable: s.settings,
      builder: (c, _) {
        final st = s.settings;
        Widget slider(String label, String key, double value, double min, double max) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('$label  ${value.toStringAsFixed(1)}', style: const TextStyle(color: C.muted, fontSize: 14)),
                Slider(value: value, min: min, max: max, divisions: ((max - min) * 10).round(), onChanged: (v) {
                  if (v != value) Fx.select(); // a tick per step
                  st.set(key, v);
                }),
              ],
            );
        final l = s.laptop;
        return SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              const Text('Settings', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
              const SizedBox(height: 12),
              slider('Pointer speed', 'speed', st.speed, 0.5, 4),
              slider('Acceleration', 'accel', st.accel, 0, 3),
              slider('Scroll speed', 'scrollSpeed', st.scrollSpeed, 0.5, 6),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Natural scrolling'),
                value: st.natural,
                onChanged: (v) {
                  Fx.select();
                  st.set('natural', v);
                },
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Vibration'),
                subtitle: const Text('Haptic feedback on taps, keys and clicks', style: TextStyle(color: C.muted, fontSize: 12)),
                value: st.haptics,
                onChanged: (v) {
                  st.set('haptics', v);
                  Fx.select(); // after the change: turning it on gives a buzz
                },
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('"Send clipboard" notification'),
                subtitle: const Text(
                    'Copied something in another app? Tap Send clipboard in the notification shade. '
                    'There is also a "Send clipboard" Quick Settings tile.',
                    style: TextStyle(color: C.muted, fontSize: 12)),
                value: st.clipNotify,
                onChanged: (v) {
                  Fx.select();
                  st.set('clipNotify', v);
                },
              ),
              const Text('Screen preview quality', style: TextStyle(color: C.muted, fontSize: 14)),
              DropdownButton<String>(
                value: st.screenQuality,
                isExpanded: true,
                items: const [
                  DropdownMenuItem(value: 'low', child: Text('Low – smooth on weak Wi-Fi')),
                  DropdownMenuItem(value: 'medium', child: Text('Medium (720p, 30 fps)')),
                  DropdownMenuItem(value: 'high', child: Text('High (1080p, 30 fps)')),
                ],
                onChanged: (v) {
                  Fx.select();
                  st.set('screenQuality', v!);
                },
              ),
              const Divider(height: 28),
              if (l != null) ...[
                Text('Paired laptop', style: const TextStyle(color: C.muted, fontSize: 14)),
                const SizedBox(height: 4),
                Text('${l.host}:${l.port}', style: const TextStyle(fontSize: 15)),
                Text(
                  'Connected via ${s.connection?.address ?? '—'} · certificate ${l.fp.isEmpty ? 'not pinned yet' : '${l.fp.substring(0, 12)}…'}',
                  style: const TextStyle(color: C.muted, fontSize: 12),
                ),
                const SizedBox(height: 8),
              ],
              Row(children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () {
                      Navigator.pop(c);
                      onPairNew();
                    },
                    child: const Text('Pair another laptop'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(foregroundColor: C.bad),
                    onPressed: () async {
                      if (await confirm(c, 'Forget laptop', 'Forget this laptop? You will need to scan its QR code again.',
                          ok: 'Forget', danger: true)) {
                        if (c.mounted) Navigator.pop(c);
                        s.forget();
                      }
                    },
                    child: const Text('Forget laptop'),
                  ),
                ),
              ]),
              const SizedBox(height: 8),
              Text('This phone: ${s.identity.name}', style: const TextStyle(color: C.muted, fontSize: 12)),
              const Text('Fasway v$appVersion (build $appBuild)', style: TextStyle(color: C.muted, fontSize: 12)),
            ]),
          ),
        );
      },
    ),
  );
}
