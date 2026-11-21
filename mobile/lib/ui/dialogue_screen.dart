import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/dialogue_cubit.dart';
import '../bloc/load_status.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'theme.dart';

/// A request's dialogue: what the customer and the AI wrote, and the owner's reply through the customer's channel.
class DialogueScreen extends StatelessWidget {
  const DialogueScreen({super.key, required this.conversationId, required this.title, this.onAnswered});

  final int conversationId;
  final String title;

  /// Called after a reply went out (the request is closed on the server).
  final VoidCallback? onAnswered;

  @override
  Widget build(BuildContext context) => BlocProvider(
        create: (_) => DialogueCubit(context.read<JoopRepository>(), conversationId)..load(),
        child: _Dialogue(title: title, onAnswered: onAnswered),
      );
}

class _Dialogue extends StatefulWidget {
  const _Dialogue({required this.title, this.onAnswered});

  final String title;
  final VoidCallback? onAnswered;

  @override
  State<_Dialogue> createState() => _DialogueState();
}

class _DialogueState extends State<_Dialogue> {
  final _text = TextEditingController();
  final _scroll = ScrollController();

  @override
  void dispose() {
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (await context.read<DialogueCubit>().reply(_text.text)) {
      _text.clear();
      widget.onAnswered?.call();
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title, style: const TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          BlocBuilder<DialogueCubit, DialogueState>(
            buildWhen: (a, b) => a.dialogue?.aiPaused != b.dialogue?.aiPaused || a.sending != b.sending,
            builder: (context, state) {
              final d = state.dialogue;
              if (d == null) return const SizedBox.shrink();
              return IconButton(
                key: const Key('ai-switch'),
                tooltip: d.aiPaused ? S.current.aiOn : S.current.aiOff,
                icon: Icon(d.aiPaused ? Icons.smart_toy_outlined : Icons.pause_circle_outline),
                onPressed: state.sending ? null : () => context.read<DialogueCubit>().switchAi(d.aiPaused),
              );
            },
          ),
        ],
      ),
      body: BlocConsumer<DialogueCubit, DialogueState>(
        listenWhen: (a, b) => b.notice != null || (b.error != null && b.dialogue != null),
        listener: (context, state) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(state.notice ?? state.error!)));
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
          });
        },
        builder: (context, state) {
          final dialogue = state.dialogue;
          if (dialogue == null) {
            return Center(
              child: state.status == LoadStatus.failure
                  ? Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(state.error ?? s.loadFailed),
                      TextButton(onPressed: () => context.read<DialogueCubit>().load(), child: Text(s.retry)),
                    ])
                  : const CircularProgressIndicator(),
            );
          }
          final blocked = dialogue.replyBlocked;
          return Column(
            children: [
              Expanded(
                child: ListView(
                  controller: _scroll,
                  padding: const EdgeInsets.all(12),
                  children: [for (final m in dialogue.messages) MessageBubble(message: m)],
                ),
              ),
              if (dialogue.aiPaused && dialogue.aiPausedUntil != null)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                  child: Text(
                    s.aiPausedNote(_until(dialogue.aiPausedUntil!), s.pauseWords(dialogue.takeoverMinutes)),
                    key: const Key('ai-paused'),
                    style: theme.textTheme.bodySmall,
                    textAlign: TextAlign.center,
                  ),
                ),
              SafeArea(
                top: false,
                child: blocked.isNotEmpty
                    ? Container(
                        key: const Key('reply-blocked'),
                        width: double.infinity,
                        margin: const EdgeInsets.all(12),
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: theme.colorScheme.errorContainer,
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Text(
                          [blocked, s.callInstead(formatPhone(dialogue.customerPhone))].where((x) => x.isNotEmpty).join('\n'),
                          style: TextStyle(color: theme.colorScheme.onErrorContainer),
                        ),
                      )
                    : Column(mainAxisSize: MainAxisSize.min, children: [
                        if (dialogue.quickReplies.isNotEmpty)
                          SizedBox(
                            height: 44,
                            child: ListView(
                              key: const Key('quick-replies'),
                              scrollDirection: Axis.horizontal,
                              padding: const EdgeInsets.symmetric(horizontal: 12),
                              children: [
                                for (final r in dialogue.quickReplies)
                                  Padding(
                                    padding: const EdgeInsets.only(right: 6),
                                    child: ActionChip(
                                      label: Text(r.title),
                                      // into the box, not sent: the person reads it and presses send
                                      onPressed: () => _text.value = TextEditingValue(
                                        text: r.text,
                                        selection: TextSelection.collapsed(offset: r.text.length),
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        Padding(
                          padding: const EdgeInsets.fromLTRB(12, 4, 8, 8),
                          child: Row(children: [
                            Expanded(
                              child: TextField(
                                key: const Key('reply-input'),
                                controller: _text,
                                minLines: 1,
                                maxLines: 5,
                                decoration: InputDecoration(hintText: s.answerHint),
                              ),
                            ),
                            const SizedBox(width: 6),
                            state.sending
                                ? const Padding(
                                    padding: EdgeInsets.all(12),
                                    child: SizedBox(
                                        width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2)),
                                  )
                                : IconButton.filled(
                                    key: const Key('reply-send'),
                                    tooltip: s.send,
                                    onPressed: _send,
                                    icon: const Icon(Icons.send),
                                  ),
                          ]),
                        ),
                      ]),
              ),
            ],
          );
        },
      ),
    );
  }
}

/// "14:30", or "пн, 16 ноя, 09:00" when the pause runs past today.
String _until(DateTime until) {
  final now = DateTime.now();
  final today = until.year == now.year && until.month == now.month && until.day == now.day;
  return today ? formatTime(until) : '${formatDay(until)}, ${formatTime(until)}';
}

/// One message of a dialogue: the customer on the left, the AI and staff on the right.
class MessageBubble extends StatelessWidget {
  const MessageBubble({super.key, required this.message});

  final DialogueMessage message;

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final scheme = Theme.of(context).colorScheme;
    final customer = message.fromCustomer;
    final staff = message.role == 'staff';
    final who =
        customer ? s.customerLabel : (staff ? (message.author.isEmpty ? s.staffReply : message.author) : s.aiLabel);
    return Align(
      // The business's side (the AI and staff) on the right, as in the owner's own messenger.
      alignment: customer ? Alignment.centerLeft : Alignment.centerRight,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.8),
        decoration: BoxDecoration(
          color: customer ? cardColor(scheme) : (staff ? brandColor : brandColor.withValues(alpha: 0.14)),
          borderRadius: BorderRadius.circular(18),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$who · ${formatTime(message.at)}',
              style:
                  TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: staff ? Colors.white70 : scheme.outline)),
          const SizedBox(height: 2),
          Text(message.text, style: TextStyle(color: staff ? Colors.white : scheme.onSurface)),
        ]),
      ),
    );
  }
}
