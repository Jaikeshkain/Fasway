import 'package:fasway/core/phone_lock.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const ch = MethodChannel('fasway/lock');
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  test('which quick actions run a command', () {
    expect(PhoneLock.runsCommand({'type': 'command', 'value': 'shutdown /h'}), isTrue);
    expect(PhoneLock.runsCommand({'type': 'macro', 'value': 'key win+r\nCMD echo hi'}), isTrue);
    expect(PhoneLock.runsCommand({'type': 'macro', 'value': 'key win+r\ntype cmd'}), isFalse);
    expect(PhoneLock.runsCommand({'type': 'open', 'value': 'cmd'}), isFalse);
  });

  test('asks the phone lock, then not again for a minute; a "no" stops the action', () async {
    var asked = 0;
    var answer = false;
    messenger.setMockMethodCallHandler(ch, (call) async {
      asked++;
      expect(call.arguments['reason'], 'Restart');
      return answer;
    });
    PhoneLock.enabled = true;
    expect(await PhoneLock.check('Restart'), isFalse);
    answer = true;
    expect(await PhoneLock.check('Restart'), isTrue);
    expect(await PhoneLock.check('Restart'), isTrue); // within the grace minute
    expect(asked, 2);
    messenger.setMockMethodCallHandler(ch, null);
  });

  test('turned off: never asks', () async {
    PhoneLock.enabled = false;
    messenger.setMockMethodCallHandler(ch, (call) async => fail('should not ask'));
    expect(await PhoneLock.check('Shut down'), isTrue);
    messenger.setMockMethodCallHandler(ch, null);
    PhoneLock.enabled = true;
  });
}
