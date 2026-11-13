import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/auth_bloc.dart';
import '../bloc/bookings_bloc.dart';
import '../bloc/services_cubit.dart';
import '../bloc/summary_cubit.dart';
import '../bloc/work_cubits.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'bookings_screen.dart';
import 'services_screen.dart';
import 'today_screen.dart';
import 'work_screens.dart';

/// The signed-in app. Its tabs follow the business's niche, as the panel's menu does: a clinic has «Сегодня» and
/// «Записи», a cafe adds «Заказы», a shop has «Заказы» without bookings; everyone but a master has «Заявки».
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.account, required this.today});

  final Account account;

  /// Today's date on the device; the server answers in the business's own time zone.
  final DateTime today;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

enum _Tab { today, bookings, orders, leads, prices }

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  List<_Tab> get _tabs => [
        if (widget.account.bookings) ...[_Tab.today, _Tab.bookings],
        if (widget.account.orders) _Tab.orders,
        if (widget.account.leads) _Tab.leads,
        _Tab.prices,
      ];

  static const _titles = {
    _Tab.today: 'Сегодня',
    _Tab.bookings: 'Записи',
    _Tab.orders: 'Заказы',
    _Tab.leads: 'Заявки',
    _Tab.prices: 'Прайс',
  };

  static const _icons = {
    _Tab.today: (Icons.today_outlined, Icons.today),
    _Tab.bookings: (Icons.event_note_outlined, Icons.event_note),
    _Tab.orders: (Icons.shopping_bag_outlined, Icons.shopping_bag),
    _Tab.leads: (Icons.inbox_outlined, Icons.inbox),
    _Tab.prices: (Icons.sell_outlined, Icons.sell),
  };

  Widget _screen(BuildContext context, _Tab tab) => switch (tab) {
        _Tab.today => TodayScreen(onOpenBookings: (offset) {
            context.read<BookingsBloc>().add(BookingsDayChanged(widget.today.add(Duration(days: offset))));
            setState(() => _index = _tabs.indexOf(_Tab.bookings));
          }),
        _Tab.bookings => const BookingsScreen(),
        _Tab.orders => const OrdersScreen(),
        _Tab.leads => const LeadsScreen(),
        _Tab.prices => const ServicesScreen(),
      };

  @override
  Widget build(BuildContext context) {
    final repository = context.read<JoopRepository>();
    final tabs = _tabs;
    final account = widget.account;
    return MultiBlocProvider(
      providers: [
        BlocProvider(create: (_) => SummaryCubit(repository)..load(), lazy: !account.bookings),
        BlocProvider(
          create: (_) => BookingsBloc(repository, today: widget.today)..add(BookingsDayChanged(widget.today)),
          lazy: !account.bookings,
        ),
        BlocProvider(create: (_) => OrdersCubit(repository)..load(), lazy: !account.orders),
        BlocProvider(create: (_) => LeadsCubit(repository)..load(), lazy: !account.leads),
        BlocProvider(create: (_) => ServicesCubit(repository)..load()),
      ],
      child: Builder(
        builder: (context) => Scaffold(
          appBar: AppBar(
            title: Text(_titles[tabs[_index]]!, style: const TextStyle(fontWeight: FontWeight.w800)),
            actions: [
              IconButton(
                tooltip: 'Выйти',
                icon: const Icon(Icons.logout),
                onPressed: () => context.read<AuthBloc>().add(const AuthLogoutRequested()),
              ),
            ],
          ),
          body: IndexedStack(index: _index, children: [for (final t in tabs) _screen(context, t)]),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            destinations: [
              for (final t in tabs)
                NavigationDestination(icon: Icon(_icons[t]!.$1), selectedIcon: Icon(_icons[t]!.$2), label: _titles[t]!),
            ],
          ),
        ),
      ),
    );
  }
}
