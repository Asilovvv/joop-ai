import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/customers_cubit.dart';
import '../bloc/load_status.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import 'customer_screen.dart';
import 'theme.dart';

/// Every customer the AI met (the panel's Клиенты), found by name, phone or tag; a tap opens the card.
class CustomersScreen extends StatelessWidget {
  const CustomersScreen({super.key});

  @override
  Widget build(BuildContext context) => BlocProvider(
        create: (_) => CustomersCubit(context.read<JoopRepository>())..load(),
        child: const _Customers(),
      );
}

class _Customers extends StatefulWidget {
  const _Customers();

  @override
  State<_Customers> createState() => _CustomersState();
}

class _CustomersState extends State<_Customers> {
  Timer? _debounce;

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _search(String text) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () => context.read<CustomersCubit>().load(query: text));
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final theme = Theme.of(context);
    final cubit = context.read<CustomersCubit>();
    return Scaffold(
      appBar: AppBar(title: Text(s.customersTitle, style: const TextStyle(fontWeight: FontWeight.w800))),
      body: BlocBuilder<CustomersCubit, CustomersState>(
        builder: (context, state) => Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: TextField(
              key: const Key('customers-search'),
              onChanged: _search,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(prefixIcon: const Icon(Icons.search), hintText: s.chatsSearch),
            ),
          ),
          if (state.tags.isNotEmpty)
            SizedBox(
              height: 44,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                children: [
                  for (final t in ['', ...state.tags])
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: ChoiceChip(
                        key: Key('tag-$t'),
                        label: Text(t.isEmpty ? s.allTags : t),
                        selected: state.tag == t,
                        onSelected: (_) => cubit.load(tag: t),
                      ),
                    ),
                ],
              ),
            ),
          Expanded(
            child: state.rows.isEmpty
                ? Center(
                    child: switch (state.status) {
                      LoadStatus.failure => Column(mainAxisSize: MainAxisSize.min, children: [
                          Text(state.error ?? s.loadFailed),
                          TextButton(onPressed: () => cubit.load(), child: Text(s.retry)),
                        ]),
                      LoadStatus.success =>
                        Text(state.query.isEmpty && state.tag.isEmpty ? s.customersEmpty : s.chatsNotFound),
                      _ => const CircularProgressIndicator(),
                    },
                  )
                : RefreshIndicator(
                    onRefresh: () => cubit.load(),
                    child: ListView.builder(
                      padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                      itemCount: state.rows.length + (state.total > state.rows.length ? 1 : 0),
                      itemBuilder: (context, i) {
                        if (i == state.rows.length) {
                          return Padding(
                            padding: const EdgeInsets.all(12),
                            child: Text(s.shownOf(state.rows.length, state.total),
                                textAlign: TextAlign.center, style: theme.textTheme.bodySmall),
                          );
                        }
                        final c = state.rows[i];
                        return Card(
                          elevation: 0,
                          color: cardColor(theme.colorScheme),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                          child: ListTile(
                            key: Key('customer-${c.key}'),
                            onTap: () => Navigator.of(context).push(MaterialPageRoute(
                              builder: (_) =>
                                  CustomerScreen(customerKey: c.key, title: c.name.isEmpty ? s.noName : c.name),
                            )),
                            title: Text(c.name.isEmpty ? s.noName : c.name,
                                style: const TextStyle(fontWeight: FontWeight.w600)),
                            subtitle: Text([
                              if (c.phone.isNotEmpty) formatPhone(c.phone),
                              s.customerLine(c.visits, formatSom(c.spendSom)),
                              if (c.tags.isNotEmpty) c.tags.join(', '),
                            ].join('\n')),
                            trailing: c.lastVisit == null
                                ? null
                                : Text(formatDay(c.lastVisit!), style: theme.textTheme.bodySmall),
                          ),
                        );
                      },
                    ),
                  ),
          ),
        ]),
      ),
    );
  }
}
