import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

/// The address, phone and opening hours the AI tells customers, and the hours bookable times follow: the launch
/// list's «Контакты и часы работы» step on the phone. Fields still the sign-up example's are marked.
class ContactsScreen extends StatefulWidget {
  const ContactsScreen({super.key});

  @override
  State<ContactsScreen> createState() => _ContactsScreenState();
}

class _ContactsScreenState extends State<ContactsScreen> {
  final _address = TextEditingController();
  final _phone = TextEditingController();
  final _hours = TextEditingController();
  final _start = TextEditingController();
  final _end = TextEditingController();
  ContactsInfo? _info;
  Set<int> _daysOff = {};
  String? _error;
  bool _busy = true;

  static final _time = RegExp(r'^([01]?\d|2[0-3]):[0-5]\d$');

  @override
  void initState() {
    super.initState();
    _run(() => context.read<JoopRepository>().contacts(), saved: false);
  }

  @override
  void dispose() {
    for (final c in [_address, _phone, _hours, _start, _end]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _run(Future<ContactsInfo> Function() call, {required bool saved}) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final info = await call();
      if (!mounted) return;
      setState(() {
        _info = info;
        _address.text = info.address;
        _phone.text = info.phone;
        _hours.text = info.hoursText;
        _start.text = info.workStart;
        _end.text = info.workEnd;
        _daysOff = {...info.daysOff};
      });
      if (saved) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(S.current.saved)));
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _save() {
    if (_busy) return;
    if (!_time.hasMatch(_start.text.trim()) || !_time.hasMatch(_end.text.trim())) {
      setState(() => _error = S.current.timeFormat);
      return;
    }
    final info = ContactsInfo(
      address: _address.text.trim(),
      phone: _phone.text.trim(),
      hoursText: _hours.text.trim(),
      workStart: _start.text.trim(),
      workEnd: _end.text.trim(),
      daysOff: _daysOff,
    );
    _run(() => context.read<JoopRepository>().saveContacts(info), saved: true);
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final info = _info;
    InputDecoration field(String label, String key, {String? hint}) => InputDecoration(
          labelText: label,
          hintText: hint,
          helperText: info != null && info.example.contains(key) ? s.fromExample : null,
          helperStyle: TextStyle(color: Theme.of(context).colorScheme.error),
          border: const OutlineInputBorder(),
        );
    return Scaffold(
      appBar: AppBar(title: Text(s.contactsTitle, style: const TextStyle(fontWeight: FontWeight.w800))),
      body: info == null
          ? Center(
              child: _error == null
                  ? const CircularProgressIndicator()
                  : Padding(padding: const EdgeInsets.all(24), child: Text(_error!, textAlign: TextAlign.center)))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_busy) const LinearProgressIndicator(),
                TextField(key: const Key('contacts-address'), controller: _address, decoration: field(s.address, 'address')),
                const SizedBox(height: 12),
                TextField(
                    key: const Key('contacts-phone'),
                    controller: _phone,
                    keyboardType: TextInputType.phone,
                    decoration: field(s.phone, 'phone')),
                const SizedBox(height: 12),
                TextField(
                    key: const Key('contacts-hours'),
                    controller: _hours,
                    decoration: field(s.hoursText, 'hours_text', hint: s.hoursTextHint)),
                const SizedBox(height: 12),
                Row(children: [
                  Expanded(
                    child: TextField(
                      key: const Key('contacts-start'),
                      controller: _start,
                      keyboardType: TextInputType.datetime,
                      decoration: InputDecoration(labelText: s.workStart, border: const OutlineInputBorder()),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextField(
                      key: const Key('contacts-end'),
                      controller: _end,
                      keyboardType: TextInputType.datetime,
                      decoration: InputDecoration(labelText: s.workEnd, border: const OutlineInputBorder()),
                    ),
                  ),
                ]),
                const SizedBox(height: 16),
                Text(s.daysOffLabel, style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: 8),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  for (var d = 1; d <= 7; d++)
                    FilterChip(
                      key: Key('day-off-$d'),
                      label: Text(s.weekdays[d - 1]),
                      selected: _daysOff.contains(d),
                      onSelected: (on) => setState(() => on ? _daysOff.add(d) : _daysOff.remove(d)),
                    ),
                ]),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(_error!, key: const Key('contacts-error'),
                        style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  ),
                const SizedBox(height: 16),
                FilledButton(key: const Key('contacts-save'), onPressed: _busy ? null : _save, child: Text(s.save)),
              ],
            ),
    );
  }
}
