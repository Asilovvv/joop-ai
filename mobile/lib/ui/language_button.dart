import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/language_cubit.dart';
import '../core/strings.dart';

/// «RU» / «KY» in the app bar: switches every screen between Russian and Kyrgyz.
class LanguageButton extends StatelessWidget {
  const LanguageButton({super.key, this.color});

  final Color? color;

  @override
  Widget build(BuildContext context) {
    final current = context.watch<LanguageCubit>().state;
    return PopupMenuButton<S>(
      key: const Key('language'),
      tooltip: current.languageName,
      initialValue: current,
      onSelected: (s) => context.read<LanguageCubit>().choose(s),
      itemBuilder: (context) => [
        for (final s in S.languages) PopupMenuItem(value: s, child: Text(s.languageName)),
      ],
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.translate, size: 20, color: color),
          const SizedBox(width: 4),
          Text(current.code.toUpperCase(), style: TextStyle(fontWeight: FontWeight.w700, color: color)),
        ]),
      ),
    );
  }
}
