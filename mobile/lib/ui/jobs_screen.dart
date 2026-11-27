import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

/// The panel's «Заказы в работе» at the counter: a receipt taken for what was left (or is made to order), its status,
/// and «готов», which sends the customer the panel's message. The sheets only collect what was typed and close; the
/// screen sends it, so a refusal is shown here, on the screen in front.
class JobsScreen extends StatefulWidget {
  const JobsScreen({super.key});

  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen> {
  final _search = TextEditingController();
  JobsInfo? _info;
  String? _error;
  bool _busy = true;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _run(() => context.read<JoopRepository>().jobs());
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _run(Future<JobsInfo> Function() call, {String? Function()? done}) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final info = await call();
      if (!mounted) return;
      setState(() => _info = info);
      final said = done?.call();
      if (said != null) _say(said);
    } on ApiException catch (e) {
      if (!mounted) return;
      if (_info == null) {
        setState(() => _error = e.message);
      } else {
        _say(e.message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _say(String text) => ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));

  Future<void> _load() => _run(() => context.read<JoopRepository>().jobs(query: _query));

  void _find(String text) {
    _query = text.trim();
    _load();
  }

  Future<void> _add() async {
    final info = _info!;
    final typed = await showModalBottomSheet<Job>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _NewJobSheet(info: info),
    );
    if (typed == null || !mounted) return;
    final repository = context.read<JoopRepository>();
    _search.clear();
    _query = ''; // the new receipt is in sight, whatever was searched before
    var number = '';
    _run(() async {
      final (job, info) = await repository.addJob(typed);
      number = job.number;
      return info;
    }, done: () => S.current.jobAccepted(number));
  }

  Future<void> _change(Job job) async {
    final info = _info!;
    final asked = await showModalBottomSheet<_Change>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _JobSheet(job: job, delivered: info.delivered),
    );
    if (asked == null || !mounted) return;
    final repository = context.read<JoopRepository>();
    bool? told;
    _run(() async {
      final (said, info) = await repository.changeJob(job.id,
          status: asked.status, note: asked.note, price: asked.price, readyBy: asked.readyBy, query: _query);
      told = said;
      return info;
    }, done: () {
      final s = S.current;
      return switch (told) {
        true => s.jobReadyTold(job.number),
        false => s.jobReadyCall(job.number, formatPhone(job.customerPhone)),
        null => s.jobSaved(job.number, s.jobStatus(asked.status, info.delivered)),
      };
    });
  }

  Future<void> _deleteExample() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: Text(S.current.jobsExampleConfirm),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: Text(S.current.cancel)),
          FilledButton(
              key: const Key('jobs-example-yes'),
              onPressed: () => Navigator.of(context).pop(true),
              child: Text(S.current.deleteExample)),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    final repository = context.read<JoopRepository>();
    var removed = 0;
    _run(() async {
      final (n, info) = await repository.deleteJobsExample();
      removed = n;
      return info;
    }, done: () => S.current.jobsExampleDeleted(removed));
  }

  Widget _tile(Job j, JobsInfo info, {required bool open}) {
    final s = S.current;
    final theme = Theme.of(context);
    final ready = j.status == 'ready';
    final due = DateTime.tryParse(j.readyBy);
    final details = [
      if (j.customerName.isNotEmpty) j.customerName,
      if (j.customerPhone.isNotEmpty) formatPhone(j.customerPhone),
      if (due != null && open && !ready) s.jobDue('${due.day.toString().padLeft(2, '0')}.${due.month.toString().padLeft(2, '0')}'),
      if (j.price.isNotEmpty) priceWithSom(j.price),
      if (j.note.isNotEmpty) j.note,
    ].join(' · ');
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: ListTile(
        key: Key('job-${j.id}'),
        onTap: open && !_busy ? () => _change(j) : null,
        title: Text('№${j.number} · ${j.item}', style: const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(
            s.jobStatus(j.status, info.delivered) + (ready && j.readyNotified ? ' · ${s.jobTold}' : ''),
            style: TextStyle(
                fontWeight: FontWeight.w600, color: ready ? theme.colorScheme.primary : theme.colorScheme.onSurfaceVariant),
          ),
          if (details.isNotEmpty) Text(details),
        ]),
        trailing: j.example ? Chip(label: Text(s.exampleChip)) : (open ? const Icon(Icons.chevron_right) : null),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final info = _info;
    final theme = Theme.of(context);
    if (info == null) {
      return Center(
        child: _error == null
            ? const CircularProgressIndicator()
            : Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(_error!, textAlign: TextAlign.center),
                  TextButton(onPressed: _load, child: Text(s.retry)),
                ]),
              ),
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        key: const Key('jobs-list'),
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        children: [
          if (_busy) const LinearProgressIndicator(),
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
            child: Text(s.jobsHint, style: theme.textTheme.bodySmall),
          ),
          FilledButton.icon(
            key: const Key('job-add'),
            onPressed: _busy ? null : _add,
            icon: const Icon(Icons.add),
            label: Text(s.newJob),
          ),
          const SizedBox(height: 8),
          TextField(
            key: const Key('jobs-search'),
            controller: _search,
            textInputAction: TextInputAction.search,
            onSubmitted: _find,
            decoration: InputDecoration(
              hintText: s.jobsSearch,
              prefixIcon: const Icon(Icons.search),
              border: const OutlineInputBorder(),
              isDense: true,
              suffixIcon: _query.isEmpty
                  ? null
                  : IconButton(
                      key: const Key('jobs-search-clear'),
                      icon: const Icon(Icons.close),
                      onPressed: () {
                        _search.clear();
                        _find('');
                      }),
            ),
          ),
          if ([...info.open, ...info.done].any((j) => j.example))
            Card(
              key: const Key('jobs-example-banner'),
              elevation: 0,
              margin: const EdgeInsets.only(top: 8),
              color: theme.colorScheme.tertiaryContainer,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(s.jobsExampleBanner),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      key: const Key('jobs-example-delete'),
                      onPressed: _busy ? null : _deleteExample,
                      child: Text(s.deleteExample),
                    ),
                  ),
                ]),
              ),
            ),
          if (info.open.isEmpty) Padding(padding: const EdgeInsets.all(24), child: Text(s.jobsEmpty)),
          for (final j in info.open) _tile(j, info, open: true),
          if (info.done.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 20, 4, 0),
              child: Text(s.jobsDone(info.delivered), style: theme.textTheme.titleSmall),
            ),
            for (final j in info.done) _tile(j, info, open: false),
          ],
        ],
      ),
    );
  }
}

