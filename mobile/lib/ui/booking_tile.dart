import 'package:flutter/material.dart';

import '../core/format.dart';
import '../core/strings.dart';
import '../data/models.dart';
import 'theme.dart';

/// One booking: time, customer, service and specialist, the channel it came from.
class BookingTile extends StatelessWidget {
  const BookingTile({super.key, required this.booking, this.onCancel, this.busy = false, this.showDay = false});

  final Booking booking;
  final VoidCallback? onCancel;
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
                      _Chip(channelName(booking.channel), channelColor(booking.channel)),
                      if (!active) _Chip(S.current.cancelled, scheme.outline),
                      if (active && booking.confirmed) _Chip(S.current.confirmed, const Color(0xFF2E9E5B)),
                      if (booking.customerPhone.isNotEmpty) _Chip(booking.customerPhone, scheme.outline),
                    ],
                  ),
                ],
              ),
            ),
            if (active && onCancel != null)
              busy
                  ? const Padding(
                      padding: EdgeInsets.all(12),
                      child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                    )
                  : IconButton(
                      tooltip: S.current.cancelBooking,
                      icon: const Icon(Icons.event_busy_outlined),
                      onPressed: onCancel,
                    ),
          ],
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
