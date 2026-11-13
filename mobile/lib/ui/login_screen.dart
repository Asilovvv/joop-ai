import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/auth_bloc.dart';
import '../data/joop_repository.dart';
import 'theme.dart';

/// Sign-in with the panel's credentials.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _company = TextEditingController();
  final _user = TextEditingController();
  final _password = TextEditingController();
  late final TextEditingController _server;
  bool _staff = false;
  bool _showServer = false;

  @override
  void initState() {
    super.initState();
    _server = TextEditingController(text: context.read<JoopRepository>().server);
  }

  @override
  void dispose() {
    for (final c in [_company, _user, _password, _server]) {
      c.dispose();
    }
    super.dispose();
  }

  void _submit() {
    if (_company.text.trim().isEmpty || _password.text.isEmpty) return;
    context.read<AuthBloc>().add(AuthLoginRequested(
          _company.text,
          _password.text,
          user: _staff ? _user.text : '',
          server: _showServer ? _server.text : null,
        ));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: brandGradient),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(22),
                      child: Image.asset('assets/icon/icon.png', width: 84, height: 84),
                    ),
                    const SizedBox(height: 16),
                    Text('Joop AI',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.headlineMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w900)),
                    const SizedBox(height: 6),
                    Text('Записи из всех каналов в одном приложении',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.bodyMedium?.copyWith(color: Colors.white70)),
                    const SizedBox(height: 28),
                    Card(
                      color: cardColor(theme.colorScheme),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: BlocBuilder<AuthBloc, AuthState>(
                          builder: (context, state) {
                            final busy = state is AuthLoading;
                            final error = state is AuthSignedOut ? state.error : null;
                            return Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                TextField(
                                  key: const Key('company'),
                                  controller: _company,
                                  decoration: const InputDecoration(labelText: 'Логин компании или телефон'),
                                  textInputAction: TextInputAction.next,
                                ),
                                const SizedBox(height: 12),
                                if (_staff) ...[
                                  TextField(
                                    key: const Key('user'),
                                    controller: _user,
                                    decoration: const InputDecoration(labelText: 'Ваш логин сотрудника'),
                                    textInputAction: TextInputAction.next,
                                  ),
                                  const SizedBox(height: 12),
                                ],
                                TextField(
                                  key: const Key('password'),
                                  controller: _password,
                                  obscureText: true,
                                  decoration: const InputDecoration(labelText: 'Пароль'),
                                  onSubmitted: (_) => _submit(),
                                ),
                                SwitchListTile(
                                  contentPadding: EdgeInsets.zero,
                                  title: const Text('Я сотрудник'),
                                  value: _staff,
                                  onChanged: (v) => setState(() => _staff = v),
                                ),
                                if (_showServer) ...[
                                  TextField(
                                    controller: _server,
                                    decoration: const InputDecoration(labelText: 'Адрес сервера Joop'),
                                    keyboardType: TextInputType.url,
                                  ),
                                  const SizedBox(height: 12),
                                ],
                                if (error != null) ...[
                                  Text(error, style: TextStyle(color: theme.colorScheme.error)),
                                  const SizedBox(height: 12),
                                ],
                                FilledButton(
                                  key: const Key('login'),
                                  onPressed: busy ? null : _submit,
                                  style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                                  child: busy
                                      ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5))
                                      : const Text('Войти'),
                                ),
                                TextButton(
                                  onPressed: () => setState(() => _showServer = !_showServer),
                                  child: Text(_showServer ? 'Скрыть адрес сервера' : 'Другой сервер'),
                                ),
                              ],
                            );
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Text('Логин и пароль те же, что в панели Joop.',
                        textAlign: TextAlign.center, style: theme.textTheme.bodySmall?.copyWith(color: Colors.white70)),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
