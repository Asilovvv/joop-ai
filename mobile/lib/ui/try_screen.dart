import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'dialogue_screen.dart';

/// The panel's «Тестовый чат» on the phone: the owner writes as a customer and sees how the AI answers. Counted
/// nowhere; «Новый диалог» cancels what the test booked and starts over.
class TryScreen extends StatefulWidget {
  const TryScreen({super.key});

  @override
  State<TryScreen> createState() => _TryScreenState();
}

class _TryScreenState extends State<TryScreen> {
  final _text = TextEditingController();
  final _scroll = ScrollController();
  List<DialogueMessage> _messages = const [];
  List<(String, bool)> _notes = const [];
  String? _error;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _load(() async => (await context.read<JoopRepository>().tryChat(), const <(String, bool)>[]));
  }

  @override
  void dispose() {
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load(Future<(List<DialogueMessage>, List<(String, bool)>)> Function() call) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final (messages, notes) = await call();
      if (!mounted) return;
      setState(() {
        _messages = messages;
        _notes = notes;
      });
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _send() {
    final text = _text.text.trim();
    if (text.isEmpty || _busy) return;
    _text.clear();
    _load(() => context.read<JoopRepository>().trySend(text));
  }

  void _reset() {
    _load(() async {
      final cancelled = await context.read<JoopRepository>().tryReset();
      return (const <DialogueMessage>[], [if (cancelled > 0) (S.current.testBookingsCancelled(cancelled), true)]);
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    return Scaffold(
      appBar: AppBar(
        title: Text(s.tryTitle, style: const TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          TextButton(key: const Key('try-reset'), onPressed: _busy ? null : _reset, child: Text(s.newDialogue)),
        ],
      ),
      body: Column(children: [
        if (_busy) const LinearProgressIndicator(),
        Expanded(
          child: ListView(
            key: const Key('try-list'),
            controller: _scroll,
            padding: const EdgeInsets.all(12),
            children: [
              if (_messages.isEmpty) Padding(padding: const EdgeInsets.all(8), child: Text(s.tryHint)),
              for (final m in _messages) MessageBubble(message: m),
              for (final (text, ok) in _notes)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(text, style: TextStyle(color: ok ? Theme.of(context).colorScheme.outline : Theme.of(context).colorScheme.error)),
                ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(_error!, key: const Key('try-error'), style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
            ],
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 8, 8),
            child: Row(children: [
              Expanded(
                child: TextField(
                  key: const Key('try-input'),
                  controller: _text,
                  minLines: 1,
                  maxLines: 4,
                  textInputAction: TextInputAction.send,
                  decoration: InputDecoration(hintText: s.tryInputHint, border: const OutlineInputBorder()),
                  onSubmitted: (_) => _send(),
                ),
              ),
              IconButton(key: const Key('try-send'), tooltip: s.send, onPressed: _busy ? null : _send, icon: const Icon(Icons.send)),
            ]),
          ),
        ),
      ]),
    );
  }
}
