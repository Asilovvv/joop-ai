import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

/// The business's people (tables, groups) by niche, the panel's «Специалисты»: the sign-up example out, its own in.
/// The edit sheet only collects what was typed and closes; the screen sends it, so a reply can never close anything
/// but its own sheet, and a refusal is shown here, on the screen in front.
class PeopleScreen extends StatefulWidget {
  const PeopleScreen({super.key, required this.title});

  /// Shown until the list arrives: the niche's word from the account.
  final String title;

  @override
  State<PeopleScreen> createState() => _PeopleScreenState();
}

class _PeopleScreenState extends State<PeopleScreen> {
  PeopleInfo? _info;
  String? _error;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _run(() => context.read<JoopRepository>().people());
  }

  Future<void> _run(Future<PeopleInfo> Function() call, {String Function()? done}) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final info = await call();
      if (!mounted) return;
      setState(() => _info = info);
      final said = done?.call();
      if (said != null) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(said)));
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      if (_info == null) {
        setState(() => _error = e.message);
      } else {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(e.message)));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _edit(Person? person) async {
    final info = _info!;
    final result = await showModalBottomSheet<_Edit>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _PersonSheet(person: person, info: info),
    );
    if (result == null || !mounted) return;
    final repository = context.read<JoopRepository>();
    _run(() => result.delete ? repository.deletePerson(person!.id) : repository.savePerson(person?.id, result.person!));
  }

  /// Free times for one person: the sheet collects days, step and hours; the screen sends them.
  Future<void> _windows(Person person) async {
    final info = _info!;
    final asked = await showModalBottomSheet<_Windows>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _WindowsSheet(person: person, info: info),
    );
    if (asked == null || !mounted) return;
    final repository = context.read<JoopRepository>();
    var created = 0;
    _run(() async {
      final (n, info) = await repository.openWindows(person.id,
          days: asked.days, step: asked.step, start: asked.start, end: asked.end);
      created = n;
      return info;
    }, done: () => created > 0 ? S.current.windowsOpened(created) : S.current.windowsNone);
  }

  Future<void> _deleteExample() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: Text(S.current.peopleExampleConfirm),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: Text(S.current.cancel)),
          FilledButton(
              key: const Key('people-example-yes'),
              onPressed: () => Navigator.of(context).pop(true),
              child: Text(S.current.deleteExample)),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    final repository = context.read<JoopRepository>();
    var removed = 0;
    _run(() async {
      final (n, info) = await repository.deletePeopleExample();
      removed = n;
      return info;
    }, done: () => S.current.peopleExampleDeleted(removed));
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final info = _info;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(info?.label ?? widget.title, style: const TextStyle(fontWeight: FontWeight.w800))),
      floatingActionButton: info == null
          ? null
          : FloatingActionButton.extended(
              key: const Key('person-add'),
              onPressed: _busy ? null : () => _edit(null),
              icon: const Icon(Icons.person_add_alt),
              label: Text(s.newPerson),
            ),
      body: info == null
          ? Center(
              child: _error == null
                  ? const CircularProgressIndicator()
                  : Padding(padding: const EdgeInsets.all(24), child: Text(_error!, textAlign: TextAlign.center)))
          : ListView(
              key: const Key('people-list'),
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 96),
              children: [
                if (_busy) const LinearProgressIndicator(),
                if (info.people.any((p) => p.example))
                  Card(
                    key: const Key('people-example-banner'),
                    elevation: 0,
                    color: theme.colorScheme.tertiaryContainer,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(s.peopleExampleBanner),
                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton(
                            key: const Key('people-example-delete'),
                            onPressed: _busy ? null : _deleteExample,
                            child: Text(s.deleteExample),
                          ),
                        ),
                      ]),
                    ),
                  ),
                if (info.people.isEmpty) Padding(padding: const EdgeInsets.all(24), child: Text(s.peopleEmpty)),
                for (final p in info.people)
                  Card(
                    margin: const EdgeInsets.only(top: 8),
                    child: ListTile(
                      key: Key('person-${p.id}'),
                      onTap: _busy ? null : () => _edit(p),
                      title: Text(p.name, style: const TextStyle(fontWeight: FontWeight.w700)),
                      subtitle: Text([
                        if (p.role.isNotEmpty) p.role,
                        if (p.handles.isNotEmpty) p.handles,
                        if (info.capacity && p.capacity > 0) s.personSeats(p.capacity),
                        if (info.group && p.groupSize > 1) s.personGroupUpTo(p.groupSize),
                        if (info.booking && !p.example) s.freeAhead(p.free),
                      ].join(' · ')),
                      trailing: p.example
                          ? Chip(label: Text(s.exampleChip))
                          : info.booking
                              ? IconButton(
                                  key: Key('windows-${p.id}'),
                                  tooltip: s.openWindows,
                                  icon: Icon(Icons.event_available_outlined,
                                      color: p.free == 0 ? theme.colorScheme.error : null),
                                  onPressed: _busy ? null : () => _windows(p),
                                )
                              : const Icon(Icons.chevron_right),
                    ),
                  ),
              ],
            ),
    );
  }
}

/// What the sheet hands back: the person as typed, or a request to retire them.
class _Edit {
  const _Edit.save(this.person) : delete = false;
  const _Edit.delete()
      : person = null,
        delete = true;

  final Person? person;
  final bool delete;
}

class _PersonSheet extends StatefulWidget {
  const _PersonSheet({required this.person, required this.info});

