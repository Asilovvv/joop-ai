import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/auth_bloc.dart';
import '../bloc/load_status.dart';
import '../bloc/summary_cubit.dart';
import '../core/format.dart';
import 'booking_tile.dart';
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
      onRefresh: () => context.read<SummaryCubit>().load(),
      child: BlocBuilder<SummaryCubit, SummaryState>(
        builder: (context, state) {
          final summary = state.summary;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
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
                    Text(account == null ? '' : 'Вы вошли: ${account.who}',
                        style: theme.textTheme.bodyMedium?.copyWith(color: Colors.white70)),
                    const SizedBox(height: 18),
                    Text(summary == null ? '…' : bookingsWord(summary.today),
                        key: const Key('today-count'),
                        style: theme.textTheme.headlineMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w900)),
                    Text('сегодня', style: theme.textTheme.bodyLarge?.copyWith(color: Colors.white70)),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(child: _Stat('Завтра', summary?.tomorrow, () => onOpenBookings(1))),
                  const SizedBox(width: 12),
                  Expanded(child: _Stat('За 7 дней', summary?.week, () => onOpenBookings(0))),
                ],
              ),
              const SizedBox(height: 20),
              Text('Ближайший визит', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              if (state.status == LoadStatus.failure)
                _Message(state.error ?? 'Не удалось загрузить', retry: () => context.read<SummaryCubit>().load())
              else if (summary == null)
                const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()))
              else if (summary.next == null)
                const _Message('На ближайшие 7 дней записей нет.')
              else
                BookingTile(booking: summary.next!, showDay: true),
            ],
          );
        },
      ),
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
              Text(value?.toString() ?? '…', style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
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
            if (retry != null) TextButton(onPressed: retry, child: const Text('Повторить')),
          ],
        ),
      );
}
