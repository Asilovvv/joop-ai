import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/ai_results_cubit.dart';
import '../bloc/auth_bloc.dart';
import '../bloc/cash_cubit.dart';
import '../bloc/load_status.dart';
import '../bloc/summary_cubit.dart';
import '../core/browser.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/models.dart';
import 'booking_tile.dart';
import 'customer_screen.dart';
import 'deposit.dart';
import 'theme.dart';

/// Home: how many bookings today, tomorrow and this week, and who comes next.
class TodayScreen extends StatelessWidget {
  const TodayScreen({super.key, required this.onOpenBookings});

  /// Opens the bookings tab on this day offset from today (0 = today, 1 = tomorrow).
  final void Function(int offset) onOpenBookings;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final auth = context.watch<AuthBloc>().state;
    final account = auth is AuthSignedIn ? auth.account : null;
    return RefreshIndicator(
      onRefresh: () async {
        if (account != null && account.cash) context.read<CashCubit>().load();
        if (account != null && account.role != 'master') context.read<AiResultsCubit>().load();
        await context.read<SummaryCubit>().load();
      },
      child: BlocBuilder<SummaryCubit, SummaryState>(
        builder: (context, state) {
          final summary = state.summary;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 96), // room under the «Записать» button
            children: [
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(gradient: brandGradient, borderRadius: BorderRadius.circular(24)),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(account?.businessName ?? '',
                        style: theme.textTheme.titleLarge?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 4),
                    Text(account == null ? '' : S.current.signedInAs(account.isOwner ? S.current.owner : account.who),
                        style: theme.textTheme.bodyMedium?.copyWith(color: Colors.white70)),
                    const SizedBox(height: 18),
                    Text(summary == null ? '…' : bookingsWord(summary.today),
                        key: const Key('today-count'),
                        style:
                            theme.textTheme.headlineMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w900)),
                    Text(S.current.today, style: theme.textTheme.bodyLarge?.copyWith(color: Colors.white70)),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(child: _Stat(S.current.tomorrow, summary?.tomorrow, () => onOpenBookings(1))),
                  const SizedBox(width: 12),
                  Expanded(child: _Stat(S.current.next7days, summary?.week, () => onOpenBookings(0))),
                ],
              ),
              if (account != null && account.cash) _CashCard(onOpen: () => onOpenBookings(0)),
              if (summary != null && summary.deposits.isNotEmpty) ...[
                const SizedBox(height: 20),
                Text(S.current.depositsToCheck,
                    key: const Key('deposits-to-check'),
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                for (final b in summary.deposits)
                  BookingTile(
                    booking: b,
                    showDay: true,
                    onDeposit: () => markDepositPaid(context, b),
                    onOpen: b.customerKey.isEmpty ? null : () => openCustomer(context, b),
                  ),
              ],
              const SizedBox(height: 20),
              Text(S.current.nextVisit, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              if (state.status == LoadStatus.failure)
                _Message(state.error ?? S.current.loadFailed, retry: () => context.read<SummaryCubit>().load())
              else if (summary == null)
                const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()))
              else if (summary.next == null)
                _Message(S.current.noBookings7days)
              else
                BookingTile(
                  booking: summary.next!,
                  showDay: true,
                  onOpen: summary.next!.customerKey.isEmpty ? null : () => openCustomer(context, summary.next!),
                ),
              if (account != null && account.role != 'master') const _AiCard(),
            ],
          );
        },
      ),
    );
  }
}

