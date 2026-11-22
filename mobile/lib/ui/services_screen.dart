import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/auth_bloc.dart';
import '../bloc/load_status.dart';
import '../bloc/services_cubit.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/models.dart';
import 'theme.dart';

/// The price list the AI quotes to customers, with the stop list. The owner and administrators edit it here (the
/// sign-up example out, their own prices in); a master only reads it; a salon on Altegio edits it there.
class ServicesScreen extends StatelessWidget {
  const ServicesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: () => context.read<ServicesCubit>().load(),
      child: BlocConsumer<ServicesCubit, ServicesState>(
        listenWhen: (a, b) => b.notice != null,
        listener: (context, state) =>
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(state.notice!))),
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
          final editable = context.read<AuthBloc>().state is AuthSignedIn &&
              (context.read<AuthBloc>().state as AuthSignedIn).account.role != 'master';
          final altegio = state.services.any((x) => x.fromAltegio);
          final editing = editable && !altegio;
          if (state.services.isEmpty && !(editing && state.status == LoadStatus.success)) {
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
          final example = state.services.where((x) => x.example).length;
          return ListView(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
            children: [
              if (state.saving) const LinearProgressIndicator(),
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
                child: Row(children: [
                  Expanded(
                    child: Text(
                        !editable ? S.current.pricesNote : (altegio ? S.current.fromAltegioNote : S.current.stopListEditNote),
                        style: theme.textTheme.bodySmall),
                  ),
                  if (editing)
                    FilledButton.tonalIcon(
                      key: const Key('service-add'),
                      onPressed: state.saving ? null : () => _edit(context, null),
                      icon: const Icon(Icons.add),
                      label: Text(S.current.addService),
                    ),
                ]),
              ),
              if (editing && example > 0)
                Card(
                  key: const Key('example-banner'),
                  elevation: 0,
                  color: theme.colorScheme.tertiaryContainer,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(S.current.exampleBanner),
                      Align(
                        alignment: Alignment.centerRight,
                        child: TextButton(
                          key: const Key('example-delete'),
                          onPressed: state.saving ? null : () => _deleteExample(context),
                          child: Text(S.current.deleteExample),
                        ),
                      ),
                    ]),
                  ),
                ),
              if (state.services.isEmpty)
                Padding(padding: const EdgeInsets.all(24), child: Center(child: Text(S.current.pricesEmpty))),
              for (final s in state.services)
                Card(
                  elevation: 0,
                  color: cardColor(theme.colorScheme),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  child: ListTile(
                    key: Key('service-${s.id}'),
                    onTap: editing && !state.saving ? () => _edit(context, s) : null,
                    title: Text(s.name,
                        style: TextStyle(color: s.available ? null : theme.colorScheme.outline)),
                    subtitle: Text(
                      [
                        if (s.price.isNotEmpty) priceWithSom(s.price),
                        if (s.example) S.current.exampleRow,
                        if (!s.available) s.soldOut ? S.current.soldOutStock : (editable ? S.current.stopListed : S.current.soldOut)
                        else if (s.category.isNotEmpty) s.category,
                      ].join(' · '),
                      style: TextStyle(color: s.available ? null : theme.colorScheme.error),
                    ),
                    trailing: !editable
                        ? null
                        : state.switching == s.id
                            ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                            : Switch(
                                key: Key('available-${s.id}'),
                                value: s.available,
                                onChanged: s.switchable
                                    ? (on) => context.read<ServicesCubit>().setAvailable(s, on)
                                    : null,
                              ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _deleteExample(BuildContext context) async {
    final cubit = context.read<ServicesCubit>();
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: Text(S.current.deleteExampleConfirm),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: Text(S.current.cancel)),
          FilledButton(
              key: const Key('example-delete-yes'),
              onPressed: () => Navigator.of(context).pop(true),
              child: Text(S.current.deleteExample)),
        ],
      ),
    );
    if (yes == true) await cubit.deleteExample(S.current.exampleDeleted);
  }

  /// The row's name, price, Kyrgyz name and note; a new row when `item` is null.
  Future<void> _edit(BuildContext context, Service? item) => showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        builder: (_) => BlocProvider.value(value: context.read<ServicesCubit>(), child: _ServiceSheet(item: item)),
      );
}

class _ServiceSheet extends StatefulWidget {
  const _ServiceSheet({required this.item});

  final Service? item;

  @override
  State<_ServiceSheet> createState() => _ServiceSheetState();
}

class _ServiceSheetState extends State<_ServiceSheet> {
  late final _name = TextEditingController(text: widget.item?.name ?? '');
  late final _price = TextEditingController(text: widget.item?.price ?? '');
  late final _nameKy = TextEditingController(text: widget.item?.nameKy ?? '');
  late final _note = TextEditingController(text: widget.item?.note ?? '');
  bool _empty = false;

  @override
  void dispose() {
    for (final c in [_name, _price, _nameKy, _note]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _empty = true);
      return;
    }
    final draft = ServiceDraft(name: _name.text.trim(), price: _price.text.trim(), nameKy: _nameKy.text.trim(), note: _note.text.trim());
    final navigator = Navigator.of(context);
    if (await context.read<ServicesCubit>().save(widget.item, draft)) navigator.pop();
  }

  Future<void> _delete() async {
    final navigator = Navigator.of(context);
    if (await context.read<ServicesCubit>().delete(widget.item!)) navigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final saving = context.watch<ServicesCubit>().state.saving;
    InputDecoration field(String label, {String? helper, String? error}) =>
        InputDecoration(labelText: label, helperText: helper, errorText: error, helperMaxLines: 2, border: const OutlineInputBorder());
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(widget.item == null ? s.newService : s.editService, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          TextField(key: const Key('service-name'), controller: _name, textCapitalization: TextCapitalization.sentences,
              decoration: field(s.serviceName, error: _empty ? s.serviceNameEmpty : null)),
          const SizedBox(height: 12),
          TextField(key: const Key('service-price'), controller: _price, decoration: field(s.servicePrice, helper: s.servicePriceHint)),
          const SizedBox(height: 12),
          TextField(key: const Key('service-name-ky'), controller: _nameKy, decoration: field(s.serviceNameKy)),
          const SizedBox(height: 12),
          TextField(key: const Key('service-note'), controller: _note, maxLines: 2, decoration: field(s.serviceNote)),
          const SizedBox(height: 16),
          FilledButton(key: const Key('service-save'), onPressed: saving ? null : _save, child: Text(s.save)),
          if (widget.item != null)
            TextButton(
              key: const Key('service-delete'),
              onPressed: saving ? null : _delete,
              style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
              child: Text(s.deleteService),
            ),
        ]),
      ),
    );
  }
}
