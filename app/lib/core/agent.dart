import 'dart:async';

import 'package:flutter/foundation.dart';

class AgentStep {
  AgentStep(this.text, this.status);
  final String text;
  final String status; // running | done | failed | declined
}

class AgentTask {
  AgentTask.fromJson(Map<String, dynamic> m)
      : id = '${m['id']}',
        goal = '${m['goal'] ?? ''}',
        device = '${m['device'] ?? ''}',
        state = '${m['state'] ?? 'running'}',
        source = '${m['source'] ?? 'ai'}',
        reply = '${m['reply'] ?? ''}',
        inr = (m['inr'] as num?)?.toDouble() ?? 0,
        steps = [
          for (final s in (m['steps'] as List? ?? const []))
            AgentStep('${(s as Map)['text']}', '${s['status']}'),
        ];

  final String id, goal, device, state, source, reply;
  final double inr;
  final List<AgentStep> steps;

  bool get active => state == 'running' || state == 'waiting_approval';
}

class AgentApproval {
  AgentApproval.fromJson(Map<String, dynamic> m)
      : id = '${m['id']}',
        task = '${m['task']}',
        action = '${m['action'] ?? ''}',
        why = '${m['why'] ?? ''}',
        deadline = DateTime.now().add(Duration(seconds: (m['seconds'] as num?)?.toInt() ?? 120));

  final String id, task, action, why;
  final DateTime deadline;
}

class AgentModel {
  AgentModel(this.id, this.label, this.hint, this.hasKey);
  final String id, label, hint;
  final bool hasKey;
}

/// The assistant's state on the phone. The laptop does the work and owns the truth: this mirrors what
/// it reports, and asks again for everything after a reconnect.
class AgentController extends ChangeNotifier {
  AgentController(
      {required Stream<Map<String, dynamic>> messages, required this.send, required this.connected, Listenable? link, this.deviceId = ''}) {
    _sub = messages.listen(_onMessage);
    _link = link;
    _link?.addListener(_onLink);
    _onLink();
  }

  final bool Function(Map<String, dynamic>) send;
  final bool Function() connected;
  final String deviceId; // this phone, as the laptop knows it: only its own requests are answered aloud

  /// A request from this phone just finished (done, failed or stopped): its reply can be read out.
  void Function(AgentTask)? onFinished;
  late final StreamSubscription<Map<String, dynamic>> _sub;
  Listenable? _link;
  bool _wasConnected = false;
  Timer? _noReply;
  static const replyTimeout = Duration(seconds: 4);

  /// Connected, but the laptop doesn't answer assistant messages.
  bool laptopOutdated = false;

  /// A new approval arrived (null = none waiting any more).
  void Function(AgentApproval?)? onApprovalChanged;

  final tasks = <AgentTask>[]; // oldest first
  final approvals = <AgentApproval>[];
  var models = <AgentModel>[];
  String model = '';
  bool hasKey = false, loaded = false;
  int taskBudget = 30, dailyBudget = 150, commandsToday = 0;
  double spentToday = 0;

  AgentTask? get activeTask {
    for (final t in tasks.reversed) {
      if (t.active) return t;
    }
    return null;
  }

  void _onLink() {
    final now = connected();
    if (now && !_wasConnected) {
      send({'t': 'agent_list'}); // catch up: tasks may have moved on while away
      _waitForLaptop();
    } else if (!now) {
      _noReply?.cancel();
    }
    _wasConnected = now;
    notifyListeners();
  }

  /// A laptop on an older Fasway ignores these messages without a word: notice, instead of showing nothing.
  void _waitForLaptop() {
    _noReply?.cancel();
    _noReply = Timer(replyTimeout, () {
      laptopOutdated = true;
      notifyListeners();
    });
  }

  void _onMessage(Map<String, dynamic> m) {
    if ('${m['t']}'.startsWith('agent_')) {
      _noReply?.cancel();
      laptopOutdated = false;
    }
    switch (m['t']) {
      case 'agent_task':
        _upsert(AgentTask.fromJson((m['task'] as Map).cast<String, dynamic>()));
      case 'agent_approval':
        final a = AgentApproval.fromJson(m);
        if (approvals.every((x) => x.id != a.id)) approvals.add(a);
        onApprovalChanged?.call(a);
      case 'agent_approval_done':
        approvals.removeWhere((a) => a.id == '${m['id']}'); // answered here, on another phone, or timed out
        if (approvals.isEmpty) onApprovalChanged?.call(null);
      case 'agent_settings':
        _settings(m);
      case 'agent_list':
        tasks
          ..clear()
          ..addAll([for (final t in (m['tasks'] as List? ?? const [])) AgentTask.fromJson((t as Map).cast<String, dynamic>())]);
        approvals
          ..clear()
          ..addAll([for (final a in (m['approvals'] as List? ?? const [])) AgentApproval.fromJson((a as Map).cast<String, dynamic>())]);
        _settings(m);
        onApprovalChanged?.call(approvals.isEmpty ? null : approvals.last);
      default:
        return;
    }
    notifyListeners();
  }

  void _settings(Map<String, dynamic> m) {
    loaded = true;
    model = '${m['model'] ?? model}';
    hasKey = m['has_key'] == true;
    taskBudget = (m['task_budget_inr'] as num?)?.toInt() ?? taskBudget;
    dailyBudget = (m['daily_budget_inr'] as num?)?.toInt() ?? dailyBudget;
    spentToday = (m['spent_today_inr'] as num?)?.toDouble() ?? spentToday;
    commandsToday = (m['commands_today'] as num?)?.toInt() ?? commandsToday;
    final list = m['models'] as List?;
    if (list != null) {
      models = [for (final x in list) AgentModel('${(x as Map)['id']}', '${x['label']}', '${x['hint']}', x['has_key'] != false)];
    }
  }

  void _upsert(AgentTask t) {
    final i = tasks.indexWhere((x) => x.id == t.id);
    final wasActive = i >= 0 && tasks[i].active;
    if (i >= 0) {
      tasks[i] = t;
    } else {
      tasks.add(t);
    }
    // only on the change itself: a task seen already finished (catching up after a reconnect) stays quiet
    if (wasActive && !t.active && deviceId.isNotEmpty && t.device == deviceId) onFinished?.call(t);
  }

  bool start(String text) {
    final clean = text.trim();
    if (clean.isEmpty || !send({'t': 'agent_start', 'text': clean})) return false;
    _waitForLaptop();
    return true;
  }

  void answer(AgentApproval a, bool ok, {bool remember = false}) {
    if (!send({'t': 'agent_approve', 'id': a.id, 'ok': ok, 'remember': remember})) return;
    approvals.remove(a);
    if (approvals.isEmpty) onApprovalChanged?.call(null);
    notifyListeners();
  }

  void stop(AgentTask t) => send({'t': 'agent_stop', 'task': t.id});

  void setModel(String id) {
    if (!send({'t': 'agent_set', 'model': id})) return;
    model = id; // shown at once; the laptop confirms with agent_settings
    notifyListeners();
  }

  void setBudgets(int task, int daily) => send({'t': 'agent_set', 'task_budget_inr': task, 'daily_budget_inr': daily});

  void newConversation() => send({'t': 'agent_reset'});

  @override
  void dispose() {
    _noReply?.cancel();
    _sub.cancel();
    _link?.removeListener(_onLink);
    super.dispose();
  }
}
