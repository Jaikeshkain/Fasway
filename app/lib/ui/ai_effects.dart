import 'dart:math' as math;

import 'package:flutter/material.dart';

/// The assistant's look: a blue-violet-pink gradient, glows that drift, a sparkle that turns while it
/// works. Everything here is painted (no images, no blur filters), so it stays light on the phone.
class Ai {
  static const blue = Color(0xFF4F8CFF);
  static const violet = Color(0xFF9B6BFF);
  static const pink = Color(0xFFFF6FB5);
  static const cyan = Color(0xFF3DDCFF);
  static const gradient = LinearGradient(colors: [blue, violet, pink]);
}

class GradientText extends StatelessWidget {
  const GradientText(this.text, {super.key, required this.style, this.textAlign});
  final String text;
  final TextStyle style;
  final TextAlign? textAlign;

  @override
  Widget build(BuildContext context) => ShaderMask(
        blendMode: BlendMode.srcIn,
        shaderCallback: (r) => Ai.gradient.createShader(Offset.zero & r.size),
        child: Text(text, style: style, textAlign: textAlign),
      );
}

/// The ✦ mark. While [spinning] (the assistant is working) it turns, pulses and its colours flow.
class AiSparkle extends StatefulWidget {
  const AiSparkle({super.key, this.size = 22, this.spinning = false});
  final double size;
  final bool spinning;
  @override
  State<AiSparkle> createState() => _AiSparkleState();
}

class _AiSparkleState extends State<AiSparkle> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2400));

  @override
  void initState() {
    super.initState();
    if (widget.spinning) _c.repeat();
  }

  @override
  void didUpdateWidget(AiSparkle old) {
    super.didUpdateWidget(old);
    if (widget.spinning && !_c.isAnimating) {
      _c.repeat();
    } else if (!widget.spinning && _c.isAnimating) {
      _c.animateTo(1, duration: const Duration(milliseconds: 300)).then((_) => _c.value = 0);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          final t = _c.value;
          return Transform.rotate(
            angle: t * 2 * math.pi,
            child: Transform.scale(
              scale: 1 + 0.12 * math.sin(t * 4 * math.pi),
              child: ShaderMask(
                blendMode: BlendMode.srcIn,
                shaderCallback: (r) => LinearGradient(
                  colors: const [Ai.blue, Ai.violet, Ai.pink, Ai.blue],
                  transform: GradientRotation(t * 2 * math.pi),
                ).createShader(Offset.zero & r.size),
                child: Icon(Icons.auto_awesome_rounded, size: widget.size, color: Colors.white),
              ),
            ),
          );
        },
      );
}

/// Text with light sweeping across it: "thinking".
class Shimmer extends StatefulWidget {
  const Shimmer(this.text, {super.key, this.style = const TextStyle(fontSize: 15)});
  final String text;
  final TextStyle style;
  @override
  State<Shimmer> createState() => _ShimmerState();
}

class _ShimmerState extends State<Shimmer> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1500))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, child) => ShaderMask(
          blendMode: BlendMode.srcIn,
          shaderCallback: (r) {
            final x = -1 + 3 * _c.value; // the bright band sweeps from left to right
            return LinearGradient(
              colors: const [Color(0xFF8B90A0), Colors.white, Color(0xFFB79BFF), Color(0xFF8B90A0)],
              stops: [(x - 0.4).clamp(0.0, 1.0), x.clamp(0.0, 1.0), (x + 0.15).clamp(0.0, 1.0), (x + 0.5).clamp(0.0, 1.0)],
            ).createShader(Offset.zero & r.size);
          },
          child: child,
        ),
        child: Text(widget.text, style: widget.style),
      );
}

/// Soft coloured light drifting behind the page; stronger while the assistant is busy.
class AuraBackground extends StatefulWidget {
  const AuraBackground({super.key, this.busy = false});
  final bool busy;
  @override
  State<AuraBackground> createState() => _AuraBackgroundState();
}

