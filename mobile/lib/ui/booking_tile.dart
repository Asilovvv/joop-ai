import 'package:flutter/material.dart';

import '../core/format.dart';
import '../core/strings.dart';
import '../data/models.dart';
import 'payment_sheet.dart';
import 'theme.dart';

/// One booking: time, customer, service and specialist, the channel it came from.
class BookingTile extends StatelessWidget {
  const BookingTile(
      {super.key,
      required this.booking,
      this.onCancel,
      this.onPay,
      this.onOpen,
      this.onMove,
      this.onDeposit,
      this.busy = false,
      this.showDay = false});

  final Booking booking;
  final VoidCallback? onCancel;

  /// Records the payment after the visit; null where payments are not kept.
  final VoidCallback? onPay;

  /// Opens the customer's card; null when the booking has no customer to show.
  final VoidCallback? onOpen;

  /// Moves the booking to another free time; null where it cannot be moved here.
  final VoidCallback? onMove;

  /// Marks the prepayment received; null where it is not waited for or not marked here.
  final VoidCallback? onDeposit;
  final bool busy;
  final bool showDay;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final active = booking.isActive;
    final muted = active ? null : scheme.outline;
    final details = [booking.service, booking.staff].where((s) => s.isNotEmpty).join(' · ');
    return Card(
      elevation: 0,
      color: cardColor(scheme),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onOpen,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 8, 14),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 62,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(formatTime(booking.start),
                        style: theme.textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: muted,
                            decoration: active ? null : TextDecoration.lineThrough)),
                    if (showDay) Text(formatDay(booking.start), style: theme.textTheme.bodySmall),
                  ],
                ),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(booking.customerName.isEmpty ? S.current.noName : booking.customerName,
                        style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600, color: muted)),
                    if (details.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text(details, style: theme.textTheme.bodyMedium?.copyWith(color: muted)),
                      ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        _Chip(bookingOrigin(booking), channelColor(booking.channel)),
                        if (!active) _Chip(S.current.cancelled, scheme.outline),
                        if (active && booking.confirmed) _Chip(S.current.confirmed, const Color(0xFF2E9E5B)),
                        if (active && booking.isPaid) _Chip(paidLabel(booking), const Color(0xFF2E9E5B)),
                        if (active && booking.depositStatus.isNotEmpty && depositLabel(booking).isNotEmpty)
                          _Chip(depositLabel(booking),
                              booking.depositStatus == 'paid' ? const Color(0xFF2E9E5B) : const Color(0xFFB7791F)),
                        if (booking.customerPhone.isNotEmpty) _Chip(formatPhone(booking.customerPhone), scheme.outline),
                      ],
                    ),
                  ],
                ),
              ),
              if (active && (onCancel != null || onPay != null || onMove != null || onDeposit != null))
                busy
                    ? const Padding(
                        padding: EdgeInsets.all(12),
                        child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                      )
                    : Column(mainAxisSize: MainAxisSize.min, children: [
                        if (onCancel != null || onMove != null || onDeposit != null)
                          PopupMenuButton<VoidCallback>(
                            key: Key('booking-menu-${booking.id}'),
                            tooltip: S.current.more,
                            onSelected: (action) => action(),
                            itemBuilder: (_) => [
                              if (onDeposit != null)
                                PopupMenuItem(value: onDeposit, child: Text(S.current.depositReceived)),
                              if (onMove != null) PopupMenuItem(value: onMove, child: Text(S.current.moveAction)),
                              if (onCancel != null)
                                PopupMenuItem(value: onCancel, child: Text(S.current.cancelBooking)),
                            ],
                          ),
                        if (onPay != null)
                          IconButton(
                            tooltip: S.current.payment,
                            icon: Icon(booking.isPaid ? Icons.payments : Icons.payments_outlined),
                            onPressed: onPay,
                          ),
                      ]),
            ],
          ),
        ),
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip(this.text, this.color);

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(8)),
        child: Text(text, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
      );
}

/// The prepayment line under a booking, as the panel shows it; empty when there is nothing to say.
String depositLabel(Booking b) {
  final s = S.current;
  final amount = formatSom(b.depositDue);
  return switch (b.depositStatus) {
    'awaiting' => s.depositAwaiting(
        amount,
        b.depositDeadline == null
            ? ''
            : (DateUtils.isSameDay(b.depositDeadline, DateTime.now())
                ? formatTime(b.depositDeadline!)
                : '${formatDay(b.depositDeadline!)}, ${formatTime(b.depositDeadline!)}')),
    'check' => s.depositCheck(amount),
    'paid' => s.depositPaid(amount),
    'overdue' => s.depositOverdue,
    _ => '',
  };
}
