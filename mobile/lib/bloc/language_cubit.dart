import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/strings.dart';

/// The app's language, Russian or Kyrgyz, kept on the device. Changing it rebuilds every screen.
class LanguageCubit extends Cubit<S> {
  LanguageCubit() : super(S.current);

  static const _key = 'joop_language';

  Future<void> restore() async {
    final prefs = await SharedPreferences.getInstance();
    _apply(S.byCode(prefs.getString(_key)));
  }

  Future<void> choose(S language) async {
    _apply(language);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, language.code);
  }

  void _apply(S language) {
    S.current = language;
    emit(language);
  }
}
