import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'bloc/auth_bloc.dart';
import 'core/api_client.dart';
import 'data/customer_repository.dart';
import 'data/joop_repository.dart';
import 'ui/home_shell.dart';
import 'ui/login_screen.dart';
import 'ui/theme.dart';

void main() {
  final api = ApiClient();
  runApp(JoopApp(repository: JoopRepository(api), customers: CustomerRepository(api)));
}

class JoopApp extends StatelessWidget {
  const JoopApp({super.key, required this.repository, required this.customers, this.today});

  final JoopRepository repository;
  final CustomerRepository customers;

  /// Fixed in tests; the device's date otherwise.
  final DateTime? today;

  @override
  Widget build(BuildContext context) {
    return MultiRepositoryProvider(
      providers: [RepositoryProvider.value(value: repository), RepositoryProvider.value(value: customers)],
      child: BlocProvider(
        create: (_) => AuthBloc(repository)..add(const AuthStarted()),
        child: MaterialApp(
          title: 'Joop AI',
          debugShowCheckedModeBanner: false,
          theme: buildTheme(Brightness.light),
          darkTheme: buildTheme(Brightness.dark),
          home: BlocBuilder<AuthBloc, AuthState>(
            buildWhen: (a, b) => a.runtimeType != b.runtimeType || b is AuthSignedIn,
            builder: (context, state) => switch (state) {
              AuthInitial() => const Scaffold(body: Center(child: CircularProgressIndicator())),
              AuthSignedIn() => HomeShell(key: ValueKey(state.account), account: state.account, today: today ?? DateTime.now()),
              _ => const LoginScreen(),
            },
          ),
        ),
      ),
    );
  }
}
