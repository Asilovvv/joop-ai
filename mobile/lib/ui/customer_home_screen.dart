import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/places_cubit.dart';
import '../data/customer_repository.dart';
import 'place_screen.dart';
import 'theme.dart';

/// For customers: open a business by its code or link and talk to its AI administrator.
class CustomerHomeScreen extends StatelessWidget {
  const CustomerHomeScreen({super.key});

  @override
  Widget build(BuildContext context) => BlocProvider(
        create: (_) => PlacesCubit(context.read<CustomerRepository>())..load(),
        child: const _CustomerHome(),
      );
}

class _CustomerHome extends StatefulWidget {
  const _CustomerHome();

  @override
  State<_CustomerHome> createState() => _CustomerHomeState();
}

class _CustomerHomeState extends State<_CustomerHome> {
  final _code = TextEditingController();

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  void _open(BuildContext context, String code) => context.read<PlacesCubit>().open(code);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Записаться', style: TextStyle(fontWeight: FontWeight.w800))),
      body: BlocConsumer<PlacesCubit, PlacesState>(
        listenWhen: (a, b) => b.opened != null && a.opened != b.opened,
        listener: (context, state) {
          _code.clear();
          Navigator.of(context).push(MaterialPageRoute(builder: (_) => PlaceScreen(place: state.opened!)));
        },
        builder: (context, state) => ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(gradient: brandGradient, borderRadius: BorderRadius.circular(24)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Цены, свободное время и запись',
                      style: theme.textTheme.titleLarge?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 6),
                  Text('Отвечает ИИ-администратор компании, сразу и в любое время.',
                      style: theme.textTheme.bodyMedium?.copyWith(color: Colors.white70)),
                ],
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              key: const Key('place-code'),
              controller: _code,
              decoration: InputDecoration(
                labelText: 'Код компании или ссылка на её чат',
                helperText: 'Код есть на QR-коде и в ссылке: …/c/код',
                errorText: state.error,
                suffixIcon: state.adding
                    ? const Padding(
                        padding: EdgeInsets.all(14),
                        child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                      )
                    : IconButton(
                        key: const Key('place-open'),
                        tooltip: 'Открыть',
                        icon: const Icon(Icons.arrow_forward),
                        onPressed: () => _open(context, _code.text),
                      ),
              ),
              textInputAction: TextInputAction.go,
              onSubmitted: (v) => _open(context, v),
            ),
            const SizedBox(height: 20),
            if (state.places.isNotEmpty) ...[
              Text('Мои компании', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              for (final p in state.places)
                Card(
                  elevation: 0,
                  color: cardColor(theme.colorScheme),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  child: ListTile(
                    leading: CircleAvatar(
                      backgroundColor: brandColor.withValues(alpha: 0.12),
                      child: Text(p.name.isEmpty ? '?' : p.name.characters.first.toUpperCase(),
                          style: const TextStyle(color: brandColor, fontWeight: FontWeight.w700)),
                    ),
                    title: Text(p.name),
                    subtitle: Text(p.slug),
                    onTap: () => _open(context, p.slug),
                    trailing: IconButton(
                      tooltip: 'Убрать из списка',
                      icon: const Icon(Icons.close),
                      onPressed: () => context.read<PlacesCubit>().remove(p.slug),
                    ),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}