String _isoDay(DateTime d) => '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// A date field: shows the chosen day, opens a calendar, and can be cleared.
class _DueField extends StatelessWidget {
  const _DueField({required this.value, required this.onPick, required this.fieldKey});

  final String value;
  final ValueChanged<String> onPick;
  final Key fieldKey;

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final day = DateTime.tryParse(value);
    return InputDecorator(
      decoration: InputDecoration(labelText: s.jobReadyBy, border: const OutlineInputBorder()),
      child: Row(children: [
        Expanded(
          child: Text(day == null ? '—' : formatDay(day)),
        ),
        TextButton(
          key: fieldKey,
          onPressed: () async {
            final now = DateTime.now();
            final picked = await showDatePicker(
              context: context,
              initialDate: day ?? now,
              firstDate: DateTime(now.year - 1),
              lastDate: DateTime(now.year + 2),
            );
            if (picked != null) onPick(_isoDay(picked));
          },
          child: Text(s.jobPickDate),
        ),
      ]),
    );
  }
}

class _NewJobSheet extends StatefulWidget {
  const _NewJobSheet({required this.info});

  final JobsInfo info;

  @override
  State<_NewJobSheet> createState() => _NewJobSheetState();
}

class _NewJobSheetState extends State<_NewJobSheet> {
  late final _number = TextEditingController(text: widget.info.nextNumber);
  final _phone = TextEditingController();
  final _name = TextEditingController();
  final _item = TextEditingController();
  final _price = TextEditingController();
  final _note = TextEditingController();
  String _due = '';
  bool _tried = false;

  @override
  void dispose() {
    for (final c in [_number, _phone, _name, _item, _price, _note]) {
      c.dispose();
    }
    super.dispose();
  }

  /// The server checks the phone as well; this only spares a round trip for an empty field.
  bool get _phoneOk => _phone.text.replaceAll(RegExp(r'\D'), '').length >= 9;

