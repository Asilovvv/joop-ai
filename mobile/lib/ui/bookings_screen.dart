import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/bookings_bloc.dart';
import '../bloc/load_status.dart';
import '../bloc/summary_cubit.dart';
import '../core/format.dart';
import 'booking_tile.dart';

/// Bookings of one day from every channel, with the day switcher and cancelling.
class BookingsScreen extends StatelessWidget {
  const BookingsScreen({super.key});

  Future<void> _confirmCancel(BuildContext context, int id, String who) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Отменить запись?'),
        content: Text('Запись «$who» будет отменена, время снова станет свободным. Клиенту сообщите сами.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Нет')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Отменить запись')),
        ],
      ),
    );
    if (yes == true && context.mounted) context.read<BookingsBloc>().add(BookingCancelRequested(id));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return BlocConsumer<BookingsBloc, BookingsState>(
      listenWhen: (a, b) => b.notice != null || (b.error != null && b.status != LoadStatus.failure),
      listener: (context, state) {
        if (state.notice != null) context.read<SummaryCubit>().load(); // the home screen's counts changed too
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(state.notice ?? state.error!)));
      },
      builder: (context, state) {
        final bloc = context.read<BookingsBloc>();
        return Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Row(
                children: [
                  IconButton(
                    tooltip: 'Предыдущий день',
                    icon: const Icon(Icons.chevron_left),
                    onPressed: () => bloc.add(BookingsDayChanged(state.day.subtract(const Duration(days: 1)))),
                  ),
                  Expanded(
                    child: InkWell(
                      borderRadius: BorderRadius.circular(12),
                      onTap: () async {
                        final picked = await showDatePicker(
                          context: context,
                          initialDate: state.day,
                          firstDate: DateTime(2024),
                          lastDate: DateTime(2030),
                        );
                        if (picked != null) bloc.add(BookingsDayChanged(picked));
                      },
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Column(
                          children: [
                            Text(formatDay(state.day),
                                key: const Key('day'),
                                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                            Text(state.status == LoadStatus.success ? bookingsWord(state.activeCount) : ' ',
                                style: theme.textTheme.bodySmall),
                          ],
                        ),
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Следующий день',
                    icon: const Icon(Icons.chevron_right),
                    onPressed: () => bloc.add(BookingsDayChanged(state.day.add(const Duration(days: 1)))),
                  ),
                ],
              ),
            ),
            Expanded(
              child: RefreshIndicator(
                onRefresh: () async => bloc.add(const BookingsRefreshed()),
                child: switch (state.status) {
                  LoadStatus.failure when state.bookings.isEmpty => _Centered(
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                        Text(state.error ?? 'Не удалось загрузить'),
                        TextButton(onPressed: () => bloc.add(const BookingsRefreshed()), child: const Text('Повторить')),
                      ]),
                    ),
                  LoadStatus.initial || LoadStatus.loading when state.bookings.isEmpty =>
                    const _Centered(child: CircularProgressIndicator()),
                  _ when state.bookings.isEmpty => const _Centered(child: Text('В этот день записей нет.')),
                  _ => ListView.separated(
                      padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                      itemCount: state.bookings.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 4),
                      itemBuilder: (context, i) {
                        final b = state.bookings[i];
                        return BookingTile(
                          booking: b,
                          busy: state.cancelling == b.id,
                          onCancel: () => _confirmCancel(context, b.id, b.customerName),
                        );
                      },
                    ),
                },
              ),
            ),
          ],
        );
      },
    );
  }
}

/// Centred content that still lets the list be pulled to refresh.
class _Centered extends StatelessWidget {
  const _Centered({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, constraints) => ListView(
          children: [SizedBox(height: constraints.maxHeight * 0.8, child: Center(child: child))],
        ),
      );
}
