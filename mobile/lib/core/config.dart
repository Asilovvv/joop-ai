import 'package:flutter/foundation.dart';

/// Where the server lives.
///
/// A release build gets the address at build time:
///   flutter build apk --dart-define=API_URL=https://api.example.com
/// The user can also change it on the sign-in screen; that choice is saved.
class AppConfig {
  static const String _fromBuild = String.fromEnvironment('API_URL');

  /// Address used until the user sets another one in the app.
  static String get defaultApiUrl {
    if (_fromBuild.isNotEmpty) return _fromBuild;
    // The Android emulator reaches the host machine via 10.0.2.2.
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://localhost:8000';
  }
}
