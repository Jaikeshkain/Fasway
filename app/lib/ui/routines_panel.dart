import 'dart:async';

import 'package:flutter/material.dart';

import '../core/connection.dart';
import 'common.dart';

/// One kind of routine step, as the phone edits it: the assistant tool, what to call it, and its one setting.
class StepKind {
  const StepKind(this.tool, this.label, this.icon, {this.field, this.hint = '', this.number = false, this.choices});
  final String tool, label, hint;
  final IconData icon;
  final String? field; // the tool input the user fills in (null: fixed by the choice)
  final bool number;
  final Map<String, Map<String, dynamic>>? choices; // label -> the whole input

  static const all = [
    StepKind('set_volume', 'Volume', Icons.volume_up_rounded, field: 'percent', hint: '0–100', number: true),
    StepKind('mute', 'Sound', Icons.volume_off_rounded, choices: {
      'Mute': {'muted': true},
      'Unmute': {'muted': false},
    }),
    StepKind('set_brightness', 'Brightness', Icons.brightness_6_rounded, field: 'percent', hint: '0–100', number: true),
    StepKind('play_youtube', 'Play on YouTube', Icons.smart_display_rounded, field: 'query', hint: 'lofi study music'),
    StepKind('open_app', 'Open an app', Icons.apps_rounded, field: 'name', hint: 'Spotify, notepad, chrome…'),
    StepKind('open_url', 'Open a website', Icons.public_rounded, field: 'url', hint: 'https://…'),
    StepKind('media', 'Music', Icons.queue_music_rounded, choices: {
      'Play / pause': {'action': 'play_pause'},
      'Next track': {'action': 'next'},
      'Previous track': {'action': 'previous'},
    }),
    StepKind('power', 'Laptop', Icons.power_settings_new_rounded, choices: {
      'Lock': {'action': 'lock'},
      'Display off': {'action': 'display_off'},
      'Sleep': {'action': 'sleep'},
      'Shut down': {'action': 'shutdown'},
    }),
    StepKind('press_keys', 'Press keys', Icons.keyboard_rounded, field: 'keys', hint: 'win+d'),
    StepKind('run_quick_action', 'Quick action', Icons.bolt_rounded, field: 'name', hint: 'its exact name'),
    StepKind('wait', 'Wait (seconds)', Icons.hourglass_bottom_rounded, field: 'seconds', hint: '1–10', number: true),
  ];

  static StepKind? of(String tool) => all.where((k) => k.tool == tool).firstOrNull;

  /// "Volume 30%", "Play on YouTube: lofi", "Laptop: Sleep"
  static String describe(Map step) {
    final tool = '${step['tool']}';
    final inp = (step['input'] as Map?) ?? const {};
    final k = of(tool);
    if (k == null) return '$tool ${inp.values.join(' ')}'.trim();
    if (k.choices != null) {
      final pick = k.choices!.entries.where((e) => e.value.entries.every((v) => inp[v.key] == v.value)).firstOrNull;
      return k.tool == 'mute' ? (pick?.key ?? k.label) : '${k.label}: ${pick?.key ?? inp.values.join(' ')}';
    }
    final v = inp[k.field];
    return switch (tool) {
      'set_volume' || 'set_brightness' => '${k.label} $v%',
      'wait' => 'Wait ${v}s',
      _ => '${k.label}: $v',
    };
  }
}

/// Routines on the laptop: tap one to run it, or make your own. Saying its name to the assistant runs it too.
class RoutinesPanel extends StatefulWidget {
  const RoutinesPanel({super.key, required this.conn, required this.active});
  final Connection conn;
  final bool active;
  @override
  State<RoutinesPanel> createState() => _RoutinesPanelState();
}

class _RoutinesPanelState extends State<RoutinesPanel> {
  late final StreamSubscription _sub;
  List<Map<String, dynamic>> _items = [];
  bool _loaded = false, _editing = false;

  Connection get conn => widget.conn;

  @override
  void initState() {
    super.initState();
    _sub = conn.messages.listen((m) {
      if (m['t'] == 'agent_routines' && mounted) {
        setState(() {
          _items = [for (final r in (m['items'] as List? ?? const [])) (r as Map).cast<String, dynamic>()];
          _loaded = true;
        });
      }
      if (m['t'] == 'hello') conn.send({'t': 'agent_routines'});
    });
    conn.send({'t': 'agent_routines'});
  }

