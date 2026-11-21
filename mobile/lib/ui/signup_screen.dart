import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/auth_bloc.dart';
import '../core/api_client.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import 'theme.dart';

/// A new business signs itself up, as on the site's /signup: name, what it does, phone, password. The server makes
/// the niche's sample price list and a trial; the next step (a Telegram bot, the real prices) is in the panel.
class SignupScreen extends StatefulWidget {
  const SignupScreen({super.key, this.server});

  /// Another server address typed on the sign-in screen; null keeps the app's own.
  final String? server;

  @override
  State<SignupScreen> createState() => _SignupScreenState();
}

class _SignupScreenState extends State<SignupScreen> {
  final _name = TextEditingController();
  final _person = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  List<(String, String)> _niches = const [];
  int _trialDays = 0;
  String? _niche;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final (niches, days) = await context.read<JoopRepository>().niches(server: widget.server);
      if (!mounted) return;
      setState(() {
        _niches = niches;
        _trialDays = days;
        _niche = niches.isEmpty ? null : niches.first.$1;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  void dispose() {
    for (final c in [_name, _person, _phone, _password]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (_niche == null || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final (account, setup) = await context.read<JoopRepository>().signup(
          name: _name.text.trim(), niche: _niche!, phone: _phone.text.trim(), password: _password.text,
          contactName: _person.text.trim(), server: widget.server);
      if (!mounted) return;
      setState(() => _busy = false);
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (dialog) => AlertDialog(
          title: Text(S.current.signUpDone),
          content: SelectableText(S.current.signUpNext(account.slug, setup), key: const Key('signup-next')),
          actions: [
            TextButton(
              onPressed: () => Clipboard.setData(ClipboardData(text: setup)),
              child: const Icon(Icons.copy, size: 20),
            ),
            FilledButton(onPressed: () => Navigator.of(dialog).pop(), child: Text(S.current.continueToApp)),
          ],
        ),
      );
      if (!mounted) return;
      context.read<AuthBloc>().add(AuthSignedUp(account));
      Navigator.of(context).pop();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(S.current.signUpTitle)),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Card(
                color: cardColor(theme.colorScheme),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextField(
                        key: const Key('signup-name'),
                        controller: _name,
                        decoration: InputDecoration(labelText: S.current.businessName),
                        textInputAction: TextInputAction.next,
                      ),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        key: ValueKey('signup-niche-${_niches.length}'), // built again once the list arrives
                        initialValue: _niche,
                        isExpanded: true,
                        decoration: InputDecoration(labelText: S.current.niche),
                        items: [for (final (key, label) in _niches) DropdownMenuItem(value: key, child: Text(label))],
                        onChanged: (v) => setState(() => _niche = v),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        key: const Key('signup-person'),
                        controller: _person,
                        decoration: InputDecoration(labelText: S.current.yourName),
                        textInputAction: TextInputAction.next,
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        key: const Key('signup-phone'),
                        controller: _phone,
                        keyboardType: TextInputType.phone,
                        decoration: InputDecoration(labelText: S.current.businessPhone, hintText: '0555 123 456'),
                        textInputAction: TextInputAction.next,
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        key: const Key('signup-password'),
                        controller: _password,
                        obscureText: true,
                        decoration: InputDecoration(labelText: S.current.newPassword),
                        onSubmitted: (_) => _submit(),
                      ),
                      const SizedBox(height: 12),
                      Text(S.current.trialNote(_trialDays), style: theme.textTheme.bodySmall),
                      if (_error != null) ...[
                        const SizedBox(height: 12),
                        Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
                      ],
                      const SizedBox(height: 16),
                      FilledButton(
                        key: const Key('signup-submit'),
                        onPressed: _busy || _niche == null ? null : _submit,
                        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                        child: _busy
                            ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5))
                            : Text(S.current.createCompany),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
