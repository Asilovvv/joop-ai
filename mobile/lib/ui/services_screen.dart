import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/load_status.dart';
import '../bloc/services_cubit.dart';
import '../core/strings.dart';
import 'theme.dart';

/// The price list the AI quotes to customers. Editing stays in the panel.
class ServicesScreen extends StatelessWidget {
  const ServicesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: () => context.read<ServicesCubit>().load(),
      child: BlocBuilder<ServicesCubit, ServicesState>(
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
          return ListView(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
                child: Text(S.current.pricesNote,
                    style: theme.textTheme.bodySmall),
              ),
              for (final s in state.services)
                Card(
                  elevation: 0,
                  color: cardColor(theme.colorScheme),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  child: ListTile(
                    title: Text(s.name),
                    subtitle: s.available
                        ? (s.category.isEmpty ? null : Text(s.category))
                        : Text(S.current.soldOut, style: TextStyle(color: theme.colorScheme.error)),
                    trailing: Text(s.price.isEmpty ? '—' : '${s.price} ${S.current.som}',
                        style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}
