import 'dart:io';
import 'dart:typed_data';

import 'laptop.dart';

/// Wake-on-LAN: wakes a sleeping laptop with a "magic packet" sent on the Wi-Fi to its network card
/// (the laptop told the phone the card's address the last time it was connected).
class Wake {
  /// 6 × 0xFF, then the card address 16 times. Null if [mac] isn't a card address.
  static Uint8List? magicPacket(String mac) {
    final hex = mac.replaceAll(RegExp(r'[^0-9a-fA-F]'), '');
    if (hex.length != 12) return null;
    final bytes = [for (var i = 0; i < 12; i += 2) int.parse(hex.substring(i, i + 2), radix: 16)];
    return Uint8List.fromList([...List.filled(6, 0xFF), for (var i = 0; i < 16; i++) ...bytes]);
  }

  static bool canWake(Laptop l) => magicPacket(l.mac) != null;

  /// Sends the packet a few times, to the laptop's network and to everyone on this Wi-Fi, on the usual
  /// ports. Returns false if this laptop's card address isn't known yet.
  static Future<bool> send(Laptop l) async {
    final packet = magicPacket(l.mac);
    if (packet == null) return false;
    final targets = {if (l.bcast.isNotEmpty) l.bcast, '255.255.255.255', ...l.ips};
    final socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
    try {
      socket.broadcastEnabled = true;
      for (var round = 0; round < 3; round++) {
        for (final t in targets) {
          final addr = InternetAddress.tryParse(t);
          if (addr == null || addr.type != InternetAddressType.IPv4) continue;
          for (final port in const [9, 7]) {
            try {
              socket.send(packet, addr, port);
            } catch (_) {} // one address unreachable: the others may still work
          }
        }
        await Future<void>.delayed(const Duration(milliseconds: 150));
      }
    } finally {
      socket.close();
    }
    return true;
  }
}
