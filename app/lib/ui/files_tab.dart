import 'package:flutter/material.dart';

import '../core/connection.dart';
import '../core/files.dart';
import 'common.dart';

/// File sharing: send phone files to the laptop, receive files dropped on the laptop's Fasway window,
/// with live progress, speed, time left, cancel / retry and a history.
class FilesTab extends StatelessWidget {
  const FilesTab({super.key, required this.conn, required this.files});
  final Connection conn;
  final FileTransfers files;

  Future<void> _send(BuildContext context) async {
    if (!conn.isConnected) {
      toast(context, 'Not connected to the laptop');
      return;
    }
    try {
      await files.pickAndSend();
    } catch (e) {
      if (context.mounted) toast(context, "Couldn't pick files: $e");
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: Listenable.merge([files, conn]),
        builder: (context, _) {
          final active = files.active;
          final history = files.items.where((t) => !t.active).toList();
          return ListView(padding: const EdgeInsets.only(top: 4, bottom: 16), children: [
            Row(children: [
              Expanded(
                child: _ActionCard(
                  icon: Icons.upload_rounded,
                  title: 'Send to laptop',
                  subtitle: 'Photos, videos, any file',
                  primary: true,
                  onTap: () => _send(context),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _ActionCard(
                  icon: Icons.folder_open_rounded,
                  title: 'Show on laptop',
                  subtitle: r'Opens Downloads\Fasway',
                  onTap: () {
                    if (!conn.send({'t': 'files_open'})) toast(context, 'Not connected to the laptop');
                  },
                ),
              ),
            ]),
            const SizedBox(height: 10),
            if (active.isNotEmpty) _Summary(files) else const _HowTo(),
            if (active.isNotEmpty) ...[
              _SectionTitle('In progress', trailing: '${active.length}'),
              for (final t in active) _TransferCard(t, files),
            ],
            if (history.isNotEmpty) ...[
              _SectionTitle('Recent',
                  action: TextButton(onPressed: files.clearFinished, child: const Text('Clear'))),
              for (final t in history) _TransferCard(t, files),
            ],
            if (files.items.isEmpty)
              const Padding(
                padding: EdgeInsets.only(top: 36),
                child: Column(children: [
                  Icon(Icons.swap_vert_circle_outlined, size: 56, color: C.panel2),
                  SizedBox(height: 8),
                  Text('No transfers yet', style: TextStyle(color: C.muted)),
                ]),
              ),
          ]);
        },
      );
}

// ---------------------------------------------------------------------------------------------

String fmtSize(num b) => b < 1024
    ? '${b.round()} B'
    : b < 1 << 20
        ? '${(b / 1024).toStringAsFixed(0)} KB'
        : b < 1 << 30
            ? '${(b / (1 << 20)).toStringAsFixed(1)} MB'
            : '${(b / (1 << 30)).toStringAsFixed(2)} GB';

String fmtEta(Duration d) =>
    d.inHours > 0 ? '${d.inHours} h ${d.inMinutes % 60} min' : d.inMinutes > 0 ? '${d.inMinutes} min ${d.inSeconds % 60} s' : '${d.inSeconds} s';

(IconData, Color) fileIcon(String name) {
  final ext = name.contains('.') ? name.split('.').last.toLowerCase() : '';
  const image = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'heif', 'bmp', 'svg'};
  const video = {'mp4', 'mov', 'mkv', 'avi', 'webm', '3gp', 'm4v'};
  const audio = {'mp3', 'm4a', 'wav', 'aac', 'flac', 'ogg', 'opus'};
  const archive = {'zip', 'rar', '7z', 'tar', 'gz'};
  const doc = {'doc', 'docx', 'txt', 'rtf', 'odt', 'md', 'xls', 'xlsx', 'csv', 'ppt', 'pptx'};
  if (image.contains(ext)) return (Icons.image_rounded, const Color(0xFF4FC3F7));
  if (video.contains(ext)) return (Icons.movie_rounded, const Color(0xFFBA68C8));
  if (audio.contains(ext)) return (Icons.audiotrack_rounded, const Color(0xFFFFB74D));
  if (ext == 'pdf') return (Icons.picture_as_pdf_rounded, const Color(0xFFFF7043));
  if (archive.contains(ext)) return (Icons.folder_zip_rounded, const Color(0xFFA1887F));
  if (ext == 'apk') return (Icons.android_rounded, C.ok);
  if (doc.contains(ext)) return (Icons.description_rounded, C.accent);
  return (Icons.insert_drive_file_rounded, C.muted);
}

class _ActionCard extends StatelessWidget {
  const _ActionCard({required this.icon, required this.title, required this.subtitle, required this.onTap, this.primary = false});
  final IconData icon;
  final String title, subtitle;
  final VoidCallback onTap;
  final bool primary;

  @override
  Widget build(BuildContext context) => Material(
        color: primary ? C.accent : C.panel,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 14, 12, 14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(icon, size: 28, color: primary ? Colors.white : C.accent),
              const SizedBox(height: 10),
              Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: Colors.white)),
              const SizedBox(height: 2),
              Text(subtitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 12, color: primary ? Colors.white70 : C.muted)),
            ]),
          ),
        ),
      );
}

