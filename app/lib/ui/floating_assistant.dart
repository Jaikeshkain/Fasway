import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/agent.dart';
import '../core/settings.dart';
import 'ai_effects.dart';
import 'common.dart';

/// The ✦ bubble that floats over every screen of the app. Tap: the assistant's voice bar. Drag: put it
/// wherever it's out of the way; let go and it bounces to the nearest side (remembered).
class FloatingAssistant extends StatefulWidget {
  const FloatingAssistant({super.key, required this.agent, required this.settings, required this.onTap});
  final AgentController agent;
  final Settings settings;
  final VoidCallback onTap;

  static const size = 56.0;

  @override
  State<FloatingAssistant> createState() => _FloatingAssistantState();
}

class _FloatingAssistantState extends State<FloatingAssistant> with SingleTickerProviderStateMixin {
  late final _glow = AnimationController(vsync: this, duration: const Duration(milliseconds: 2600))..repeat();
  Offset? _drag; // while being dragged: where it is
  static const _margin = 10.0;

  @override
  void dispose() {
    _glow.dispose();
    super.dispose();
  }

  void _settle(Size area) {
    final p = _drag!;
    final left = p.dx + FloatingAssistant.size / 2 < area.width / 2;
    final top = (p.dy / (area.height - FloatingAssistant.size)).clamp(0.0, 1.0);
    Fx.select();
    widget.settings.set('fabLeft', left);
    widget.settings.set('fabY', top);
    setState(() => _drag = null);
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, box) {
        final area = box.biggest;
        const s = FloatingAssistant.size;
        final maxY = math.max(0.0, area.height - s - _margin);
        final restX = widget.settings.fabLeft ? _margin : area.width - s - _margin;
        final restY = (widget.settings.fabY * (area.height - s)).clamp(_margin, maxY);
        final pos = _drag ?? Offset(restX, restY);
        return Stack(children: [
          AnimatedPositioned(
            // following the finger: no delay; let go: bounce to the side
            duration: _drag != null ? Duration.zero : Motion.bounceTime,
            curve: Motion.bounce,
            left: pos.dx,
            top: pos.dy,
            child: GestureDetector(
              onPanStart: (_) => setState(() => _drag = pos),
              onPanUpdate: (d) => setState(() {
                final p = (_drag ?? pos) + d.delta;
                _drag = Offset(p.dx.clamp(0.0, area.width - s), p.dy.clamp(0.0, area.height - s));
              }),
              onPanEnd: (_) => _settle(area),
              onPanCancel: () => _drag == null ? null : _settle(area),
              child: Tooltip(
                message: 'Ask the assistant',
                child: Pressable(
                  onTap: widget.onTap,
                  scale: 0.85,
                  child: ListenableBuilder(listenable: widget.agent, builder: (context, _) => _bubble()),
                ),
              ),
            ),
          ),
        ]);
      });

  Widget _bubble() {
    final waiting = widget.agent.approvals.length;
    final busy = widget.agent.activeTask != null;
    return AnimatedBuilder(
      animation: _glow,
      builder: (context, child) {
        final t = _glow.value * 2 * math.pi;
        return Container(
          width: FloatingAssistant.size,
          height: FloatingAssistant.size,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: SweepGradient(colors: const [Ai.blue, Ai.violet, Ai.pink, Ai.blue], transform: GradientRotation(t)),
            boxShadow: [
              BoxShadow(
                color: Ai.violet.withValues(alpha: busy ? 0.75 : 0.45 + 0.1 * math.sin(t)),
                blurRadius: busy ? 26 : 16 + 4 * math.sin(t),
                spreadRadius: -2,
              ),
            ],
          ),
          child: child,
        );
      },
      child: Badge(
        isLabelVisible: waiting > 0,
        label: Text('$waiting'),
        backgroundColor: C.warn,
        child: Center(
          child: Container(
            width: FloatingAssistant.size - 6,
            height: FloatingAssistant.size - 6,
            decoration: const BoxDecoration(shape: BoxShape.circle, color: Color(0xEE14161C)),
            child: Center(child: AiSparkle(size: 26, spinning: busy)),
          ),
        ),
      ),
    );
  }
}
