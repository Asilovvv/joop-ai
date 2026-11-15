import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/load_status.dart';
import '../bloc/new_booking_cubit.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

/// Booking a customer who phoned or walked in, or, with [moving], moving a booking to another free time.
/// Closes with the new or moved [Booking].
class NewBookingScreen extends StatelessWidget {
  const NewBookingScreen({super.key, required this.day, required this.today, this.moving});

  final DateTime day;
  final DateTime today;
  final Booking? moving;

  @override
  Widget build(BuildContext context) => BlocProvider(
        create: (_) => NewBookingCubit(context.read<JoopRepository>(), day)..showDay(day),
        child: _NewBooking(today: today, moving: moving),
      );
}

class _NewBooking extends StatefulWidget {
  const _NewBooking({required this.today, this.moving});

  final DateTime today;
  final Booking? moving;

  @override
  State<_NewBooking> createState() => _NewBookingState();
}

class _NewBookingState extends State<_NewBooking> {
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _service = TextEditingController();

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _service.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final theme = Theme.of(context);
    final cubit = context.read<NewBookingCubit>();
    final today = DateTime(widget.today.year, widget.today.month, widget.today.day);
    return BlocConsumer<NewBookingCubit, NewBookingState>(
      listenWhen: (a, b) => b.booked != null && a.booked == null,
      listener: (context, state) {
        if (widget.moving != null) {
          final b = state.booked!;
          final when = '${formatDay(b.start)}, ${formatTime(b.start)}';
          ScaffoldMessenger.of(context)
            ..hideCurrentSnackBar()
            ..showSnackBar(SnackBar(content: Text(cubit.told ? s.movedTold(when) : s.movedCallYourself(when))));
        }
        Navigator.of(context).pop(state.booked);
      },
      builder: (context, state) {
        final canGoBack = state.day.isAfter(today);
        return Scaffold(
          appBar: AppBar(
              title: Text(widget.moving == null ? s.newBooking : s.moveBooking,
                  style: const TextStyle(fontWeight: FontWeight.w800))),
          body: ListView(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
            children: [
              Row(children: [
                IconButton(
                  tooltip: s.previousDay,
                  onPressed: canGoBack ? () => cubit.showDay(state.day.subtract(const Duration(days: 1))) : null,
                  icon: const Icon(Icons.chevron_left),
                ),
                Expanded(
                  child: Text(formatDay(state.day),
                      key: const Key('new-booking-day'),
                      textAlign: TextAlign.center,
                      style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                ),
                IconButton(
                  tooltip: s.nextDay,
                  onPressed: () => cubit.showDay(state.day.add(const Duration(days: 1))),
                  icon: const Icon(Icons.chevron_right),
                ),
              ]),
              const SizedBox(height: 8),
              Text(s.chooseTime, style: theme.textTheme.labelLarge),
              const SizedBox(height: 8),
              switch (state.status) {
                LoadStatus.initial ||
                LoadStatus.loading =>
                  const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
                LoadStatus.failure when state.slots.isEmpty => Column(children: [
                    Text(state.error ?? s.loadFailed),
                    TextButton(onPressed: () => cubit.showDay(state.day), child: Text(s.retry)),
                  ]),
                _ when state.slots.isEmpty =>
                  Padding(padding: const EdgeInsets.symmetric(vertical: 16), child: Text(s.noFreeTimes)),
                _ => _Times(slots: state.slots, selected: state.selected, onChoose: cubit.choose),
              },
              if (widget.moving != null) ...[
                const SizedBox(height: 16),
                Text(
                    s.movingFrom(widget.moving!.customerName,
                        '${formatDay(widget.moving!.start)}, ${formatTime(widget.moving!.start)}'),
                    style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.outline)),
              ] else ...[
                const SizedBox(height: 20),
                TextField(
                  key: const Key('new-booking-name'),
                  controller: _name,
                  textCapitalization: TextCapitalization.words,
                  decoration: InputDecoration(labelText: s.customerName),
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('new-booking-phone'),
                  controller: _phone,
                  keyboardType: TextInputType.phone,
                  decoration: InputDecoration(labelText: s.customerPhoneOptional, hintText: '0555 123 456'),
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('new-booking-service'),
                  controller: _service,
                  decoration: InputDecoration(labelText: s.serviceOptional),
                ),
              ],
              if (state.error != null && state.status != LoadStatus.failure) ...[
                const SizedBox(height: 12),
                Text(state.error!,
                    key: const Key('new-booking-error'), style: TextStyle(color: theme.colorScheme.error)),
              ],
              const SizedBox(height: 20),
              FilledButton(
                key: const Key('new-booking-save'),
                onPressed: state.selected == null || state.saving
                    ? null
                    : () => widget.moving != null
                        ? cubit.move(widget.moving!)
                        : cubit.book(name: _name.text, phone: _phone.text, service: _service.text),
                child: state.saving
                    ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(state.selected == null
                        ? (widget.moving == null ? s.bookAction : s.moveAction)
                        : '${widget.moving == null ? s.bookAction : s.moveAction} · ${formatTime(state.selected!.start)}'),
              ),
            ],
          ),
        );
      },
    );
  }
}

/// The day's free times, grouped by the person (doctor, master, table).
class _Times extends StatelessWidget {
  const _Times({required this.slots, required this.selected, required this.onChoose});

  final List<FreeSlot> slots;
  final FreeSlot? selected;
  final ValueChanged<FreeSlot> onChoose;

  @override
  Widget build(BuildContext context) {
    final byStaff = <String, List<FreeSlot>>{};
    for (final x in slots) {
      byStaff.putIfAbsent(x.staff, () => []).add(x);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final entry in byStaff.entries) ...[
          Padding(
            padding: const EdgeInsets.only(top: 8, bottom: 6),
            child: Text(entry.key, style: const TextStyle(fontWeight: FontWeight.w700)),
          ),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final x in entry.value)
              ChoiceChip(
                key: Key('slot-${x.id}'),
                label: Text(
                    x.seats > 1 ? '${formatTime(x.start)} · ${S.current.seatsLeft(x.seatsLeft)}' : formatTime(x.start)),
                selected: selected?.id == x.id,
                onSelected: (_) => onChoose(x),
              ),
          ]),
        ],
      ],
    );
  }
}
