import 'package:flutter/material.dart';

import '../core/connection.dart';

/// A text field mirrored live to the laptop: every change is diffed against the previous value and
/// replayed as backspaces + new text. Works with Gboard autocorrect, swipe typing, Hindi keyboards
/// and the keyboard's own mic, which don't send usable key events.
class LiveTypingField extends StatefulWidget {
  const LiveTypingField({
    super.key,
    required this.conn,
    required this.focusNode,
    this.decoration,
    this.onCombo,
    this.onSpecialKey,
  });

  final Connection conn;
  final FocusNode focusNode;
  final InputDecoration? decoration;

  /// Return true to swallow typed characters as shortcuts (when Ctrl/Alt/Win is active).
  final bool Function(String chars)? onCombo;

  /// Enter etc.; defaults to sending the key as-is.
  final void Function(String key)? onSpecialKey;

  @override
  State<LiveTypingField> createState() => LiveTypingFieldState();
}

class LiveTypingFieldState extends State<LiveTypingField> {
  // invisible character, so Backspace on an "empty" field still produces an edit
  static const sentinel = '​';
  final _c = TextEditingController(text: sentinel);
  String _prev = sentinel;

  @override
  void initState() {
    super.initState();
    _c.selection = const TextSelection.collapsed(offset: 1);
    _c.addListener(_caretToEnd);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  /// The laptop's caret is always at the end of what we've typed, so keep the phone's there too.
  void _caretToEnd() {
    final n = _c.text.length;
    if (_c.value.composing.isValid) return;
    if (!_c.selection.isCollapsed || _c.selection.baseOffset != n) {
      _c.selection = TextSelection.collapsed(offset: n);
    }
  }

  void reset() {
    _prev = sentinel;
    _c.value = const TextEditingValue(text: sentinel, selection: TextSelection.collapsed(offset: 1));
  }

  void _onChanged(String v) {
    var i = 0;
    while (i < _prev.length && i < v.length && _prev.codeUnitAt(i) == v.codeUnitAt(i)) {
      i++;
    }
    // don't split an emoji's surrogate pair
    if (i > 0 && _isHighSurrogate(_prev.codeUnitAt(i - 1))) i--;
    final removed = _prev.substring(i), added = v.substring(i);

    if (added.isNotEmpty && removed.isEmpty && (widget.onCombo?.call(added) ?? false)) {
      // swallowed as a shortcut (Ctrl+C...): restore the field
      _c.value = TextEditingValue(text: _prev, selection: TextSelection.collapsed(offset: _prev.length));
      return;
    }
    if (removed.isNotEmpty || added.isNotEmpty) {
      widget.conn.send({'t': 'edit', 'del': removed.runes.length, 'ins': added});
    }
    var next = v;
    if (!next.startsWith(sentinel)) next = sentinel + next; // sentinel was deleted: put it back
    if (next.length > 400 && !_c.value.composing.isValid) {
      next = sentinel + next.substring(next.length - 40); // keep the field short
    }
    if (next != v) {
      _c.value = TextEditingValue(text: next, selection: TextSelection.collapsed(offset: next.length));
    }
    _prev = next;
  }

  static bool _isHighSurrogate(int u) => u >= 0xD800 && u <= 0xDBFF;

  @override
  Widget build(BuildContext context) => TextField(
        controller: _c,
        focusNode: widget.focusNode,
        onChanged: _onChanged,
        textInputAction: TextInputAction.send,
        onSubmitted: (_) {
          (widget.onSpecialKey ?? (k) => widget.conn.send({'t': 'key', 'k': k}))('enter');
          reset();
          widget.focusNode.requestFocus(); // keep the keyboard up
        },
        onEditingComplete: () {}, // don't close the keyboard on Enter
        autocorrect: true,
        enableSuggestions: true,
        style: const TextStyle(fontSize: 18),
        decoration: widget.decoration,
      );
}