  @override
  void didUpdateWidget(RoutinesPanel old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) conn.send({'t': 'agent_routines'});
  }

  @override
  void dispose() {
    _sub.cancel();
    super.dispose();
  }

  void _run(Map<String, dynamic> r) {
    if (!conn.send({'t': 'agent_start', 'text': r['name']})) {
      toast(context, 'Not connected to the laptop');
      return;
    }
    Fx.heavy();
    final risky = (r['steps'] as List).any((s) => s['tool'] == 'power' && s['input']['action'] != 'lock'
        && s['input']['action'] != 'display_off');
    toast(context, '${r['icon']} ${r['name']}${risky ? ' — approve the risky step in ✦' : ''}', ms: 2500);
  }

  Future<void> _edit(Map<String, dynamic>? r) async {
    final result = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      backgroundColor: C.panel,
      showDragHandle: true,
      builder: (c) => _RoutineEditor(routine: r),
    );
    if (result == null) return;
    if (result['delete'] == true) {
      conn.send({'t': 'agent_routine_del', 'id': r!['id']});
    } else {
      conn.send({'t': 'agent_routine_save', 'routine': result});
    }
  }

  @override
  Widget build(BuildContext context) => Panel(
        title: 'Routines',
        trailing: TextButton(
          onPressed: () => setState(() => _editing = !_editing),
          child: Text(_editing ? 'Done' : 'Edit'),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (!_loaded)
            const Text('Loading…', style: TextStyle(color: C.muted))
          else
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final r in _items)
                ActionChip(
                  avatar: Text('${r['icon']}', style: const TextStyle(fontSize: 16)),
                  label: Text('${r['name']}'),
                  backgroundColor: C.panel2,
                  side: BorderSide(color: _editing ? C.accent : Colors.transparent),
                  onPressed: () => _editing ? _edit(r) : _run(r),
                ),
              ActionChip(
                avatar: const Icon(Icons.add_rounded, size: 18),
                label: const Text('New'),
                backgroundColor: C.panel2,
                onPressed: () => _edit(null),
              ),
            ]),
          const SizedBox(height: 8),
          Text(
            _editing
                ? 'Tap a routine to change it.'
                : 'Tap to run, or say its name to the assistant ✦. You can also ask it: '
                    '"make a routine called gym time: volume 80 and play workout songs".',
            style: const TextStyle(color: C.muted, fontSize: 12),
          ),
        ]),
      );
}

class _RoutineEditor extends StatefulWidget {
  const _RoutineEditor({this.routine});
  final Map<String, dynamic>? routine;
  @override
  State<_RoutineEditor> createState() => _RoutineEditorState();
}

class _RoutineEditorState extends State<_RoutineEditor> {
  late final _icon = TextEditingController(text: '${widget.routine?['icon'] ?? '⚡'}');
  late final _name = TextEditingController(text: '${widget.routine?['name'] ?? ''}');
  late final _phrases = TextEditingController(text: ((widget.routine?['phrases'] as List?) ?? const []).join(', '));
  late final List<Map<String, dynamic>> _steps = [
    for (final s in (widget.routine?['steps'] as List? ?? const []))
      {'tool': s['tool'], 'input': Map<String, dynamic>.from(s['input'] as Map)}
  ];

  @override
  void dispose() {
    _icon.dispose();
    _name.dispose();
    _phrases.dispose();
    super.dispose();
  }

