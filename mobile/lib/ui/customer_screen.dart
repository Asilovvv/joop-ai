import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/customer_cubit.dart';
import '../bloc/load_status.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'booking_tile.dart';
import 'theme.dart';

/// Opens the card of a booking's customer.
Future<void> openCustomer(BuildContext context, Booking b) => Navigator.of(context).push(MaterialPageRoute(
      builder: (_) =>
          CustomerScreen(customerKey: b.customerKey, title: b.customerName.isEmpty ? S.current.noName : b.customerName),
    ));

/// The customer card: visits, what they spent, their rating, orders, and the note and tags staff keep.
class CustomerScreen extends StatelessWidget {
  const CustomerScreen({super.key, required this.customerKey, required this.title});

  final String customerKey;
  final String title;

  @override
  Widget build(BuildContext context) => BlocProvider(
        create: (_) => CustomerCubit(context.read<JoopRepository>(), customerKey)..load(),
        child: _Customer(title: title),
      );
}

class _Customer extends StatefulWidget {
  const _Customer({required this.title});

  final String title;

  @override
  State<_Customer> createState() => _CustomerState();
}

class _CustomerState extends State<_Customer> {
  final _note = TextEditingController();
  final _tags = TextEditingController();
  bool _filled = false;

  @override
  void dispose() {
    _note.dispose();
    _tags.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final theme = Theme.of(context);
    return BlocConsumer<CustomerCubit, CustomerState>(
      listenWhen: (a, b) => b.notice != null || (!_filled && b.card != null),
      listener: (context, state) {
        if (!_filled && state.card != null) {
          _filled = true;
          _note.text = state.card!.note;
          _tags.text = state.card!.tags.join(', ');
        }
        if (state.notice != null) {
          ScaffoldMessenger.of(context)
            ..hideCurrentSnackBar()
            ..showSnackBar(SnackBar(content: Text(state.notice!)));
        }
      },
      builder: (context, state) {
        final card = state.card;
        return Scaffold(
          appBar: AppBar(
              title: Text(card?.name.isNotEmpty == true ? card!.name : widget.title,
                  style: const TextStyle(fontWeight: FontWeight.w800))),
          body: card == null
              ? Center(
                  child: state.status == LoadStatus.failure
                      ? Column(mainAxisSize: MainAxisSize.min, children: [
                          Text(state.error ?? s.loadFailed),
                          TextButton(onPressed: () => context.read<CustomerCubit>().load(), child: Text(s.retry)),
                        ])
                      : const CircularProgressIndicator(),
                )
              : RefreshIndicator(
                  onRefresh: () => context.read<CustomerCubit>().load(),
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
                    children: [
                      if (card.phone.isNotEmpty || card.channels.isNotEmpty)
                        Text(
                          [card.phone, ...card.channels.map(channelName)].where((x) => x.isNotEmpty).join(' · '),
                          style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.outline),
                        ),
                      const SizedBox(height: 12),
                      Row(children: [
                        _Figure(label: s.visitsLabel, value: '${card.visits}'),
                        _Figure(label: s.spentLabel, value: formatSom(card.spendSom)),
                        if (card.rating != null) _Figure(label: s.ratingLabel, value: '${card.rating} ★'),
                      ]),
                      if (card.upcoming != null) ...[
                        _Heading(s.upcomingVisit),
                        BookingTile(booking: card.upcoming!, showDay: true),
                      ],
                      _Heading(s.noteLabel),
                      TextField(
                        key: const Key('customer-note'),
                        controller: _note,
                        minLines: 2,
                        maxLines: 6,
                        maxLength: 1000,
                      ),
                      TextField(
                        key: const Key('customer-tags'),
                        controller: _tags,
                        decoration: InputDecoration(labelText: s.tagsLabel, hintText: 'VIP, постоянный'),
                      ),
                      const SizedBox(height: 10),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: FilledButton.tonal(
                          key: const Key('customer-save'),
                          onPressed: state.saving
                              ? null
                              : () => context.read<CustomerCubit>().saveNote(_note.text, _tags.text),
                          child: Text(s.save),
                        ),
                      ),
                      if (card.bookings.isNotEmpty) ...[
                        _Heading(s.historyLabel),
                        for (final b in card.bookings) BookingTile(booking: b, showDay: true),
                      ],
                      if (card.orders.isNotEmpty) ...[
                        _Heading(s.customerOrders),
                        for (final o in card.orders)
                          Card(
                            elevation: 0,
                            color: cardColor(theme.colorScheme),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                            child: ListTile(
                              title: Text('№${o.id} · ${o.label}'),
                              subtitle: Text(o.lines.map((l) => '${l.name} × ${l.quantity}').join(', ')),
                              trailing: o.total == null ? null : Text(formatSom(o.total!)),
                            ),
                          ),
                      ],
                    ],
                  ),
                ),
        );
      },
    );
  }
}

class _Figure extends StatelessWidget {
  const _Figure({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(value, style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
        Text(label, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline)),
      ]),
    );
  }
}

class _Heading extends StatelessWidget {
  const _Heading(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 20, bottom: 8),
        child: Text(text, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
      );
}
