import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import 'connection.dart';

enum TransferState { waiting, running, done, failed }

class Transfer {
  Transfer(this.name, this.size, {required this.toLaptop});
  String name;
  final bool toLaptop;
  final int size; // bytes, 0 = unknown
  int done = 0;
  TransferState state = TransferState.waiting;
  String? error;
  String? saved; // received file on the phone (content:// uri or path), for opening

  double? get progress => size > 0 ? (done / size).clamp(0.0, 1.0) : null;
}

/// File sharing with the laptop.
///
/// * Phone -> laptop: picked files are uploaded over HTTPS (pinned certificate, this phone's key);
///   the laptop saves them in Downloads\Fasway.
/// * Laptop -> phone: files dropped on the Fasway window arrive as a `file_offer`; they are downloaded
///   and saved in the phone's Downloads/Fasway.
///
/// One transfer at a time, in order.
class FileTransfers extends ChangeNotifier {
  FileTransfers(this.conn) {
    _sub = conn.messages.listen(_onMessage);
  }

  final Connection conn;
  late final StreamSubscription _sub;
  final List<Transfer> items = []; // newest first
  void Function(String text)? onNotice; // short messages for a toast

  static const _native = MethodChannel('fasway/files');
  Future<void> _chain = Future.value();
  DateTime _lastTick = DateTime(0);
  bool _disposed = false;

  bool get busy => items.any((t) => t.state == TransferState.running || t.state == TransferState.waiting);

  void _onMessage(Map<String, dynamic> m) {
    if (m['t'] != 'file_offer') return;
    final files = (m['files'] as List).cast<Map<String, dynamic>>();
    if (files.isEmpty) return;
    onNotice?.call(files.length == 1 ? '📥 Receiving ${files.first['name']}' : '📥 Receiving ${files.length} files');
    for (final f in files) {
      final t = Transfer(f['name'] as String, (f['size'] as num?)?.toInt() ?? 0, toLaptop: false);
      _add(t);
      _run(t, () => _download(f['id'] as String, t));
    }
  }

  /// Pick files on the phone and send them to the laptop.
  Future<void> pickAndSend() async {
    final files = await FilePicker.pickFiles(dialogTitle: 'Send to laptop');
    for (final f in files) {
      final t = Transfer(f.name, await f.length() ?? 0, toLaptop: true);
      _add(t);
      _run(t, () => _upload(f, t));
    }
  }

  /// Open a received file in a phone app. False when no app can open it.
  Future<bool> open(Transfer t) async {
    if (t.saved == null) return false;
    return await _native.invokeMethod<bool>('open', {'uri': t.saved, 'name': t.name}) ?? false;
  }

  void clearFinished() {
    items.removeWhere((t) => t.state == TransferState.done || t.state == TransferState.failed);
    notifyListeners();
  }

  void _add(Transfer t) {
    items.insert(0, t);
    if (items.length > 30) items.removeLast();
    notifyListeners();
  }

  void _run(Transfer t, Future<void> Function() job) {
    _chain = _chain.then((_) async {
      if (_disposed) return;
      t.state = TransferState.running;
      notifyListeners();
      try {
        await job();
        t.state = TransferState.done;
      } catch (e) {
        t.state = TransferState.failed;
        t.error = '$e';
      }
      if (!_disposed) notifyListeners();
    });
  }

  void _progress(Transfer t, int bytes) {
    t.done += bytes;
    final now = DateTime.now();
    if (!_disposed && now.difference(_lastTick).inMilliseconds > 120) {
      _lastTick = now;
      notifyListeners();
    }
  }

  Uri _uri(String path, [Map<String, String>? query]) {
    final uri = conn.httpUri(path, query);
    if (uri == null) throw 'Not connected to the laptop';
    return uri;
  }

  Future<void> _upload(PlatformFile f, Transfer t) async {
    final uri = _uri('/upload', {'name': f.name});
    final client = conn.httpClient();
    try {
      final req = await client.postUrl(uri);
      conn.authHeaders.forEach(req.headers.set);
      req.headers.contentType = ContentType.binary;
      if (t.size > 0) req.contentLength = t.size;
      await req.addStream(f.readAsByteStream().map((chunk) {
        _progress(t, chunk.length);
        return chunk;
      }));
      final res = await req.close();
      final body = await res.transform(utf8.decoder).join();
      if (res.statusCode != 200) throw 'Laptop refused the file (${res.statusCode})';
      t.name = (jsonDecode(body) as Map)['name'] as String? ?? t.name; // renamed if the name was taken
    } finally {
      client.close(force: true);
    }
  }

  Future<void> _download(String id, Transfer t) async {
    final uri = _uri('/files/$id');
    final client = conn.httpClient();
    final tmp = File('${(await getTemporaryDirectory()).path}/fasway-${DateTime.now().microsecondsSinceEpoch}.part');
    try {
      final res = await (await client.getUrl(uri)).close();
      if (res.statusCode != 200) throw 'The laptop no longer offers this file (${res.statusCode})';
      final sink = tmp.openWrite();
      try {
        await for (final chunk in res) {
          sink.add(chunk);
          _progress(t, chunk.length);
        }
      } finally {
        await sink.close();
      }
      if (t.size > 0 && t.done != t.size) throw 'Transfer cut short';
      // copy into the shared Downloads/Fasway folder (Android MediaStore)
      t.saved = await _native.invokeMethod<String>('save', {'path': tmp.path, 'name': t.name});
    } finally {
      client.close(force: true);
      if (await tmp.exists()) await tmp.delete();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _sub.cancel();
    super.dispose();
  }
}
