import 'dart:async';

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
  const HomeShell({super.key, required this.account, required this.today, this.poll = const Duration(seconds: 30)});

  final Account account;

  /// How often the open app checks for new bookings, orders and requests; zero turns it off (tests).
  final Duration poll;

  /// Today's date on the device; the server answers in the business's own time zone.
  final DateTime today;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

enum _Tab { today, bookings, orders, leads, prices }

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  int _index = 0;
  Timer? _timer;

  late final JoopRepository _repository = context.read<JoopRepository>();
  late final SummaryCubit _summary = SummaryCubit(_repository);
  late final BookingsBloc _bookings = BookingsBloc(_repository, today: widget.today);
  late final OrdersCubit _orders = OrdersCubit(_repository);
  late final LeadsCubit _leads = LeadsCubit(_repository);
  late final ServicesCubit _services = ServicesCubit(_repository)..load();

  Account get _account => widget.account;

  @override
  void initState() {
    super.initState();
    if (_account.bookings) {
      _summary.load();
      _bookings.add(BookingsDayChanged(widget.today));
    }
    if (_account.orders) _orders.load();
    if (_account.leads) _leads.load();
    WidgetsBinding.instance.addObserver(this);
    _startTimer();
  }

  void _startTimer() {
    _timer?.cancel();
    if (widget.poll > Duration.zero) _timer = Timer.periodic(widget.poll, (_) => _check());
  }

  /// Asks the server what changed: new orders and requests show a notice and the tabs' counters.
  void _check() {
    if (_account.bookings) {
      _summary.refresh();
      _bookings.add(const BookingsPolled());
    }
    if (_account.orders) _orders.refresh();
    if (_account.leads) _leads.refresh();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _check(); // back in the app: show what came in meanwhile
      _startTimer();
    } else if (state == AppLifecycleState.paused) {
      _timer?.cancel(); // no checks in the background
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    for (final c in [_summary, _orders, _leads, _services]) {
      c.close();
    }
    _bookings.close();
    super.dispose();
  }

  List<_Tab> get _tabs => [
        if (_account.bookings) ...[_Tab.today, _Tab.bookings],
        if (_account.orders) _Tab.orders,
        if (_account.leads) _Tab.leads,
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

  Widget _screen(_Tab tab) => switch (tab) {
        _Tab.today => TodayScreen(onOpenBookings: (offset) {
            _bookings.add(BookingsDayChanged(widget.today.add(Duration(days: offset))));
            setState(() => _index = _tabs.indexOf(_Tab.bookings));
          }),
        _Tab.bookings => const BookingsScreen(),
        _Tab.orders => const OrdersScreen(),
        _Tab.leads => const LeadsScreen(),
        _Tab.prices => const ServicesScreen(),
      };

  /// The tab's icon with a counter: orders nobody accepted, requests nobody closed.
  Widget _icon(_Tab tab, bool selected) {
    final icon = Icon(selected ? _icons[tab]!.$2 : _icons[tab]!.$1);
    Widget counted(int n) => n == 0 ? icon : Badge(label: Text('$n'), child: icon);
    return switch (tab) {
      _Tab.orders => BlocBuilder<OrdersCubit, WorkState<Order>>(builder: (context, _) => counted(_orders.newCount)),
      _Tab.leads => BlocBuilder<LeadsCubit, WorkState<Lead>>(builder: (context, _) => counted(_leads.newCount)),
      _ => icon,
    };
  }

  @override
  Widget build(BuildContext context) {
    final tabs = _tabs;
    return MultiBlocProvider(
      providers: [
        BlocProvider.value(value: _summary),
        BlocProvider.value(value: _bookings),
        BlocProvider.value(value: _orders),
        BlocProvider.value(value: _leads),
        BlocProvider.value(value: _services),
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
          body: IndexedStack(index: _index, children: [for (final t in tabs) _screen(t)]),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            destinations: [
              for (final t in tabs)
                NavigationDestination(icon: _icon(t, false), selectedIcon: _icon(t, true), label: _titles[t]!),
            ],
          ),
        ),
      ),
    );
  }
}
