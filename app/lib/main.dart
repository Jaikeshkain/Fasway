import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'core/app_state.dart';
import 'ui/common.dart';
import 'ui/connect_screen.dart';
import 'ui/home_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    systemNavigationBarColor: Color(0xFF0C0E12),
  ));
  // Show the app immediately; startup work happens behind a loading screen and any failure is
  // shown on screen (before, a failed startup step left the phone stuck on the launch logo).
  runApp(const FaswayApp());
}

class FaswayApp extends StatefulWidget {
  const FaswayApp({super.key});
  @override
  State<FaswayApp> createState() => _FaswayAppState();
}

class _FaswayAppState extends State<FaswayApp> {
  AppState? _state;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final s = await AppState.load().timeout(const Duration(seconds: 20));
      if (mounted) setState(() => _state = s);
    } catch (e, st) {
      debugPrint('startup failed: $e\n$st');
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _state;
    return MaterialApp(
      title: 'Fasway',
      debugShowCheckedModeBanner: false,
      theme: faswayTheme(),
      home: s != null
          ? ListenableBuilder(
              listenable: s,
              builder: (_, _) => s.laptop == null ? ConnectScreen(s) : HomeScreen(s),
            )
          : _Boot(error: _error, onRetry: _load),
    );
  }
}

class _Boot extends StatelessWidget {
  const _Boot({required this.error, required this.onRetry});
  final Object? error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(22),
                child: Image.asset('assets/icon.png', width: 96, height: 96),
              ),
              const SizedBox(height: 20),
              if (error == null) ...[
                const SizedBox(width: 28, height: 28, child: CircularProgressIndicator(strokeWidth: 3)),
                const SizedBox(height: 14),
                const Text('Starting…', style: TextStyle(color: C.muted)),
              ] else ...[
                const Text('Fasway could not start', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                const SizedBox(height: 10),
                SelectableText('$error', textAlign: TextAlign.center, style: const TextStyle(color: C.muted, fontSize: 13)),
                const SizedBox(height: 18),
                FilledButton(onPressed: onRetry, child: const Text('Try again')),
              ],
            ]),
          ),
        ),
      );
}
