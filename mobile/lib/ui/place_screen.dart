import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/chat_bloc.dart';
import '../data/customer_repository.dart';
import '../data/models.dart';
import 'theme.dart';

/// One business for a customer: the chat with its AI administrator and its prices.
class PlaceScreen extends StatelessWidget {
  const PlaceScreen({super.key, required this.place, this.poll = const Duration(seconds: 15)});

  final Place place;

  /// How often the chat asks for staff replies; zero turns it off (tests).
  final Duration poll;

  @override
  Widget build(BuildContext context) {
    return BlocProvider(
      create: (_) => ChatBloc(context.read<CustomerRepository>(), place.slug, poll: poll)..add(const ChatOpened()),
      child: DefaultTabController(
        length: 2,
        child: Scaffold(
          appBar: AppBar(
            title: Text(place.name, style: const TextStyle(fontWeight: FontWeight.w800)),
            bottom: const TabBar(tabs: [Tab(text: 'Чат'), Tab(text: 'Цены и контакты')]),
          ),
          body: TabBarView(children: [_Chat(place: place), _About(place: place)]),
        ),
      ),
    );
  }
}

class _Chat extends StatefulWidget {
  const _Chat({required this.place});

  final Place place;

  @override
  State<_Chat> createState() => _ChatState();
}

class _ChatState extends State<_Chat> {
  final _text = TextEditingController();
  final _scroll = ScrollController();

  @override
  void dispose() {
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _send() {
    if (_text.text.trim().isEmpty) return;
    context.read<ChatBloc>().add(ChatMessageSent(_text.text));
    _text.clear();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hello = widget.place.booking
        ? 'Здравствуйте! Спросите цену или свободное время, и я запишу вас.'
        : 'Здравствуйте! Напишите ваш вопрос: цены, наличие, заказ.';
    return Column(
      children: [
        Expanded(
          child: BlocConsumer<ChatBloc, ChatState>(
            listener: (context, state) {
              if (state.error != null) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(state.error!)));
              }
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
              });
            },
            builder: (context, state) => ListView(
              controller: _scroll,
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
              children: [
                _Bubble(text: hello, mine: false),
                for (final m in state.messages) _Bubble(text: m.text, mine: m.fromCustomer, staff: m.staffId != null),
                if (state.waiting)
                  const Padding(
                    padding: EdgeInsets.all(8),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2)),
                    ),
                  ),
              ],
            ),
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 8, 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('chat-input'),
                    controller: _text,
                    minLines: 1,
                    maxLines: 4,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _send(),
                    decoration: const InputDecoration(hintText: 'Сообщение'),
                  ),
                ),
                const SizedBox(width: 6),
                BlocBuilder<ChatBloc, ChatState>(
                  builder: (context, state) => IconButton.filled(
                    key: const Key('chat-send'),
                    tooltip: 'Отправить',
                    onPressed: state.waiting ? null : _send,
                    icon: const Icon(Icons.send),
                  ),
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text('Отвечает ИИ-администратор ${widget.place.name}', style: theme.textTheme.bodySmall),
        ),
      ],
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.text, required this.mine, this.staff = false});

  final String text;
  final bool mine;

  /// Written by a staff member from the panel, not by the AI.
  final bool staff;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.8),
        decoration: BoxDecoration(
          color: mine ? brandColor : cardColor(scheme),
          borderRadius: BorderRadius.circular(18),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (staff)
              Text('Администратор', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: scheme.primary)),
            Text(text, style: TextStyle(color: mine ? Colors.white : scheme.onSurface)),
          ],
        ),
      ),
    );
  }
}

class _About extends StatelessWidget {
  const _About({required this.place});

  final Place place;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = [
      if (place.address.isNotEmpty) (Icons.place_outlined, place.address),
      if (place.phone.isNotEmpty) (Icons.phone_outlined, place.phone),
      if (place.hours.isNotEmpty) (Icons.schedule_outlined, place.hours),
    ];
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
      children: [
        if (place.description.isNotEmpty)
          Padding(padding: const EdgeInsets.fromLTRB(4, 0, 4, 12), child: Text(place.description)),
        for (final (icon, text) in rows) ListTile(leading: Icon(icon), title: Text(text), dense: true),
        const SizedBox(height: 8),
        if (place.services.isEmpty)
          const Padding(padding: EdgeInsets.all(16), child: Text('Цены уточните в чате.'))
        else
          for (final s in place.services)
            Card(
              elevation: 0,
              color: cardColor(theme.colorScheme),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
              child: ListTile(
                title: Text(s.name),
                subtitle: s.category.isEmpty ? null : Text(s.category),
                trailing: Text(s.price.isEmpty ? '—' : (RegExp(r'\d').hasMatch(s.price) && !s.price.contains('сом') ? '${s.price} сом' : s.price),
                    style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
              ),
            ),
      ],
    );
  }
}