/// How to get files from the laptop (shown when nothing is going on).
class _HowTo extends StatelessWidget {
  const _HowTo();

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: C.panel, borderRadius: BorderRadius.circular(16)),
        child: const Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.laptop_windows_rounded, color: C.accent, size: 26),
          SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Get files from the laptop', style: TextStyle(fontWeight: FontWeight.w700)),
              SizedBox(height: 4),
              Text(
                'Drag files onto the Fasway window on the laptop (or click "Send files to phone…"). '
                'They arrive here and are saved in Downloads/Fasway.',
                style: TextStyle(color: C.muted, fontSize: 13, height: 1.4),
              ),
            ]),
          ),
        ]),
      );
}

/// Overall progress while files are moving.
class _Summary extends StatelessWidget {
  const _Summary(this.files);
  final FileTransfers files;

  @override
  Widget build(BuildContext context) {
    final active = files.active;
    final up = active.where((t) => t.toLaptop).length, down = active.length - up;
    final p = files.totalProgress;
    final left = active.fold<int>(0, (s, t) => s + (t.size - t.done).clamp(0, t.size));
    final what = [if (up > 0) 'Sending $up', if (down > 0) 'Receiving $down'].join(' · ');
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        gradient: const LinearGradient(colors: [Color(0xFF233355), Color(0xFF1B1E25)]),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(children: [
        SizedBox(
          width: 52,
          height: 52,
          child: Stack(alignment: Alignment.center, children: [
            CircularProgressIndicator(value: p, strokeWidth: 5, backgroundColor: C.panel2),
            Text(p == null ? '…' : '${(p * 100).floor()}%', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
          ]),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('$what file${active.length == 1 ? '' : 's'}', style: const TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 3),
            Text(left > 0 ? '${fmtSize(left)} left' : 'Working…', style: const TextStyle(color: C.muted, fontSize: 13)),
          ]),
        ),
      ]),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text, {this.trailing, this.action});
  final String text;
  final String? trailing;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 16, 0, 2),
        child: Row(children: [
          Text(text.toUpperCase(),
              style: const TextStyle(color: C.muted, fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
          if (trailing != null) ...[
            const SizedBox(width: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
              decoration: BoxDecoration(color: C.accent.withValues(alpha: 0.2), borderRadius: BorderRadius.circular(10)),
              child: Text(trailing!, style: const TextStyle(color: C.accent, fontSize: 11, fontWeight: FontWeight.w700)),
            ),
          ],
          const Spacer(),
          ?action,
        ]),
      );
}

class _TransferCard extends StatelessWidget {
  const _TransferCard(this.t, this.files);
  final Transfer t;
  final FileTransfers files;

  @override
  Widget build(BuildContext context) {
    final (icon, color) = fileIcon(t.name);
    final failed = t.state == TransferState.failed;
    final direction = t.toLaptop ? 'To laptop' : 'From laptop';
    final String status;
    switch (t.state) {
      case TransferState.waiting:
        status = 'Waiting · ${t.size > 0 ? fmtSize(t.size) : direction}';
      case TransferState.running:
        final p = t.progress;
        final eta = t.eta;
        status = [
          if (p != null) '${(p * 100).floor()}%',
          t.size > 0 ? '${fmtSize(t.done)} of ${fmtSize(t.size)}' : fmtSize(t.done),
          if (t.speed > 0) '${fmtSize(t.speed)}/s',
          if (eta != null) '${fmtEta(eta)} left',
        ].join(' · ');
      case TransferState.done:
        status = '${t.toLaptop ? r'Sent · laptop Downloads\Fasway' : 'Saved · Downloads/Fasway'} · ${fmtSize(t.size > 0 ? t.size : t.done)}';
      case TransferState.failed:
        status = t.error ?? 'Failed';
    }
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
      decoration: BoxDecoration(color: C.panel, borderRadius: BorderRadius.circular(14)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Stack(clipBehavior: Clip.none, children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(10)),
              child: Icon(icon, color: color),
            ),
            Positioned(
              right: -4,
              bottom: -4,
              child: Container(
                padding: const EdgeInsets.all(2),
                decoration: const BoxDecoration(color: C.panel, shape: BoxShape.circle),
                child: Icon(t.toLaptop ? Icons.arrow_circle_up_rounded : Icons.arrow_circle_down_rounded,
                    size: 16, color: t.state == TransferState.done ? C.ok : failed ? C.bad : C.accent),
              ),
            ),
          ]),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(t.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text(status,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: failed ? C.bad : C.muted, fontSize: 12)),
            ]),
          ),
          if (t.active)
            IconButton(tooltip: 'Cancel', icon: const Icon(Icons.close_rounded, size: 20), onPressed: () => files.cancel(t))
          else if (failed)
            IconButton(tooltip: 'Try again', icon: const Icon(Icons.refresh_rounded, size: 22), onPressed: () => files.retry(t))
          else if (t.canOpen)
            IconButton(
              tooltip: 'Open',
              icon: const Icon(Icons.open_in_new_rounded, size: 20),
              onPressed: () async {
                if (!await files.open(t) && context.mounted) toast(context, 'No app on the phone can open this file');
              },
            )
          else if (t.state == TransferState.done)
            const Padding(padding: EdgeInsets.all(12), child: Icon(Icons.check_circle_rounded, size: 20, color: C.ok)),
        ]),
        if (t.active)
          Padding(
            padding: const EdgeInsets.fromLTRB(0, 10, 8, 0),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: t.state == TransferState.waiting ? 0 : t.progress,
                minHeight: 6,
                backgroundColor: C.panel2,
              ),
            ),
          ),
      ]),
    );
  }
}
