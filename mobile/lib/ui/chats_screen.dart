import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/chats_cubit.dart';
import '../bloc/load_status.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'dialogue_screen.dart';
import 'theme.dart';

/// Every real chat the AI is having, newest first (the panel's Диалоги); a tap opens it, with the reply box.
class ChatsScreen extends StatelessWidget {
  const ChatsScreen({super.key});

  @override
  Widget build(BuildContext context) => BlocProvider(
        create: (_) => ChatsCubit(context.read<JoopRepository>())..load(),
        child: const _Chats(),
      );
}

class _Chats extends StatefulWidget {
  const _Chats();

  @override
  State<_Chats> createState() => _ChatsState();
}

class _ChatsState extends State<_Chats> {
  Timer? _debounce;

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _search(String text) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () => context.read<ChatsCubit>().load(text));
  }

  Future<void> _open(BuildContext context, ChatSummary chat) async {
    final cubit = context.read<ChatsCubit>();
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => DialogueScreen(
        conversationId: chat.id,
        title: chat.customerName.isEmpty ? channelName(chat.channel) : chat.customerName,
      ),
    ));
    cubit.load(); // a reply moved the chat up and paused the AI
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(s.chats, style: const TextStyle(fontWeight: FontWeight.w800))),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: TextField(
            key: const Key('chats-search'),
            onChanged: _search,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(prefixIcon: const Icon(Icons.search), hintText: s.chatsSearch),
          ),
        ),
        Expanded(
          child: BlocBuilder<ChatsCubit, ChatsState>(
            builder: (context, state) {
              if (state.chats.isEmpty) {
                return Center(
                  child: switch (state.status) {
                    LoadStatus.failure => Column(mainAxisSize: MainAxisSize.min, children: [
                        Text(state.error ?? s.loadFailed),
                        TextButton(onPressed: () => context.read<ChatsCubit>().load(), child: Text(s.retry)),
                      ]),
                    LoadStatus.success => Text(state.query.isEmpty ? s.chatsEmpty : s.chatsNotFound),
                    _ => const CircularProgressIndicator(),
                  },
                );
              }
              return RefreshIndicator(
                onRefresh: () => context.read<ChatsCubit>().load(),
                child: ListView.builder(
                  padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
                  itemCount: state.chats.length,
                  itemBuilder: (context, i) {
                    final c = state.chats[i];
                    final prefix = switch (c.lastRole) { 'ai' => s.aiPrefix, 'staff' => s.youPrefix, _ => '' };
                    return Card(
                      elevation: 0,
                      color: cardColor(theme.colorScheme),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                      child: ListTile(
                        key: Key('chat-${c.id}'),
                        onTap: () => _open(context, c),
                        title: Text(c.customerName.isEmpty ? s.noName : c.customerName,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontWeight: FontWeight.w600)),
                        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          if (c.lastText.isNotEmpty)
                            Text('$prefix${c.lastText}', maxLines: 2, overflow: TextOverflow.ellipsis),
                          const SizedBox(height: 4),
                          Wrap(spacing: 6, runSpacing: 4, children: [
                            _Tag(channelName(c.channel), theme.colorScheme.primary),
                            if (c.aiPaused) _Tag(s.aiPausedChip, const Color(0xFFB7791F)),
                            if (c.blocked) _Tag(s.blockedChip, theme.colorScheme.error),
                          ]),
                        ]),
                        trailing: Text(_when(c.lastAt), style: theme.textTheme.bodySmall),
                      ),
                    );
                  },
                ),
              );
            },
          ),
        ),
      ]),
    );
  }
}

/// "14:05" today, "12 ноя" before.
String _when(DateTime at) {
  final now = DateTime.now();
  if (at.year == now.year && at.month == now.month && at.day == now.day) return formatTime(at);
  final day = formatDay(at);
  final comma = day.indexOf(', ');
  return comma < 0 ? day : day.substring(comma + 2);
}

class _Tag extends StatelessWidget {
  const _Tag(this.text, this.color);

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(8)),
        child: Text(text, style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w600)),
      );
}
