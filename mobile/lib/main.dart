import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'bloc/auth_bloc.dart';
import 'core/api_client.dart';
import 'data/joop_repository.dart';
import 'ui/home_shell.dart';
import 'ui/login_screen.dart';
import 'ui/theme.dart';

void main() {
  runApp(JoopApp(repository: JoopRepository(ApiClient())));
}

class JoopApp extends StatelessWidget {
  const JoopApp({super.key, required this.repository, this.today});

  final JoopRepository repository;

  /// Fixed in tests; the device's date otherwise.
  final DateTime? today;

  @override
  Widget build(BuildContext context) {
    return RepositoryProvider.value(
      value: repository,
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
              AuthSignedIn() => HomeShell(key: ValueKey(state.account), today: today ?? DateTime.now()),
              _ => const LoginScreen(),
            },
          ),
        ),
      ),
    );
  }
}
