import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/connection.dart';
import '../core/settings.dart';
import 'common.dart';

/// Quick actions, open a link on the laptop, and the laptop's open windows (app switcher).
class AppsTab extends StatefulWidget {
  const AppsTab({super.key, required this.conn, required this.settings, required this.active});
  final Connection conn;
  final Settings settings;
  final bool active;
  @override
  State<AppsTab> createState() => _AppsTabState();
}

class _AppsTabState extends State<AppsTab> {
  late final StreamSubscription _sub;
  Timer? _poll;
  List<Map<String, dynamic>> _actions = [];
  List<Map<String, dynamic>> _wins = [];
  final _icons = <String, Uint8List>{};
  bool _editing = false;
  final _url = TextEditingController();

  Connection get conn => widget.conn;

  @override
  void initState() {
    super.initState();
    _sub = conn.messages.listen(_onMessage);
    _poll = Timer.periodic(const Duration(milliseconds: 2500), (_) {
      if (widget.active) _refreshWins();
    });
  }

  @override
  void didUpdateWidget(AppsTab old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) {
      conn.send({'t': 'actions'});
      _refreshWins();
    }
  }

  @override
  void dispose() {
    _sub.cancel();
    _poll?.cancel();
    _url.dispose();
    super.dispose();
  }

  void _refreshWins() => conn.send({'t': 'wins', 'have': _icons.keys.toList()});

  void _onMessage(Map<String, dynamic> m) {
    switch (m['t']) {
      case 'actions':
        setState(() => _actions = (m['items'] as List).cast<Map<String, dynamic>>());
      case 'wins':
        (m['icons'] as Map?)?.forEach((k, v) => _icons[k as String] = base64Decode(v as String));
        setState(() => _wins = (m['windows'] as List).cast<Map<String, dynamic>>());
    }
  }

  // ---------- open link ----------
  static final _urlRe = RegExp(r'(https?://|www\.)\S+', caseSensitive: false);

  void _open(String text) {
    final m = _urlRe.firstMatch(text.trim());
    if (m == null) {
      toast(context, "That doesn't look like a link");
      return;
    }
    if (conn.send({'t': 'open_url', 'url': m.group(0)})) haptic(widget.settings.haptics);
  }

  Future<void> _openFromClipboard() async {
    final t = (await Clipboard.getData(Clipboard.kTextPlain))?.text ?? '';
    final m = _urlRe.firstMatch(t);
    if (m == null) {
      if (mounted) toast(context, 'No link in the phone clipboard');
      return;
    }
    _url.text = m.group(0)!;
    _open(m.group(0)!);
  }

  // ---------- quick actions ----------
  static const _types = {
    'open': ('Open a website, app, file or folder', 'https://www.youtube.com',
        'A website (https://…), an app (notepad, calc, chrome) or a file/folder path.'),
    'text': ('Type text', 'my.email@example.com', 'Typed wherever the laptop cursor is.'),
    'keys': ('Press shortcut keys', 'win+e', 'Comma separated, e.g. ctrl+shift+esc · win+d · ctrl+c, ctrl+v'),
    'macro': ('Macro (several steps)', 'key win+r\ntype notepad\nwait 400\nkey enter',
        'One step per line: key …, type …, wait ms, open …, cmd …'),
    'command': ('Run a command', 'shutdown /h', 'Runs in the background without a window.'),
  };

  Future<void> _edit(Map<String, dynamic>? a) async {
    final icon = TextEditingController(text: a?['icon'] as String? ?? '⭐');
    final name = TextEditingController(text: a?['name'] as String? ?? '');
    final value = TextEditingController(text: a?['value'] as String? ?? '');
    var type = (a?['type'] as String?) ?? 'open';
    final result = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: C.panel,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => Padding(
          padding: EdgeInsets.fromLTRB(18, 18, 18, MediaQuery.viewInsetsOf(c).bottom + 18),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(a == null ? 'New quick action' : 'Edit quick action',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            Row(children: [
              SizedBox(width: 60, child: TextField(controller: icon, textAlign: TextAlign.center, style: const TextStyle(fontSize: 22))),
              const SizedBox(width: 10),
              Expanded(child: TextField(controller: name, decoration: const InputDecoration(hintText: 'Name'))),
            ]),
            const SizedBox(height: 10),
            DropdownButton<String>(
              value: type,
              isExpanded: true,
              items: [for (final e in _types.entries) DropdownMenuItem(value: e.key, child: Text(e.value.$1))],
              onChanged: (v) => set(() => type = v!),
            ),
            TextField(
              controller: value,
              minLines: type == 'macro' || type == 'text' ? 4 : 1,
              maxLines: 6,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 14),
              decoration: InputDecoration(hintText: _types[type]!.$2),
            ),
            const SizedBox(height: 6),
            Text(_types[type]!.$3, style: const TextStyle(color: C.muted, fontSize: 12)),
            const SizedBox(height: 14),
            Row(children: [
              if (a != null) ...[
                TextButton(onPressed: () => Navigator.pop(c, 'delete'), child: const Text('Delete', style: TextStyle(color: C.bad))),
                IconButton(onPressed: () => Navigator.pop(c, 'left'), icon: const Icon(Icons.chevron_left_rounded)),
                IconButton(onPressed: () => Navigator.pop(c, 'right'), icon: const Icon(Icons.chevron_right_rounded)),
              ],
              const Spacer(),
              TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
              FilledButton(onPressed: () => Navigator.pop(c, 'save'), child: const Text('Save')),
            ]),
          ]),
        ),
      ),
    );
    switch (result) {
      case 'save':
        if (value.text.trim().isEmpty) {
          if (mounted) toast(context, 'Fill in what the action should do');
          return;
        }
        conn.send({
          't': 'action_save',
          'action': {
            'id': a?['id'],
            'icon': icon.text.trim().isEmpty ? '⭐' : icon.text.trim(),
            'name': name.text.trim().isEmpty ? 'Action' : name.text.trim(),
            'type': type,
            'value': value.text,
          }
        });
      case 'delete':
        if (mounted && await confirm(context, 'Delete', 'Delete “${a!['name']}”?', ok: 'Delete', danger: true)) {
          conn.send({'t': 'action_del', 'id': a['id']});
        }
      case 'left' || 'right':
        conn.send({'t': 'action_move', 'id': a!['id'], 'd': result == 'left' ? -1 : 1});
    }
  }

  Widget _actionsGrid() => GridView.count(
        crossAxisCount: 4,
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        mainAxisSpacing: 8,
        crossAxisSpacing: 8,
        childAspectRatio: 0.95,
        children: [
          for (final a in _actions)
            _tile(a['icon'] as String, a['name'] as String, () {
              if (_editing) {
                _edit(a);
              } else if (conn.send({'t': 'action_run', 'id': a['id']})) {
                haptic(widget.settings.haptics);
                toast(context, '${a['icon']} ${a['name']}');
              }
            }),
          if (_editing || _actions.isEmpty) _tile('＋', 'Add', () => _edit(null), muted: true),
        ],
      );

  Widget _tile(String icon, String name, VoidCallback onTap, {bool muted = false}) => Material(
        color: C.panel2,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: Container(
            decoration: _editing ? BoxDecoration(border: Border.all(color: C.accent), borderRadius: BorderRadius.circular(12)) : null,
            padding: const EdgeInsets.all(4),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Text(icon, style: const TextStyle(fontSize: 24)),
              const SizedBox(height: 4),
              Text(name, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, color: muted ? C.muted : C.text)),
            ]),
          ),
        ),
      );

  // ---------- windows ----------
  Widget _windows() {
    if (_wins.isEmpty) return const Text('Loading…', style: TextStyle(color: C.muted));
    return Column(children: [
      for (final w in _wins)
        Container(
          margin: const EdgeInsets.only(bottom: 6),
          decoration: BoxDecoration(
            color: C.panel2,
            borderRadius: BorderRadius.circular(12),
            border: w['active'] == true ? Border.all(color: C.accent) : null,
          ),
          child: Opacity(
            opacity: w['min'] == true ? 0.65 : 1,
            child: ListTile(
              dense: true,
              contentPadding: const EdgeInsets.only(left: 10),
              leading: SizedBox(
                width: 30,
                height: 30,
                child: w['icon'] != null && _icons[w['icon']] != null
                    ? Image.memory(_icons[w['icon']]!, gaplessPlayback: true)
                    : CircleAvatar(
                        backgroundColor: const Color(0xFF33394A),
                        child: Text(((w['title'] as String).trim().isEmpty ? '?' : (w['title'] as String).trim()[0]),
                            style: const TextStyle(fontWeight: FontWeight.w700)),
                      ),
              ),
              title: Text(w['title'] as String, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14)),
              subtitle: Text(
                [w['app'], w['active'] == true ? 'active' : (w['min'] == true ? 'minimized' : '')].where((x) => (x as String).isNotEmpty).join(' · '),
                style: const TextStyle(color: C.muted, fontSize: 11),
              ),
              onTap: () => _winAction(w, 'focus'),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(icon: const Icon(Icons.minimize_rounded, size: 18), onPressed: () => _winAction(w, 'min')),
                IconButton(icon: const Icon(Icons.crop_square_rounded, size: 18), onPressed: () => _winAction(w, 'max')),
                IconButton(
                  icon: const Icon(Icons.close_rounded, size: 18),
                  onPressed: () async {
                    if (await confirm(context, 'Close window', 'Close “${w['title']}”?', ok: 'Close')) _winAction(w, 'close');
                  },
                ),
              ]),
            ),
          ),
        ),
    ]);
  }

  void _winAction(Map<String, dynamic> w, String a) {
    conn.send({'t': 'win', 'id': w['id'], 'a': a, 'have': _icons.keys.toList()});
    haptic(widget.settings.haptics);
  }

  @override
  Widget build(BuildContext context) => ListView(children: [
        Panel(
          title: 'Quick actions',
          trailing: TextButton(
            onPressed: () {
              setState(() => _editing = !_editing);
              if (_editing) toast(context, 'Tap an action to change it, or ＋ to add one');
            },
            child: Text(_editing ? 'Done' : 'Edit'),
          ),
          child: _actionsGrid(),
        ),
        Panel(
          title: 'Open link on laptop',
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _url,
                  keyboardType: TextInputType.url,
                  decoration: const InputDecoration(hintText: 'https://…'),
                  onSubmitted: _open,
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(onPressed: () => _open(_url.text), child: const Text('Open')),
            ]),
            TextButton.icon(
              onPressed: _openFromClipboard,
              icon: const Icon(Icons.content_paste_rounded, size: 18),
              label: const Text('Open the link copied on this phone'),
            ),
          ]),
        ),
        Panel(
          title: 'Open windows',
          trailing: IconButton(icon: const Icon(Icons.refresh_rounded, size: 20), onPressed: _refreshWins),
          child: _windows(),
        ),
      ]);
}
