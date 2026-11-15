import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/load_status.dart';
import '../bloc/schedule_cubit.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'theme.dart';

/// The day's times by person: close an ill doctor's day, or one time, and open them again (the panel's «Окна»).
class ScheduleScreen extends StatelessWidget {
  const ScheduleScreen({super.key, required this.day, required this.today});

  final DateTime day;
  final DateTime today;

  @override
  Widget build(BuildContext context) => BlocProvider(
        create: (_) => ScheduleCubit(context.read<JoopRepository>(), day)..showDay(day),
        child: _Schedule(today: DateTime(today.year, today.month, today.day)),
      );
}

class _Schedule extends StatelessWidget {
  const _Schedule({required this.today});

  final DateTime today;

  Future<void> _showLeft(BuildContext context, List<Booking> left) => showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(S.current.bookingsLeftTitle),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final b in left)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text('${formatTime(b.start)} — ${b.customerName.isEmpty ? S.current.noName : b.customerName}'
                    '${b.customerPhone.isEmpty ? '' : ', ${b.customerPhone}'}'),
              ),
            const SizedBox(height: 8),
            Text(S.current.bookingsLeftText),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(S.current.gotIt))],
        ),
      );

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final theme = Theme.of(context);
    final cubit = context.read<ScheduleCubit>();
    return BlocConsumer<ScheduleCubit, ScheduleState>(
      listenWhen: (a, b) => b.notice != null && b.notice != a.notice || b.left.isNotEmpty && b.left != a.left,
      listener: (context, state) {
        if (state.left.isNotEmpty) {
          _showLeft(context, state.left);
        } else if (state.notice != null) {
          ScaffoldMessenger.of(context)
            ..hideCurrentSnackBar()
            ..showSnackBar(SnackBar(content: Text(state.notice!)));
        }
      },
      builder: (context, state) => Scaffold(
        appBar: AppBar(title: Text(s.schedule, style: const TextStyle(fontWeight: FontWeight.w800))),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
          children: [
            Row(children: [
              IconButton(
                tooltip: s.previousDay,
                onPressed:
                    state.day.isAfter(today) ? () => cubit.showDay(state.day.subtract(const Duration(days: 1))) : null,
                icon: const Icon(Icons.chevron_left),
              ),
              Expanded(
                child: Text(formatDay(state.day),
                    key: const Key('schedule-day'),
                    textAlign: TextAlign.center,
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              ),
              IconButton(
                tooltip: s.nextDay,
                onPressed: () => cubit.showDay(state.day.add(const Duration(days: 1))),
                icon: const Icon(Icons.chevron_right),
              ),
            ]),
            Text(s.scheduleNote, style: theme.textTheme.bodySmall),
            const SizedBox(height: 8),
            if (state.people.isEmpty)
              Padding(
                padding: const EdgeInsets.all(24),
                child: Center(
                  child: switch (state.status) {
                    LoadStatus.initial || LoadStatus.loading => const CircularProgressIndicator(),
                    LoadStatus.failure => TextButton(onPressed: () => cubit.showDay(state.day), child: Text(s.retry)),
                    _ => Text(s.noTimes),
                  },
                ),
              ),
            for (final p in state.people) _Person(person: p, working: state.working),
          ],
        ),
      ),
    );
  }
}

class _Person extends StatelessWidget {
  const _Person({required this.person, required this.working});

  final SchedulePerson person;
  final String? working;

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final theme = Theme.of(context);
    final cubit = context.read<ScheduleCubit>();
    final closed = person.slots.where((x) => x.state == 'closed').length;
    final busy = working != null;
    return Card(
      key: Key('person-${person.id}'),
      elevation: 0,
      margin: const EdgeInsets.only(top: 10),
      color: cardColor(theme.colorScheme),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(person.name, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          if (person.slots.isEmpty)
            Text(s.noTimes, style: theme.textTheme.bodySmall)
          else if (person.fromAltegio)
            Text(s.scheduleFromAltegio, style: theme.textTheme.bodySmall)
          else
            Wrap(spacing: 8, runSpacing: 4, children: [
              if (closed < person.slots.length)
                OutlinedButton(
                  key: Key('close-day-${person.id}'),
                  onPressed: busy ? null : () => cubit.setDay(person, false),
                  child: working == 'day-${person.id}'
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                      : Text(s.closeDay),
                ),
              if (closed > 0)
                OutlinedButton(
                  key: Key('open-day-${person.id}'),
                  onPressed: busy ? null : () => cubit.setDay(person, true),
                  child: Text(s.openDay),
                ),
            ]),
          if (person.slots.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(spacing: 6, runSpacing: 6, children: [
              for (final x in person.slots) _Time(slot: x, enabled: !busy && !person.fromAltegio),
            ]),
          ],
        ]),
      ),
    );
  }
}

class _Time extends StatelessWidget {
  const _Time({required this.slot, required this.enabled});

  final ScheduleSlot slot;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final scheme = Theme.of(context).colorScheme;
    final closed = slot.state == 'closed';
    final label = [
      formatTime(slot.start),
      if (slot.isGroup) '${slot.taken}/${slot.seats}',
      if (slot.customer.isNotEmpty) slot.customer,
      if (closed) s.slotClosed,
      if (slot.state == 'busy') s.slotBusy,
    ].join(' · ');
    // free -> close; closed or busy -> open; a booked one-seat time is left to «Записи»
    final open = closed || slot.state == 'busy';
    final tappable = enabled && (open || slot.state == 'free');
    return ActionChip(
      key: Key('slot-${slot.id}'),
      label: Text(label,
          style: TextStyle(
            color: closed ? scheme.error : (slot.state == 'free' ? null : scheme.outline),
            decoration: closed ? TextDecoration.lineThrough : null,
          )),
      backgroundColor: slot.state == 'booked' ? brandColor.withValues(alpha: 0.12) : null,
      onPressed: tappable ? () => context.read<ScheduleCubit>().setSlot(slot, open) : null,
    );
  }
}