  final Person? person;
  final PeopleInfo info;

  @override
  State<_PersonSheet> createState() => _PersonSheetState();
}

class _PersonSheetState extends State<_PersonSheet> {
  late final _name = TextEditingController(text: widget.person?.name ?? '');
  late final _role = TextEditingController(text: widget.person?.role ?? '');
  late final _handles = TextEditingController(text: widget.person?.handles ?? '');
  late final _capacity = TextEditingController(text: '${widget.person?.capacity ?? 0}');
  late final _group = TextEditingController(text: '${widget.person?.groupSize ?? 0}');
  bool _empty = false;

  @override
  void dispose() {
    for (final c in [_name, _role, _handles, _capacity, _group]) {
      c.dispose();
    }
    super.dispose();
  }

  void _save() {
    if (_name.text.trim().isEmpty) {
      setState(() => _empty = true);
      return;
    }
    Navigator.of(context).pop(_Edit.save(Person(
      id: widget.person?.id ?? 0,
      name: _name.text.trim(),
      role: _role.text.trim(),
      handles: _handles.text.trim(),
      capacity: int.tryParse(_capacity.text.trim()) ?? 0,
      groupSize: int.tryParse(_group.text.trim()) ?? 0,
    )));
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    InputDecoration field(String label, {String? error}) =>
        InputDecoration(labelText: label, errorText: error, border: const OutlineInputBorder());
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(widget.person?.name ?? widget.info.label, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          TextField(
              key: const Key('person-name'),
              controller: _name,
              textCapitalization: TextCapitalization.words,
              decoration: field(s.personName, error: _empty ? s.serviceNameEmpty : null)),
          const SizedBox(height: 12),
          TextField(key: const Key('person-role'), controller: _role, decoration: field(s.personRole)),
          const SizedBox(height: 12),
          TextField(
              key: const Key('person-handles'), controller: _handles, maxLines: 2, decoration: field(s.personHandles)),
          if (widget.info.capacity) ...[
            const SizedBox(height: 12),
            TextField(
                key: const Key('person-capacity'),
                controller: _capacity,
                keyboardType: TextInputType.number,
                decoration: field(s.personCapacity)),
          ],
          if (widget.info.group) ...[
            const SizedBox(height: 12),
            TextField(
                key: const Key('person-group'),
                controller: _group,
                keyboardType: TextInputType.number,
                decoration: field(s.personGroup)),
          ],
          const SizedBox(height: 16),
          FilledButton(key: const Key('person-save'), onPressed: _save, child: Text(s.save)),
          if (widget.person != null) ...[
            TextButton(
              key: const Key('person-delete'),
              onPressed: () => Navigator.of(context).pop(const _Edit.delete()),
              style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
              child: Text(s.personDelete),
            ),
            Text(s.personDeleteNote, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
          ],
        ]),
      ),
    );
  }
}

/// What the windows sheet hands back.
class _Windows {
  const _Windows(this.days, this.step, this.start, this.end);

  final int days;
  final int step;
  final String start;
  final String end;
}

class _WindowsSheet extends StatefulWidget {
  const _WindowsSheet({required this.person, required this.info});

  final Person person;
  final PeopleInfo info;

  @override
  State<_WindowsSheet> createState() => _WindowsSheetState();
}

class _WindowsSheetState extends State<_WindowsSheet> {
  late final _start = TextEditingController(text: widget.info.workStart);
  late final _end = TextEditingController(text: widget.info.workEnd);
  int _days = 14;
  int _step = 60;
  bool _badTime = false;

  static final _time = RegExp(r'^([01]?\d|2[0-3]):[0-5]\d$');

  @override
  void dispose() {
    _start.dispose();
    _end.dispose();
    super.dispose();
  }

  void _open() {
    final start = _start.text.trim(), end = _end.text.trim();
    if (!_time.hasMatch(start) || !_time.hasMatch(end)) {
      setState(() => _badTime = true);
      return;
    }
    Navigator.of(context).pop(_Windows(_days, _step, start, end));
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    Widget choice<T>(
            String label, List<T> values, T current, void Function(T) pick, String Function(T) text, String key) =>
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 6),
          Wrap(spacing: 6, children: [
            for (final v in values)
              ChoiceChip(
                  key: Key('$key-$v'),
                  label: Text(text(v)),
                  selected: v == current,
                  onSelected: (_) => setState(() => pick(v))),
          ]),
        ]);
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('${s.windowsTitle}: ${widget.person.name}', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 4),
          Text(s.windowsHint, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          choice(s.windowsDays, const [7, 14, 30], _days, (v) => _days = v, (v) => '$v', 'days'),
          const SizedBox(height: 12),
          choice(s.windowsStep, const [30, 45, 60, 90], _step, (v) => _step = v, (v) => '$v', 'step'),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: TextField(
                  key: const Key('windows-start'),
                  controller: _start,
                  keyboardType: TextInputType.datetime,
                  decoration: InputDecoration(
                      labelText: s.workStart,
                      border: const OutlineInputBorder(),
                      errorText: _badTime ? s.timeFormat : null)),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                  key: const Key('windows-end'),
                  controller: _end,
                  keyboardType: TextInputType.datetime,
                  decoration: InputDecoration(labelText: s.workEnd, border: const OutlineInputBorder())),
            ),
          ]),
          const SizedBox(height: 16),
          FilledButton(key: const Key('windows-open'), onPressed: _open, child: Text(s.openWindows)),
        ]),
      ),
    );
  }
}