  Future<void> _addStep() async {
    var kind = StepKind.all.first;
    var choice = '';
    final value = TextEditingController();
    final step = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          backgroundColor: C.panel,
          title: const Text('Add a step'),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            DropdownButton<StepKind>(
              value: kind,
              isExpanded: true,
              items: [
                for (final k in StepKind.all)
                  DropdownMenuItem(value: k, child: Row(children: [Icon(k.icon, size: 18), const SizedBox(width: 8), Text(k.label)]))
              ],
              onChanged: (k) => set(() {
                kind = k!;
                choice = kind.choices?.keys.first ?? '';
                value.clear();
              }),
            ),
            if (kind.choices != null)
              DropdownButton<String>(
                value: choice.isEmpty ? kind.choices!.keys.first : choice,
                isExpanded: true,
                items: [for (final c in kind.choices!.keys) DropdownMenuItem(value: c, child: Text(c))],
                onChanged: (v) => set(() => choice = v!),
              )
            else
              TextField(
                controller: value,
                autofocus: true,
                keyboardType: kind.number ? TextInputType.number : TextInputType.text,
                decoration: InputDecoration(hintText: kind.hint),
              ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
            FilledButton(
              onPressed: () {
                Map<String, dynamic>? input;
                if (kind.choices != null) {
                  input = kind.choices![choice.isEmpty ? kind.choices!.keys.first : choice];
                } else {
                  final v = value.text.trim();
                  final n = num.tryParse(v);
                  if (v.isEmpty || (kind.number && n == null)) return;
                  input = {kind.field!: kind.number ? (kind.tool == 'wait' ? n!.clamp(0, 10) : n!.round().clamp(0, 100)) : v};
                }
                Navigator.pop(c, {'tool': kind.tool, 'input': Map<String, dynamic>.from(input!)});
              },
              child: const Text('Add'),
            ),
          ],
        ),
      ),
    );
    value.dispose();
    if (step != null) setState(() => _steps.add(step));
  }

  void _save() {
    if (_name.text.trim().isEmpty) {
      toast(context, 'Give the routine a name');
      return;
    }
    if (_steps.isEmpty) {
      toast(context, 'Add at least one step');
      return;
    }
    Navigator.pop(context, {
      'id': widget.routine?['id'],
      'icon': _icon.text.trim().isEmpty ? '⚡' : _icon.text.trim(),
      'name': _name.text.trim(),
      'phrases': [for (final p in _phrases.text.split(',')) if (p.trim().isNotEmpty) p.trim()],
      'steps': _steps,
    });
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(18, 0, 18, MediaQuery.viewInsetsOf(context).bottom + 18),
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(widget.routine == null ? 'New routine' : 'Edit routine',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            Row(children: [
              SizedBox(width: 56, child: TextField(controller: _icon, textAlign: TextAlign.center, style: const TextStyle(fontSize: 22))),
              const SizedBox(width: 10),
              Expanded(child: TextField(controller: _name, decoration: const InputDecoration(hintText: 'Name, e.g. Gym time'))),
            ]),
            const SizedBox(height: 8),
            TextField(
              controller: _phrases,
              decoration: const InputDecoration(
                hintText: 'Other ways to say it, comma separated',
                helperText: 'e.g. workout time, gym chalo. The name always works.',
              ),
            ),
            const SizedBox(height: 14),
            const Text('Steps, in order', style: TextStyle(color: C.muted, fontSize: 13)),
            ReorderableListView(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              buildDefaultDragHandles: true,
              onReorderItem: (a, b) => setState(() => _steps.insert(b, _steps.removeAt(a))),
              children: [
                for (final (i, s) in _steps.indexed)
                  ListTile(
                    key: ObjectKey(s),
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(StepKind.of('${s['tool']}')?.icon ?? Icons.auto_awesome_rounded, size: 20),
                    title: Text(StepKind.describe(s)),
                    trailing: IconButton(
                      tooltip: 'Remove step',
                      icon: const Icon(Icons.close_rounded, size: 18),
                      onPressed: () => setState(() => _steps.removeAt(i)),
                    ),
                  ),
              ],
            ),
            if (_steps.length < 12)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(onPressed: _addStep, icon: const Icon(Icons.add_rounded), label: const Text('Add a step')),
              ),
            const Text('Steps like shutting down still ask you on the phone before they run.',
                style: TextStyle(color: C.muted, fontSize: 12)),
            const SizedBox(height: 12),
            Row(children: [
              if (widget.routine != null)
                TextButton(
                  onPressed: () async {
                    if (await confirm(context, 'Delete routine', 'Delete “${widget.routine!['name']}”?', ok: 'Delete', danger: true) &&
                        context.mounted) {
                      Navigator.pop(context, {'delete': true});
                    }
                  },
                  child: const Text('Delete', style: TextStyle(color: C.bad)),
                ),
              const Spacer(),
              TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
              FilledButton(onPressed: _save, child: const Text('Save')),
            ]),
          ]),
        ),
      );
}
