import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/auth_bloc.dart';
import '../bloc/load_status.dart';
import '../bloc/services_cubit.dart';
import '../core/format.dart';
import '../core/strings.dart';
import 'theme.dart';

/// The price list the AI quotes to customers, with the stop list. Prices are edited in the panel.
class ServicesScreen extends StatelessWidget {
  const ServicesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: () => context.read<ServicesCubit>().load(),
      child: BlocConsumer<ServicesCubit, ServicesState>(
        listenWhen: (a, b) => b.notice != null,
        listener: (context, state) =>
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(state.notice!))),
        builder: (context, state) {
          if (state.status == LoadStatus.failure && state.services.isEmpty) {
            return ListView(children: [
              Padding(
                padding: const EdgeInsets.all(32),
                child: Column(children: [
                  Text(state.error ?? S.current.loadFailed),
                  TextButton(onPressed: () => context.read<ServicesCubit>().load(), child: Text(S.current.retry)),
                ]),
              ),
            ]);
          }
          if (state.services.isEmpty) {
            return ListView(children: [
              Padding(
                padding: const EdgeInsets.all(32),
                child: Center(
                  child: state.status == LoadStatus.success
                      ? Text(S.current.pricesEmpty)
                      : const CircularProgressIndicator(),
                ),
              ),
            ]);
          }
          final editable = context.read<AuthBloc>().state is AuthSignedIn &&
              (context.read<AuthBloc>().state as AuthSignedIn).account.role != 'master';
          final altegio = state.services.any((x) => x.fromAltegio);
          return ListView(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
                child: Text(
                    !editable ? S.current.pricesNote : (altegio ? S.current.fromAltegioNote : S.current.stopListNote),
                    style: theme.textTheme.bodySmall),
              ),
              for (final s in state.services)
                Card(
                  elevation: 0,
                  color: cardColor(theme.colorScheme),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  child: ListTile(
                    title: Text(s.name,
                        style: TextStyle(color: s.available ? null : theme.colorScheme.outline)),
                    subtitle: Text(
                      [
                        if (s.price.isNotEmpty) priceWithSom(s.price),
                        if (s.example) S.current.exampleRow,
                        if (!s.available) s.soldOut ? S.current.soldOutStock : (editable ? S.current.stopListed : S.current.soldOut)
                        else if (s.category.isNotEmpty) s.category,
                      ].join(' · '),
                      style: TextStyle(color: s.available ? null : theme.colorScheme.error),
                    ),
                    trailing: !editable
                        ? null
                        : state.switching == s.id
                            ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                            : Switch(
                                key: Key('available-${s.id}'),
                                value: s.available,
                                onChanged: s.switchable
                                    ? (on) => context.read<ServicesCubit>().setAvailable(s, on)
                                    : null,
                              ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}