  void _save() {
    if (_item.text.trim().isEmpty || !_phoneOk) {
      setState(() => _tried = true);
      return;
    }
    Navigator.of(context).pop(Job(
      id: 0,
      number: _number.text.trim(),
      item: _item.text.trim(),
      status: 'accepted',
      customerName: _name.text.trim(),
      customerPhone: _phone.text.trim(),
      price: _price.text.trim(),
      readyBy: _due,
      note: _note.text.trim(),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final info = widget.info;
    InputDecoration field(String label, {String? hint, String? error}) =>
        InputDecoration(labelText: label, hintText: hint, errorText: error, border: const OutlineInputBorder());
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(s.newJob, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          TextField(
              key: const Key('job-item'),
              controller: _item,
              maxLines: 2,
              decoration: field(info.itemLabel, hint: info.itemHint,
                  error: _tried && _item.text.trim().isEmpty ? s.jobFill : null)),
          const SizedBox(height: 12),
          TextField(
              key: const Key('job-phone'),
              controller: _phone,
              keyboardType: TextInputType.phone,
              decoration: field(s.jobPhone, hint: '0555 123 456', error: _tried && !_phoneOk ? s.jobFill : null)),
          const SizedBox(height: 12),
          TextField(
              key: const Key('job-name'),
              controller: _name,
              textCapitalization: TextCapitalization.words,
              decoration: field(s.jobCustomer)),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: TextField(key: const Key('job-number'), controller: _number, decoration: field(s.jobNumber))),
            const SizedBox(width: 12),
            Expanded(
                child: TextField(
                    key: const Key('job-price'), controller: _price, decoration: field(s.jobPrice, hint: info.priceHint))),
          ]),
          const SizedBox(height: 12),
          _DueField(value: _due, onPick: (v) => setState(() => _due = v), fieldKey: const Key('job-due')),
          const SizedBox(height: 12),
          TextField(key: const Key('job-note'), controller: _note, decoration: field(s.jobNote, hint: info.noteHint)),
          const SizedBox(height: 16),
          FilledButton(key: const Key('job-save'), onPressed: _save, child: Text(s.newJob)),
        ]),
      ),
    );
  }
}

/// What the status sheet hands back.
class _Change {
  const _Change(this.status, this.note, this.price, this.readyBy);

  final String status;
  final String note;
  final String price;
  final String readyBy;
}

class _JobSheet extends StatefulWidget {
  const _JobSheet({required this.job, required this.delivered});

  final Job job;
  final bool delivered;

  @override
  State<_JobSheet> createState() => _JobSheetState();
}

class _JobSheetState extends State<_JobSheet> {
  static const _statuses = ['accepted', 'in_progress', 'ready', 'issued', 'cancelled'];

  late String _status = widget.job.status;
  late String _due = widget.job.readyBy;
  late final _note = TextEditingController(text: widget.job.note);
  late final _price = TextEditingController(text: widget.job.price);

  @override
  void dispose() {
    _note.dispose();
    _price.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final job = widget.job;
    InputDecoration field(String label) => InputDecoration(labelText: label, border: const OutlineInputBorder());
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('№${job.number} · ${job.item}', style: Theme.of(context).textTheme.titleLarge),
          if (job.customerPhone.isNotEmpty)
            Text([job.customerName, formatPhone(job.customerPhone)].where((x) => x.isNotEmpty).join(' · '),
                style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final st in _statuses)
              ChoiceChip(
                key: Key('job-status-$st'),
                label: Text(s.jobStatus(st, widget.delivered)),
                selected: st == _status,
                onSelected: (_) => setState(() => _status = st),
              ),
          ]),
          const SizedBox(height: 12),
          TextField(key: const Key('job-edit-note'), controller: _note, decoration: field(s.jobNote)),
          const SizedBox(height: 12),
          TextField(key: const Key('job-edit-price'), controller: _price, decoration: field(s.jobPrice)),
          const SizedBox(height: 12),
          _DueField(value: _due, onPick: (v) => setState(() => _due = v), fieldKey: const Key('job-edit-due')),
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('job-edit-save'),
            onPressed: () =>
                Navigator.of(context).pop(_Change(_status, _note.text.trim(), _price.text.trim(), _due)),
            child: Text(s.save),
          ),
        ]),
      ),
    );
  }
}
