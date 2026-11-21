import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/strings.dart';
import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'qr_code.dart';

/// The owner's launch checklist, the panel's «Запуск»: the Telegram bot is connected here by its token and booking by
/// link is switched on with one tap; the other steps (prices, people, hours) name their page in the panel.
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  final _token = TextEditingController();
  SetupInfo? _info;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _run(() => context.read<JoopRepository>().setup());
  }

  @override
  void dispose() {
    _token.dispose();
    super.dispose();
  }

  Future<void> _run(Future<SetupInfo> Function() call) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final info = await call();
      if (mounted) setState(() => _info = info);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _connect() {
    final token = _token.text.trim();
    if (token.isEmpty || _busy) return;
    _run(() async {
      final info = await context.read<JoopRepository>().connectTelegram(token);
      _token.clear();
      return info;
    });
  }

  @override
  Widget build(BuildContext context) {
    final info = _info;
    return Scaffold(
      appBar: AppBar(title: Text(S.current.setupTitle, style: const TextStyle(fontWeight: FontWeight.w800))),
      body: info == null
          ? Center(
              child: _error == null
                  ? const CircularProgressIndicator()
                  : Padding(padding: const EdgeInsets.all(24), child: Text(_error!, textAlign: TextAlign.center)))
          : ListView(
              key: const Key('setup-list'),
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
              children: [
                Text(S.current.setupProgress(info.done, info.steps.length),
                    key: const Key('setup-progress'), style: Theme.of(context).textTheme.titleMedium),
                if (_busy) const Padding(padding: EdgeInsets.only(top: 8), child: LinearProgressIndicator()),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(_error!, key: const Key('setup-error'),
                        style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  ),
                for (final (text, ok) in info.notes)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(text, style: TextStyle(color: ok ? null : Theme.of(context).colorScheme.error)),
                  ),
                const SizedBox(height: 8),
                for (final step in info.steps) _step(context, info, step),
                if (info.pageAvailable) _pageBooking(context, info),
              ],
            ),
    );
  }

  Widget _step(BuildContext context, SetupInfo info, SetupStep step) {
    final telegram = step.key == 'telegram';
    return Card(
      key: Key('step-${step.key}'),
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Icon(step.done ? Icons.check_circle : Icons.radio_button_unchecked,
                  color: step.done ? Colors.green : null, key: Key('step-${step.key}-${step.done ? 'done' : 'todo'}')),
              const SizedBox(width: 8),
              Expanded(child: Text(step.title, style: const TextStyle(fontWeight: FontWeight.w700))),
            ]),
            if (step.hint.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(step.hint)),
            if (telegram && info.botConnected && info.botUsername.isNotEmpty)
              Padding(padding: const EdgeInsets.only(top: 4), child: SelectableText('@${info.botUsername}')),
            if (telegram && !info.botConnected) ...[
              Padding(padding: const EdgeInsets.only(top: 8), child: Text(S.current.botHowTo)),
              const SizedBox(height: 8),
              TextField(
                key: const Key('bot-token'),
                controller: _token,
                autocorrect: false,
                enableSuggestions: false,
                decoration: InputDecoration(labelText: S.current.botToken, border: const OutlineInputBorder()),
                onSubmitted: (_) => _connect(),
              ),
              const SizedBox(height: 8),
              FilledButton(key: const Key('bot-connect'), onPressed: _busy ? null : _connect,
                  child: Text(S.current.connectBot)),
            ] else if (!step.done && step.panel.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: SelectableText('${S.current.inPanel} ${step.panel}', style: Theme.of(context).textTheme.bodySmall),
              ),
          ],
        ),
      ),
    );
  }

  /// The QR across the whole screen, for a customer to scan from the owner's phone.
  void _showQr(BuildContext context, SetupInfo info) {
    showDialog<void>(
      context: context,
      builder: (context) => Dialog(
        key: const Key('qr-full'),
        backgroundColor: Colors.white,
        insetPadding: const EdgeInsets.all(16),
        child: InkWell(
          onTap: () => Navigator.of(context).pop(),
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: LayoutBuilder(
              builder: (context, box) => QrCode(rows: info.pageQr, size: box.maxWidth),
            ),
          ),
        ),
      ),
    );
  }

  Widget _pageBooking(BuildContext context, SetupInfo info) {
    return Card(
      key: const Key('page-booking'),
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(4, 4, 12, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SwitchListTile(
              key: const Key('page-booking-switch'),
              title: Text(S.current.pageBookingSwitch, style: const TextStyle(fontWeight: FontWeight.w700)),
              value: info.pageOn,
              onChanged: _busy ? null : (on) => _run(() => context.read<JoopRepository>().setPageBooking(on)),
            ),
            Padding(
              padding: const EdgeInsets.only(left: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(S.current.pageBookingHint),
                const SizedBox(height: 4),
                Row(children: [
                  Expanded(child: SelectableText(info.pageUrl, key: const Key('page-booking-url'))),
                  IconButton(
                    tooltip: S.current.copy,
                    icon: const Icon(Icons.copy),
                    onPressed: () => Clipboard.setData(ClipboardData(text: info.pageUrl)),
                  ),
                ]),
                if (info.pageOn && info.pageQr.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(S.current.qrHint),
                  const SizedBox(height: 8),
                  Center(
                    child: InkWell(
                      key: const Key('page-booking-qr'),
                      onTap: () => _showQr(context, info),
                      child: QrCode(rows: info.pageQr, size: 180),
                    ),
                  ),
                ],
                if (info.pageOn && !info.pageWorks && info.pageWhy == 'unpaid')
                  Text(S.current.pageBookingUnpaid, key: const Key('page-booking-unpaid'),
                      style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ]),
            ),
          ],
        ),
      ),
    );
  }
}
