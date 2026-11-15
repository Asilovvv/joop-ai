import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/auth_bloc.dart';
import '../bloc/bookings_bloc.dart';
import '../bloc/cash_cubit.dart';
import '../bloc/load_status.dart';
import '../bloc/summary_cubit.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/models.dart';
import 'booking_tile.dart';
import 'customer_screen.dart';
import 'payment_sheet.dart';

/// Bookings of one day from every channel, with the day switcher and cancelling.
class BookingsScreen extends StatelessWidget {
  const BookingsScreen({super.key});

  Future<void> _confirmCancel(BuildContext context, int id, String who) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(S.current.cancelBookingQuestion),
        content: Text(S.current.cancelBookingText(who)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(S.current.no)),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(S.current.cancelBooking)),
        ],
      ),
    );
    if (yes == true && context.mounted) context.read<BookingsBloc>().add(BookingCancelRequested(id));
  }

  Future<void> _pay(BuildContext context, Booking booking) async {
    final updated = await showPaymentSheet(context, booking);
    if (updated == null || !context.mounted) return;
    context.read<BookingsBloc>().add(BookingUpdated(updated));
    context.read<CashCubit>().load();
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar() // a second payment in a row shows at once, not after the first notice
      ..showSnackBar(SnackBar(content: Text(updated.isPaid ? S.current.paymentSaved : S.current.paymentRemoved)));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final auth = context.watch<AuthBloc>().state;
    final payments = auth is AuthSignedIn && auth.account.cash;
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
                    tooltip: S.current.previousDay,
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
                    tooltip: S.current.nextDay,
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
                        Text(state.error ?? S.current.loadFailed),
                        TextButton(onPressed: () => bloc.add(const BookingsRefreshed()), child: Text(S.current.retry)),
                      ]),
                    ),
                  LoadStatus.initial ||
                  LoadStatus.loading when state.bookings.isEmpty =>
                    const _Centered(child: CircularProgressIndicator()),
                  _ when state.bookings.isEmpty => _Centered(child: Text(S.current.noBookingsThisDay)),
                  _ => ListView.separated(
                      padding: const EdgeInsets.fromLTRB(12, 4, 12, 96), // room under the «Записать» button
                      itemCount: state.bookings.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 4),
                      itemBuilder: (context, i) {
                        final b = state.bookings[i];
                        return BookingTile(
                          booking: b,
                          busy: state.cancelling == b.id,
                          onCancel: () => _confirmCancel(context, b.id, b.customerName),
                          onPay: payments ? () => _pay(context, b) : null,
                          onOpen: b.customerKey.isEmpty ? null : () => openCustomer(context, b),
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
