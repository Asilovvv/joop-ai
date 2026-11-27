import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

/// The panel's «Доступ сотрудников» for the owner: each master or administrator her own login (a master sees only her
/// bookings, customers and cash), who signed in when, a login turned off or given a new password. The sheets only
/// collect what was typed and close; the screen sends it, so the server's refusal is shown on the screen in front.
class AccountsScreen extends StatefulWidget {
  const AccountsScreen({super.key});

  @override
  State<AccountsScreen> createState() => _AccountsScreenState();
}

class _AccountsScreenState extends State<AccountsScreen> {
  LoginsInfo? _info;
  String? _error;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _run(() => context.read<JoopRepository>().logins());
  }

  Future<void> _run(Future<LoginsInfo> Function() call, {String? Function()? done}) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final info = await call();
      if (!mounted) return;
      setState(() => _info = info);
      final said = done?.call();
      if (said != null) _say(said);
    } on ApiException catch (e) {
      if (!mounted) return;
      if (_info == null) {
        setState(() => _error = e.message);
      } else {
        _say(e.message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _say(String text) => ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text), duration: const Duration(seconds: 6)));

  Future<void> _add() async {
    final info = _info!;
    final typed = await showModalBottomSheet<_NewLogin>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _NewLoginSheet(info: info),
    );
    if (typed == null || !mounted) return;
    final repository = context.read<JoopRepository>();
    _run(
      () => repository.addLogin(name: typed.name, login: typed.login, password: typed.password, staffId: typed.staffId),
      done: () => S.current.accountCreated(typed.login.toLowerCase(), info.company),
    );
  }

  Future<void> _open(StaffLogin user) async {
    final info = _info!;
    final asked = await showModalBottomSheet<_Change>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _LoginSheet(user: user, minPassword: info.minPassword),
    );
    if (asked == null || !mounted) return;
    final repository = context.read<JoopRepository>();
    if (asked.password != null) {
      _run(() => repository.setLoginPassword(user.id, asked.password!), done: () => S.current.accountPasswordChanged);
    } else if (asked.active != null) {
      _run(() => repository.setLoginActive(user.id, asked.active!));
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final info = _info;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(s.accountsTitle, style: const TextStyle(fontWeight: FontWeight.w800))),
      body: info == null
          ? Center(
              child: _error == null
                  ? const CircularProgressIndicator()
                  : Padding(padding: const EdgeInsets.all(24), child: Text(_error!, textAlign: TextAlign.center)))
          : ListView(
              key: const Key('accounts-list'),
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
              children: [
                if (_busy) const LinearProgressIndicator(),
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
                  child: Text(s.accountsIntro, style: theme.textTheme.bodySmall),
                ),
                FilledButton.icon(
                  key: const Key('account-add'),
                  onPressed: _busy ? null : _add,
                  icon: const Icon(Icons.person_add_alt_1_outlined),
                  label: Text(s.accountAdd),
                ),
                if (info.users.isEmpty) Padding(padding: const EdgeInsets.all(24), child: Text(s.accountsEmpty)),
                for (final u in info.users)
                  Card(
                    margin: const EdgeInsets.only(top: 8),
                    child: ListTile(
                      key: Key('account-${u.id}'),
                      onTap: _busy ? null : () => _open(u),
                      title: Text('${u.name} · ${u.login}', style: const TextStyle(fontWeight: FontWeight.w700)),
                      subtitle: Text([
                        u.staffId != null ? s.accountMasterOf(u.staffName) : s.accountAdmin,
                        if (!u.active) s.accountOff,
                        u.lastLogin == null
                            ? s.accountNeverIn
                            : s.accountLastLogin('${formatDay(u.lastLogin!)}, ${formatTime(u.lastLogin!)}'),
                      ].join(' · ')),
                      trailing: Icon(u.active ? Icons.chevron_right : Icons.block, color: u.active ? null : theme.colorScheme.error),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 16, 4, 0),
                  child: Text(s.accountsHowToSignIn(info.company), key: const Key('accounts-how'), style: theme.textTheme.bodySmall),
                ),
              ],
            ),
    );
  }
}

/// What the add sheet hands back.
class _NewLogin {
  const _NewLogin(this.name, this.login, this.password, this.staffId);

  final String name;
  final String login;
  final String password;
  final int? staffId;
}

class _NewLoginSheet extends StatefulWidget {
  const _NewLoginSheet({required this.info});

  final LoginsInfo info;

  @override
  State<_NewLoginSheet> createState() => _NewLoginSheetState();
}

class _NewLoginSheetState extends State<_NewLoginSheet> {
  final _name = TextEditingController();
  final _login = TextEditingController();
  final _password = TextEditingController();
  int? _staffId;

  @override
  void dispose() {
    for (final c in [_name, _login, _password]) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final info = widget.info;
    InputDecoration field(String label) => InputDecoration(labelText: label, border: const OutlineInputBorder());
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(s.accountAdd, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          TextField(
              key: const Key('account-name'),
              controller: _name,
              textCapitalization: TextCapitalization.words,
              decoration: field(s.accountName)),
          const SizedBox(height: 12),
          TextField(
              key: const Key('account-login'),
              controller: _login,
              autocorrect: false,
              enableSuggestions: false,
              decoration: field(s.accountLogin)),
          const SizedBox(height: 12),
          TextField(
              key: const Key('account-password'),
              controller: _password,
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              decoration: field(s.accountPassword(info.minPassword))),
          if (info.masters && info.people.isNotEmpty) ...[
            const SizedBox(height: 12),
            DropdownButtonFormField<int?>(
              key: const Key('account-master'),
              initialValue: _staffId,
              isExpanded: true,
              decoration: field(s.accountMaster),
              items: [
                DropdownMenuItem<int?>(value: null, child: Text(s.accountNotMaster)),
                for (final p in info.people) DropdownMenuItem<int?>(value: p.id, child: Text(p.name)),
              ],
              onChanged: (v) => setState(() => _staffId = v),
            ),
          ],
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('account-save'),
            onPressed: () => Navigator.of(context)
                .pop(_NewLogin(_name.text.trim(), _login.text.trim(), _password.text, _staffId)),
            child: Text(s.accountAdd),
          ),
        ]),
      ),
    );
  }
}

/// What the login sheet hands back: a new password, or the login on or off.
class _Change {
  const _Change({this.password, this.active});

  final String? password;
  final bool? active;
}

class _LoginSheet extends StatefulWidget {
  const _LoginSheet({required this.user, required this.minPassword});

  final StaffLogin user;
  final int minPassword;

  @override
  State<_LoginSheet> createState() => _LoginSheetState();
}

class _LoginSheetState extends State<_LoginSheet> {
  final _password = TextEditingController();

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final user = widget.user;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('${user.name} · ${user.login}', style: Theme.of(context).textTheme.titleLarge),
          SwitchListTile(
            key: const Key('account-active'),
            contentPadding: EdgeInsets.zero,
            title: Text(s.accountActive),
            value: user.active,
            onChanged: (on) => Navigator.of(context).pop(_Change(active: on)),
          ),
          const SizedBox(height: 8),
          TextField(
            key: const Key('account-new-password'),
            controller: _password,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            decoration: InputDecoration(
                labelText: s.accountNewPassword,
                helperText: s.accountPassword(widget.minPassword),
                border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          FilledButton(
            key: const Key('account-password-save'),
            onPressed: () => Navigator.of(context).pop(_Change(password: _password.text)),
            child: Text(s.accountChangePassword),
          ),
        ]),
      ),
    );
  }
}
