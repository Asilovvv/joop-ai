import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/auth_bloc.dart';
import '../bloc/bookings_bloc.dart';
import '../bloc/services_cubit.dart';
import '../bloc/summary_cubit.dart';
import '../data/joop_repository.dart';
import 'bookings_screen.dart';
import 'services_screen.dart';
import 'today_screen.dart';

/// The signed-in app: «Сегодня», «Записи», «Прайс».
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.today});

  /// Today's date on the device; the server answers in the business's own time zone.
  final DateTime today;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _tab = 0;

  static const _titles = ['Сегодня', 'Записи', 'Прайс'];

  @override
  Widget build(BuildContext context) {
    final repository = context.read<JoopRepository>();
    return MultiBlocProvider(
      providers: [
        BlocProvider(create: (_) => SummaryCubit(repository)..load()),
        BlocProvider(create: (_) => BookingsBloc(repository, today: widget.today)..add(BookingsDayChanged(widget.today))),
        BlocProvider(create: (_) => ServicesCubit(repository)..load()),
      ],
      child: Builder(
        builder: (context) => Scaffold(
          appBar: AppBar(
            title: Text(_titles[_tab], style: const TextStyle(fontWeight: FontWeight.w800)),
            actions: [
              IconButton(
                tooltip: 'Выйти',
                icon: const Icon(Icons.logout),
                onPressed: () => context.read<AuthBloc>().add(const AuthLogoutRequested()),
              ),
            ],
          ),
          body: IndexedStack(
            index: _tab,
            children: [
              TodayScreen(onOpenBookings: (offset) {
                context.read<BookingsBloc>().add(BookingsDayChanged(widget.today.add(Duration(days: offset))));
                setState(() => _tab = 1);
              }),
              const BookingsScreen(),
              const ServicesScreen(),
            ],
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            destinations: const [
              NavigationDestination(icon: Icon(Icons.today_outlined), selectedIcon: Icon(Icons.today), label: 'Сегодня'),
              NavigationDestination(
                  icon: Icon(Icons.event_note_outlined), selectedIcon: Icon(Icons.event_note), label: 'Записи'),
              NavigationDestination(icon: Icon(Icons.sell_outlined), selectedIcon: Icon(Icons.sell), label: 'Прайс'),
            ],
          ),
        ),
      ),
    );
  }
}