/// Today's takings, the month so far, and visits that passed without a payment (they open today's bookings).
class _CashCard extends StatelessWidget {
  const _CashCard({required this.onOpen});

  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = S.current;
    return BlocBuilder<CashCubit, CashState>(
      builder: (context, state) {
        final day = state.day;
        return Padding(
          padding: const EdgeInsets.only(top: 12),
          child: Card(
            elevation: 0,
            color: cardColor(theme.colorScheme),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
            child: InkWell(
              borderRadius: BorderRadius.circular(18),
              onTap: onOpen,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(s.cashToday, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.outline)),
                  const SizedBox(height: 2),
                  Text(day == null ? '…' : formatSom(day.total),
                      key: const Key('cash-today'),
                      style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
                  if (day != null) ...[
                    Text(s.monthTakings(formatSom(day.monthTotal)), style: theme.textTheme.bodySmall),
                    if (day.unpaid.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text(s.unpaidVisits(day.unpaid.length),
                            style: TextStyle(color: theme.colorScheme.error, fontWeight: FontWeight.w600)),
                      ),
                  ],
                ]),
              ),
            ),
          ),
        );
      },
    );
  }
}

/// What the AI did in the last two weeks: the figures the panel's Сводка shows, those the niche has.
class _AiCard extends StatelessWidget {
  const _AiCard();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = S.current;
    return BlocBuilder<AiResultsCubit, AiResults?>(
      builder: (context, results) {
        if (results == null) return const SizedBox.shrink();
        final shown = results.figures.entries.where((e) => s.aiFigure(e.key, e.value).isNotEmpty).toList();
        return Padding(
          padding: const EdgeInsets.only(top: 12),
          child: Card(
            key: const Key('ai-results'),
            elevation: 0,
            color: cardColor(theme.colorScheme),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(s.aiResultsTitle(results.days),
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(height: 10),
                LayoutBuilder(
                  builder: (context, box) => Wrap(
                    runSpacing: 12,
                    children: [
                      for (final e in shown)
                        SizedBox(
                          width: (box.maxWidth - 1) / 2,
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text('${e.value}',
                                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
                            Text(s.aiFigure(e.key, e.value),
                                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline)),
                          ]),
                        ),
                    ],
                  ),
                ),
              ]),
            ),
          ),
        );
      },
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value, this.onTap);

  final String label;
  final int? value;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      elevation: 0,
      color: cardColor(theme.colorScheme),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(value?.toString() ?? '…',
                  style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
              Text(label, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.outline)),
            ],
          ),
        ),
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message(this.text, {this.retry});

  final String text;
  final VoidCallback? retry;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Column(
          children: [
            Text(text, textAlign: TextAlign.center),
            if (retry != null) TextButton(onPressed: retry, child: Text(S.current.retry)),
          ],
        ),
      );
}

/// The panel's line about the end of the trial or paid month: yellow while the AI is about to stop, red once it has.
/// The owner gets the way to pay (the billing page in the browser); staff are asked to tell the owner.
class PeriodBanner extends StatelessWidget {
  const PeriodBanner({super.key, required this.line, this.browser = const Browser()});

  final PeriodLine line;
  final Browser browser;

  Future<void> _pay(BuildContext context) async {
    final url = line.payUrl!;
    final messenger = ScaffoldMessenger.of(context);
    if (await browser.open(url)) return;
    await Clipboard.setData(ClipboardData(text: url)); // no browser to hand it to: the owner pastes it themselves
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(S.current.payLinkCopied)));
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final background = line.stopped ? scheme.errorContainer : const Color(0xFFFFF1C2);
    final foreground = line.stopped ? scheme.onErrorContainer : const Color(0xFF5C4400);
    return Container(
      key: Key('period-${line.level}'),
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
      decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(16)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(line.stopped ? Icons.error_outline : Icons.schedule, color: foreground),
          const SizedBox(width: 10),
          Expanded(child: Text(line.text, style: TextStyle(color: foreground, fontWeight: FontWeight.w600))),
        ]),
        if (line.payUrl != null)
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton(key: const Key('period-pay'), onPressed: () => _pay(context), child: Text(S.current.goToPay)),
          )
        else if (line.askOwner)
          Padding(
            padding: const EdgeInsets.only(top: 6, left: 34),
            child: Text(S.current.tellOwner, key: const Key('period-ask-owner'), style: TextStyle(color: foreground)),
          ),
      ]),
    );
  }
}
