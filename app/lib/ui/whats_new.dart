import 'package:flutter/material.dart';

import 'ai_effects.dart';
import 'common.dart';

/// "What's new": shown once after an update (and any time from Settings), so new features get found.
/// Each line can be tried straight away.
Future<void> showWhatsNew(BuildContext context, {VoidCallback? onAssistant, VoidCallback? onLive, VoidCallback? onScreen}) {
  final items = [
    (Icons.nights_stay_rounded, 'Routines', 'Say "good night" or "study mode": several steps at once, free. Make your own in Apps, or ask ✦.', onAssistant),
    (Icons.slideshow_rounded, 'Presentation remote', 'Apps → Presentation remote: big Next, volume buttons as a clicker, timer, laser.', null),
    (Icons.bedtime_rounded, 'Wake your laptop', 'Laptop asleep? Tap Wake laptop when it isn\'t reachable (needs Wake-on-LAN on).', null),
    (Icons.fingerprint_rounded, 'Confirm it\'s you', 'Restart, shut down and commands ask for your fingerprint first.', null),
    (Icons.graphic_eq_rounded, 'Live conversation', 'Just talk: it listens, answers aloud, and listens again until you close it.', onLive),
  ];
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (c) => Container(
      constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(c).height * 0.88),
      decoration: BoxDecoration(
        color: C.bg,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
        border: Border.all(color: Ai.violet.withValues(alpha: 0.35)),
      ),
      child: Stack(children: [
        const Positioned.fill(child: ClipRRect(borderRadius: BorderRadius.vertical(top: Radius.circular(28)), child: AuraBackground(busy: true))),
        SafeArea(
          top: false,
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(22, 24, 22, 16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Appear(child: AiSparkle(size: 34, spinning: true)),
              const SizedBox(height: 10),
              const Appear(
                delay: Duration(milliseconds: 60),
                child: GradientText('What\'s new', style: TextStyle(fontSize: 32, fontWeight: FontWeight.w800, height: 1.1)),
              ),
              Appear(
                delay: const Duration(milliseconds: 100),
                child: Text('Fasway $appVersion', style: const TextStyle(color: C.muted, letterSpacing: 1)),
              ),
              const SizedBox(height: 18),
              for (final (i, (icon, title, text, onTry)) in items.indexed)
                Appear(
                  delay: Duration(milliseconds: 160 + 70 * i),
                  child: _Feature(
                    icon: icon,
                    title: title,
                    text: text,
                    onTry: onTry == null
                        ? null
                        : () {
                            Navigator.pop(c);
                            onTry();
                          },
                  ),
                ),
              const SizedBox(height: 10),
              Appear(
                delay: Duration(milliseconds: 160 + 70 * items.length),
                child: Pressable(
                  onTap: () => Navigator.pop(c),
                  child: Container(
                    height: 52,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      gradient: Ai.gradient,
                      borderRadius: BorderRadius.circular(18),
                      boxShadow: [BoxShadow(color: Ai.violet.withValues(alpha: 0.45), blurRadius: 20, spreadRadius: -4)],
                    ),
                    child: const Text('Let\'s go', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: Colors.white)),
                  ),
                ),
              ),
            ]),
          ),
        ),
      ]),
    ),
  );
}

class _Feature extends StatelessWidget {
  const _Feature({required this.icon, required this.title, required this.text, this.onTry});
  final IconData icon;
  final String title, text;
  final VoidCallback? onTry;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              gradient: LinearGradient(colors: [Ai.blue.withValues(alpha: 0.25), Ai.pink.withValues(alpha: 0.2)]),
              border: Border.all(color: Ai.violet.withValues(alpha: 0.4)),
            ),
            child: ShaderMask(
              blendMode: BlendMode.srcIn,
              shaderCallback: (r) => Ai.gradient.createShader(Offset.zero & r.size),
              child: Icon(icon, color: Colors.white, size: 22),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 2),
              Text(text, style: const TextStyle(color: C.muted, fontSize: 13.5, height: 1.35)),
            ]),
          ),
          if (onTry != null)
            Padding(
              padding: const EdgeInsets.only(left: 6),
              child: TextButton(onPressed: onTry, child: const Text('Try it')),
            ),
        ]),
      );
}
