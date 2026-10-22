import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../core/app_state.dart';
import '../core/laptop.dart';
import 'common.dart';

/// First run (or "pair another laptop"): scan the QR code shown in the Fasway window.
class ConnectScreen extends StatelessWidget {
  const ConnectScreen(this.state, {super.key, this.canGoBack = false});
  final AppState state;
  final bool canGoBack;

  Future<void> _scan(BuildContext context) async {
    final laptop = await Navigator.push<Laptop>(context, MaterialPageRoute(builder: (_) => const QrScanPage()));
    if (laptop == null) return;
    state.pair(laptop);
    if (canGoBack && context.mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: canGoBack ? AppBar(title: const Text('Pair a laptop'), backgroundColor: C.bg) : null,
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              const Spacer(),
              const Appear(child: _PulsingLogo()),
              const SizedBox(height: 16),
              const Appear(
                delay: Duration(milliseconds: 60),
                child: Text('Fasway',
                    textAlign: TextAlign.center, style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700)),
              ),
              const SizedBox(height: 8),
              const Text(
                'Control your laptop from this phone.\nOpen Fasway on the laptop and scan its QR code.',
                textAlign: TextAlign.center,
                style: TextStyle(color: C.muted, height: 1.5),
              ),
              const SizedBox(height: 28),
              Appear(
                delay: const Duration(milliseconds: 140),
                child: FilledButton.icon(
                onPressed: () {
                  Fx.tap();
                  _scan(context);
                },
                icon: const Icon(Icons.qr_code_scanner_rounded),
                label: const Padding(padding: EdgeInsets.all(14), child: Text('Scan QR code', style: TextStyle(fontSize: 16))),
              ),
              ),
              const SizedBox(height: 24),
              ListenableBuilder(
                listenable: state.discovery,
                builder: (_, _) {
                  final found = state.discovery.found.values.toList();
                  if (found.isEmpty) {
                    return const Text('Looking for Fasway laptops on this Wi-Fi…',
                        textAlign: TextAlign.center, style: TextStyle(color: C.muted, fontSize: 13));
                  }
                  return Column(children: [
                    const Text('Found on this Wi-Fi (scan its QR once to pair):',
                        style: TextStyle(color: C.muted, fontSize: 13)),
                    for (final f in found)
                      Appear(key: ValueKey(f.name), child: ListTile(
                        leading: const Icon(Icons.laptop_windows_rounded, color: C.accent),
                        title: Text(f.name),
                        subtitle: Text('${f.ip}:${f.port}', style: const TextStyle(color: C.muted)),
                        dense: true,
                      )),
                  ]);
                },
              ),
              const Spacer(),
            ]),
          ),
        ),
      );
}

class QrScanPage extends StatefulWidget {
  const QrScanPage({super.key});
  @override
  State<QrScanPage> createState() => _QrScanPageState();
}

class _QrScanPageState extends State<QrScanPage> {
  bool _done = false;
  String? _hint;

  void _onDetect(BarcodeCapture capture) {
    if (_done) return;
    for (final b in capture.barcodes) {
      final raw = b.rawValue;
      if (raw == null) continue;
      final laptop = Laptop.fromQr(raw);
      if (laptop != null) {
        _done = true;
        Navigator.pop(context, laptop);
        return;
      }
      setState(() => _hint = "That's not a Fasway QR code");
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Scan the QR on your laptop'), backgroundColor: Colors.black),
        backgroundColor: Colors.black,
        body: Stack(children: [
          MobileScanner(onDetect: _onDetect),
          Center(
            child: Container(
              width: 250,
              height: 250,
              decoration: BoxDecoration(border: Border.all(color: C.accent, width: 3), borderRadius: BorderRadius.circular(20)),
            ),
          ),
          if (_hint != null)
            Positioned(
              left: 0,
              right: 0,
              bottom: 60,
              child: Text(_hint!, textAlign: TextAlign.center, style: const TextStyle(color: C.warn, fontSize: 15)),
            ),
        ]),
      );
}

/// The laptop icon with a soft "searching" glow that breathes.
class _PulsingLogo extends StatefulWidget {
  const _PulsingLogo();
  @override
  State<_PulsingLogo> createState() => _PulsingLogoState();
}

class _PulsingLogoState extends State<_PulsingLogo> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1800))..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (_, child) {
          final v = Curves.easeInOut.transform(_c.value);
          return Container(
            width: 120,
            height: 120,
            alignment: Alignment.center,
            decoration: BoxDecoration(shape: BoxShape.circle, boxShadow: [
              BoxShadow(color: C.accent.withValues(alpha: 0.10 + 0.18 * v), blurRadius: 30 + 20 * v, spreadRadius: 2 + 8 * v),
            ]),
            child: child,
          );
        },
        child: const Icon(Icons.laptop_chromebook_rounded, size: 72, color: C.accent),
      );
}