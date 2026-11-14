import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/load_status.dart';
import '../bloc/work_cubits.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/models.dart';
import 'theme.dart';

/// «Заказы»: open orders first, each with the next steps as buttons with the panel's words («Принять», «Отменить»).
class OrdersScreen extends StatelessWidget {
  const OrdersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return _WorkList<Order, OrdersCubit>(
      empty: S.current.noOrders,
      reload: (c) => c.load(),
      header: (items) => S.current.openCount(items.where((o) => o.isOpen).length),
      item: (context, o, busy) => _OrderCard(order: o, busy: busy),
    );
  }
}

/// «Заявки»: new requests first; «Готово» closes one.
class LeadsScreen extends StatelessWidget {
  const LeadsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return _WorkList<Lead, LeadsCubit>(
      empty: S.current.noLeads,
      reload: (c) => c.load(),
      header: (items) => S.current.newCount(items.where((x) => !x.done).length),
      item: (context, x, busy) => _LeadCard(lead: x, busy: busy),
    );
  }
}

class _WorkList<T, C extends Cubit<WorkState<T>>> extends StatelessWidget {
  const _WorkList({required this.empty, required this.reload, required this.header, required this.item});

  final String empty;
  final Future<void> Function(C cubit) reload;
  final String Function(List<T> items) header;
  final Widget Function(BuildContext context, T item, bool busy) item;

  int _id(T x) => x is Order ? x.id : (x as Lead).id;

  @override
  Widget build(BuildContext context) {
    return BlocConsumer<C, WorkState<T>>(
      listenWhen: (a, b) => b.notice != null || (b.error != null && b.status != LoadStatus.failure),
      listener: (context, state) =>
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(state.notice ?? state.error!))),
      builder: (context, state) {
        final cubit = context.read<C>();
        Widget body;
        if (state.items.isEmpty && state.status == LoadStatus.failure) {
          body = ListView(children: [
            Padding(
              padding: const EdgeInsets.all(32),
              child: Column(children: [
                Text(state.error ?? S.current.loadFailed),
                TextButton(onPressed: () => reload(cubit), child: Text(S.current.retry)),
              ]),
            ),
          ]);
        } else if (state.items.isEmpty) {
          body = ListView(children: [
            Padding(
              padding: const EdgeInsets.all(32),
              child: Center(
                child: state.status == LoadStatus.success
                    ? Text(empty, textAlign: TextAlign.center)
                    : const CircularProgressIndicator(),
              ),
            ),
          ]);
        } else {
          body = ListView(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
                child: Text(header(state.items), style: Theme.of(context).textTheme.bodySmall),
              ),
              for (final x in state.items) item(context, x, state.busyId == _id(x)),
            ],
          );
        }
        return RefreshIndicator(onRefresh: () => reload(cubit), child: body);
      },
    );
  }
}

String _when(DateTime d) => '${formatDay(d)}, ${formatTime(d)}';

String _som(int value) {
  final digits = value.toString();
  final out = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) out.write(' ');
    out.write(digits[i]);
  }
  return '$out ${S.current.som}';
}

class _Card extends StatelessWidget {
  const _Card({required this.children, this.muted = false});

  final List<Widget> children;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Opacity(
      opacity: muted ? 0.6 : 1,
      child: Card(
        elevation: 0,
        color: cardColor(scheme),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
        ),
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag(this.text, this.color);

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(8)),
        child: Text(text, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
      );
}

Color _orderColor(String status, ColorScheme scheme) => switch (status) {
      'new' => const Color(0xFFE5484D),
      'accepted' => const Color(0xFFF76B15),
      'sent' => const Color(0xFF3E63DD),
      'done' => const Color(0xFF2E9E5B),
      _ => scheme.outline,
    };

class _OrderCard extends StatelessWidget {
  const _OrderCard({required this.order, required this.busy});

  final Order order;
  final bool busy;

  Future<void> _move(BuildContext context, OrderStep step) async {
    if (step.status == 'cancelled') {
      final yes = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(S.current.cancelOrderQuestion(order.id)),
          content: Text(S.current.goodsBackToStock),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: Text(S.current.no)),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(S.current.cancelOrder)),
          ],
        ),
      );
      if (yes != true || !context.mounted) return;
    }
    context.read<OrdersCubit>().move(order, step);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final s = S.current;
    final where = order.delivery ? (order.address.isEmpty ? s.delivery : s.deliveryTo(order.address)) : s.pickup;
    return _Card(
      muted: !order.isOpen,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Wrap(
                spacing: 8,
                runSpacing: 4,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text('№${order.id}', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                  _Tag(s.orderStatus(order.status, delivery: order.delivery), _orderColor(order.status, scheme)),
                ],
              ),
            ),
            if (order.total != null)
              Text(_som(order.total!), style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          ],
        ),
        const SizedBox(height: 8),
        for (final l in order.lines) Text('${l.quantity} × ${l.name}'),
        const SizedBox(height: 8),
        Text(where, style: theme.textTheme.bodyMedium),
        if (order.wantedTime.isNotEmpty) Text(s.byTime(order.wantedTime), style: theme.textTheme.bodyMedium),
        if (order.comment.isNotEmpty) Text(order.comment, style: theme.textTheme.bodySmall),
        const SizedBox(height: 8),
        Wrap(spacing: 6, runSpacing: 6, children: [
          _Tag(channelName(order.channel), channelColor(order.channel)),
          if (order.customerName.isNotEmpty) _Tag(order.customerName, scheme.outline),
          if (order.customerPhone.isNotEmpty) _Tag(order.customerPhone, scheme.outline),
          _Tag(_when(order.createdAt), scheme.outline),
        ]),
        if (order.isOpen) ...[
          const SizedBox(height: 12),
          if (busy)
            const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
          else
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final step in order.next)
                step.status == 'cancelled'
                    ? OutlinedButton(onPressed: () => _move(context, step), child: Text(s.orderAction(step.status, delivery: order.delivery)))
                    : FilledButton(onPressed: () => _move(context, step), child: Text(s.orderAction(step.status, delivery: order.delivery))),
            ]),
        ],
      ],
    );
  }
}

class _LeadCard extends StatelessWidget {
  const _LeadCard({required this.lead, required this.busy});

  final Lead lead;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return _Card(
      muted: lead.done,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 4,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            _Tag(lead.kindLabel, lead.kind == 'lead' ? brandColor : const Color(0xFFF76B15)),
            Text(_when(lead.createdAt), style: theme.textTheme.bodySmall),
          ],
        ),
        const SizedBox(height: 8),
        Text(lead.summary.isEmpty ? S.current.noDescription : lead.summary,
            style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600)),
        if (lead.details.isNotEmpty)
          Padding(padding: const EdgeInsets.only(top: 4), child: Text(lead.details, style: theme.textTheme.bodyMedium)),
        const SizedBox(height: 8),
        Wrap(spacing: 6, runSpacing: 6, children: [
          _Tag(channelName(lead.channel), channelColor(lead.channel)),
          if (lead.customerName.isNotEmpty) _Tag(lead.customerName, scheme.outline),
          if (lead.customerPhone.isNotEmpty) _Tag(lead.customerPhone, scheme.outline),
          if (lead.done) _Tag(lead.closedBy.isEmpty ? S.current.done : S.current.closedBy(lead.closedBy), const Color(0xFF2E9E5B)),
        ]),
        if (!lead.done) ...[
          const SizedBox(height: 12),
          busy
              ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
              : FilledButton.tonal(
                  onPressed: () => context.read<LeadsCubit>().markDone(lead),
                  child: Text(S.current.done),
                ),
        ],
      ],
    );
  }
}
