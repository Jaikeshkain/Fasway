import 'dart:convert';

/// A laptop running Fasway that this phone has paired with (from its QR code).
class Laptop {
  /// Stable id of the laptop's Fasway install (also announced over mDNS as `fasway-<id>.local`).
  final String id;

  /// Host from the QR code: `fasway-<id>.local` or an IP address.
  final String host;
  final int port;

  /// Pairing code from the QR. Only used to *ask* for pairing; after approval the phone logs in
  /// with its own key.
  final String token;

  /// SHA-256 (hex) of the laptop's self-signed certificate. The app trusts exactly this
  /// certificate, so there is no browser-style "Not secure" warning and no impostor risk.
  /// Empty for QR codes from older Fasway versions: then it is learned on first connect.
  String fp;

  /// Last addresses this laptop was reached on (tried when discovery is slow).
  List<String> ips;

  String name;

  Laptop({
    required this.id,
    required this.host,
    required this.port,
    required this.token,
    this.fp = '',
    List<String>? ips,
    String? name,
  })  : ips = ips ?? [],
        name = name ?? 'Laptop';

  /// Parses `https://host:port/#t=TOKEN&id=ID&fp=SHA256` from the Fasway QR code.
  static Laptop? fromQr(String text) {
    final uri = Uri.tryParse(text.trim());
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) return null;
    final frag = Uri.splitQueryString(uri.fragment);
    final token = frag['t'] ?? '';
    if (token.isEmpty) return null;
    final host = uri.host;
    var id = frag['id'] ?? '';
    if (id.isEmpty) {
      final m = RegExp(r'^fasway-([a-z0-9]+)\.local$').firstMatch(host);
      id = m?.group(1) ?? host; // older QR: fall back to the host itself
    }
    final isIp = RegExp(r'^\d+\.\d+\.\d+\.\d+$').hasMatch(host);
    return Laptop(
      id: id,
      host: host,
      port: uri.hasPort ? uri.port : 8443,
      token: token,
      fp: (frag['fp'] ?? '').toLowerCase(),
      ips: isIp ? [host] : [],
    );
  }

  Map<String, dynamic> toJson() =>
      {'id': id, 'host': host, 'port': port, 'token': token, 'fp': fp, 'ips': ips, 'name': name};

  static Laptop fromJson(Map<String, dynamic> j) => Laptop(
        id: j['id'] as String,
        host: j['host'] as String,
        port: j['port'] as int,
        token: j['token'] as String,
        fp: (j['fp'] ?? '') as String,
        ips: List<String>.from(j['ips'] ?? const []),
        name: j['name'] as String?,
      );

  String encode() => jsonEncode(toJson());
  static Laptop decode(String s) => fromJson(jsonDecode(s) as Map<String, dynamic>);
}
