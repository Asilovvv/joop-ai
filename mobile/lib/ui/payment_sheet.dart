import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

/// Records what the customer paid after the visit, as the panel's Касса does. Returns the updated booking.
Future<Booking?> showPaymentSheet(BuildContext context, Booking booking) => showModalBottomSheet<Booking>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => RepositoryProvider.value(value: context.read<JoopRepository>(), child: _PaymentSheet(booking: booking)),
    );

class _PaymentSheet extends StatefulWidget {
  const _PaymentSheet({required this.booking});

  final Booking booking;

  @override
  State<_PaymentSheet> createState() => _PaymentSheetState();
}

class _PaymentSheetState extends State<_PaymentSheet> {
  late final _amount = TextEditingController(text: _start == 0 ? '' : '$_start');
  late String _method = widget.booking.paidMethod.isEmpty ? 'cash' : widget.booking.paidMethod;
  bool _saving = false;
  String? _error;

  int get _start => widget.booking.isPaid ? widget.booking.paidSom : widget.booking.suggestedSom;

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  Future<void> _save(int amount) async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final updated = await context.read<JoopRepository>().pay(widget.booking.id, amount, _method);
      if (mounted) Navigator.of(context).pop(updated);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = e.message;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final b = widget.booking;
    final theme = Theme.of(context);
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(s.payment, style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          Text([formatTime(b.start), b.customerName, b.service].where((x) => x.isNotEmpty).join(' · '),
              style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.outline)),
          const SizedBox(height: 16),
          TextField(
            key: const Key('pay-amount'),
            controller: _amount,
            autofocus: _start == 0,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(8)],
            decoration: InputDecoration(labelText: s.amountLabel),
          ),
          const SizedBox(height: 12),
          SegmentedButton<String>(
            segments: [
              ButtonSegment(value: 'cash', label: Text(s.methodCash)),
              ButtonSegment(value: 'card', label: Text(s.methodCard)),
              ButtonSegment(value: 'transfer', label: Text(s.methodTransfer)),
            ],
            selected: {_method},
            showSelectedIcon: false,
            onSelectionChanged: (x) => setState(() => _method = x.single),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
          ],
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('pay-save'),
            onPressed: _saving
                ? null
                : () {
                    final amount = int.tryParse(_amount.text) ?? 0;
                    if (amount <= 0) {
                      setState(() => _error = s.amountNeeded);
                      return;
                    }
                    _save(amount);
                  },
            child: _saving
                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : Text(s.save),
          ),
          if (b.isPaid)
            TextButton(onPressed: _saving ? null : () => _save(0), child: Text(s.removePayment)),
        ],
      ),
    );
  }
}

/// "1 500 сом · карта".
String paidLabel(Booking b) {
  final s = S.current;
  final method = switch (b.paidMethod) {
    'card' => s.methodCard,
    'transfer' => s.methodTransfer,
    _ => s.methodCash,
  };
  return '${formatSom(b.paidSom)} · ${method.toLowerCase()}';
}
