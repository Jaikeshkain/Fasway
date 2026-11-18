import 'package:flutter/services.dart';

/// "Confirm it's you" with the phone's fingerprint, face or screen lock (PhoneLock.kt) before risky
/// laptop actions: restart, shut down, sign out, sleep, quick actions that run a command, and allowing
/// an assistant step. Someone holding your unlocked phone then can't do them.
class PhoneLock {
  static const _ch = MethodChannel('fasway/lock');

  /// The "Confirm it's you" setting (Settings keeps this in step).
  static bool enabled = true;

  /// After a successful check, more risky actions within this time don't ask again.
  static const grace = Duration(seconds: 60);
  static DateTime? _okUntil;

  static Future<bool> check(String reason) async {
    if (!enabled) return true;
    if (_okUntil != null && DateTime.now().isBefore(_okUntil!)) return true;
    try {
      final ok = await _ch.invokeMethod<bool>('confirm', {'reason': reason}) ?? false;
      if (ok) _okUntil = DateTime.now().add(grace);
      return ok;
    } on MissingPluginException {
      return true; // no Android side (tests, other platforms)
    } catch (_) {
      return false;
    }
  }

  /// Does running this quick action run a shell command?
  static bool runsCommand(Map a) {
    if (a['type'] == 'command') return true;
    if (a['type'] != 'macro') return false;
    return '${a['value'] ?? ''}'
        .split('\n')
        .any((l) => const {'cmd', 'run'}.contains(l.trim().split(' ').first.toLowerCase()));
  }
}