class _AuraBackgroundState extends State<AuraBackground> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(seconds: 14))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(
        child: TweenAnimationBuilder<double>(
          tween: Tween(end: widget.busy ? 0.30 : 0.13),
          duration: const Duration(milliseconds: 700),
          builder: (context, strength, _) => CustomPaint(painter: _AuraPainter(_c, strength), size: Size.infinite),
        ),
      );
}

class _AuraPainter extends CustomPainter {
  _AuraPainter(this.anim, this.strength) : super(repaint: anim);
  final Animation<double> anim;
  final double strength;

  @override
  void paint(Canvas canvas, Size size) {
    final t = anim.value * 2 * math.pi;
    for (final (color, phase) in [(Ai.blue, 0.0), (Ai.violet, 2.1), (Ai.pink, 4.2)]) {
      final a = t + phase;
      // the glow lives near the bottom of the page, like a light behind the input
      final center = Offset(size.width * (0.5 + 0.42 * math.sin(a)), size.height * (0.82 + 0.16 * math.cos(a * 0.7)));
      final r = size.width * 0.8;
      final paint = Paint()
        ..shader = RadialGradient(colors: [color.withValues(alpha: strength), color.withValues(alpha: 0)])
            .createShader(Rect.fromCircle(center: center, radius: r));
      canvas.drawCircle(center, r, paint);
    }
  }

  @override
  bool shouldRepaint(_AuraPainter old) => old.strength != strength;
}

/// Live conversation's centrepiece: coloured light that breathes while listening, swirls while
/// thinking and pulses while speaking.
class LiveOrb extends StatefulWidget {
  const LiveOrb({super.key, required this.phase, this.size = 200});
  final String phase; // listening | working | speaking | other
  final double size;
  @override
  State<LiveOrb> createState() => _LiveOrbState();
}

class _LiveOrbState extends State<LiveOrb> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(seconds: 4))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(
        child: SizedBox.square(
          dimension: widget.size,
          child: CustomPaint(painter: _OrbPainter(_c, widget.phase)),
        ),
      );
}

class _OrbPainter extends CustomPainter {
  _OrbPainter(this.anim, this.phase) : super(repaint: anim);
  final Animation<double> anim;
  final String phase;

  @override
  void paint(Canvas canvas, Size size) {
    final t = anim.value * 2 * math.pi;
    final c = size.center(Offset.zero);
    final base = size.shortestSide / 2 * 0.55;
    final (speed, spread, pulse) = switch (phase) {
      'listening' => (1.0, 0.18, 0.08 * math.sin(t * 2)), // slow breathing
      'working' => (3.0, 0.38, 0.04 * math.sin(t * 6)), // swirling
      'speaking' => (1.5, 0.22, 0.14 * math.sin(t * 8).abs()), // pulsing with the voice
      _ => (0.5, 0.12, 0.0),
    };
    final glow = Paint()..blendMode = BlendMode.plus;
    for (final (i, color) in [Ai.blue, Ai.violet, Ai.pink, Ai.cyan].indexed) {
      final a = t * speed + i * math.pi / 2;
      final center = c + Offset(math.cos(a), math.sin(a)) * base * spread;
      final r = base * (1.05 + pulse + 0.06 * math.sin(t * 3 + i));
      glow.shader = RadialGradient(colors: [color.withValues(alpha: 0.75), color.withValues(alpha: 0)])
          .createShader(Rect.fromCircle(center: center, radius: r));
      canvas.drawCircle(center, r, glow);
    }
    // a bright core
    final core = base * (0.38 + pulse * 0.6);
    canvas.drawCircle(
        c,
        core,
        Paint()
          ..shader = RadialGradient(colors: [Colors.white.withValues(alpha: 0.85), Colors.white.withValues(alpha: 0)])
              .createShader(Rect.fromCircle(center: c, radius: core)));
  }

  @override
  bool shouldRepaint(_OrbPainter old) => old.phase != phase;
}
