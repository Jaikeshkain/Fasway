import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/connection.dart';
import '../core/laptop.dart';
import 'common.dart';

/// Colour and short text for a connection's state.
(Color, String) linkStatus(Connection conn) => switch (conn.state) {
      LinkState.connected => conn.weak ? (C.warn, 'Weak Wi-Fi') : (C.ok, 'Connected'),
      LinkState.connecting => (C.warn, 'Connecting…'),
      LinkState.waitingApproval => (C.warn, 'Waiting for approval'),
      LinkState.declined => (C.bad, 'Not allowed'),
      LinkState.removed => (C.bad, 'Removed'),
      LinkState.wrongLaptop => (C.bad, 'Wrong laptop'),
      LinkState.offline => (C.bad, 'Offline'),
    };

/// Every paired laptop: tap one to control it, add another, rename or forget one.
/// [canLeave] asks before leaving the current laptop (running file transfers).
void showLaptops(BuildContext context, AppState s, {required Future<bool> Function() canLeave, required VoidCallback onAdd}) {
  showModalBottomSheet(
    context: context,
    backgroundColor: C.panel,
    isScrollControlled: true,
    showDragHandle: true,
    sheetAnimationStyle: const AnimationStyle(duration: Motion.slow, reverseDuration: Motion.medium),
    builder: (c) => ListenableBuilder(
      // the sheet closes whenever the connection is replaced, so this one stays the current one
      listenable: Listenable.merge([s, s.discovery, s.connection]),
      builder: (c, _) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('Laptops', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            for (final l in s.laptops)
              _LaptopRow(
                key: ValueKey(l.id),
                s: s,
                laptop: l,
                onTap: () async {
                  if (l.id == s.laptop?.id) {
                    Navigator.pop(c);
                    return;
                  }
                  Fx.select();
                  if (!await canLeave()) return;
                  if (c.mounted) Navigator.pop(c);
                  s.switchTo(l);
                },
              ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () {
                Navigator.pop(c);
                onAdd();
              },
              icon: const Icon(Icons.add_rounded),
              label: const Text('Add a laptop'),
            ),
          ]),
        ),
      ),
    ),
  );
}

class _LaptopRow extends StatelessWidget {
  const _LaptopRow({super.key, required this.s, required this.laptop, required this.onTap});
  final AppState s;
  final Laptop laptop;
  final VoidCallback onTap;

  Future<void> _rename(BuildContext context) async {
    final name = TextEditingController(text: laptop.name);
    final result = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        backgroundColor: C.panel,
        title: const Text('Rename laptop'),
        content: TextField(
          controller: name,
          autofocus: true,
          maxLength: 40,
          textCapitalization: TextCapitalization.sentences,
          decoration: const InputDecoration(hintText: 'Name'),
          onSubmitted: (v) => Navigator.pop(c, v),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, name.text), child: const Text('Save')),
        ],
      ),
    );
    final v = result?.trim() ?? '';
    if (v.isNotEmpty) s.rename(laptop, v);
  }

  Future<void> _forget(BuildContext context) async {
    final ok = await confirm(context, 'Forget laptop', 'Forget ${laptop.name}? You will need to scan its QR code again.',
        ok: 'Forget', danger: true);
    if (!ok) return;
    // forgetting the current laptop replaces the connection, or leaves none: close the sheet first
    if (laptop.id == s.laptop?.id && context.mounted) Navigator.pop(context);
    s.forget(laptop);
  }

  @override
  Widget build(BuildContext context) {
    final conn = s.connection;
    final current = laptop.id == s.laptop?.id && conn != null;
    final seen = s.discovery.found.containsKey(laptop.id);
    final (color, status) = current ? linkStatus(conn) : (seen ? C.ok : C.muted, seen ? 'On this Wi-Fi' : 'Not seen on this Wi-Fi');
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(Icons.laptop_windows_rounded, color: current ? C.accent : C.muted),
      title: Text(laptop.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(current && conn.isConnected && conn.address != null ? '$status · ${conn.address}' : status,
          maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: color, fontSize: 12)),
      selected: current,
      selectedColor: C.text,
      onTap: onTap,
      trailing: PopupMenuButton<String>(
        tooltip: 'Options for ${laptop.name}',
        color: C.panel,
        onSelected: (v) => v == 'rename' ? _rename(context) : _forget(context),
        itemBuilder: (_) => const [
          PopupMenuItem(value: 'rename', child: Text('Rename')),
          PopupMenuItem(value: 'forget', child: Text('Forget', style: TextStyle(color: C.bad))),
        ],
      ),
    );
  }
}
