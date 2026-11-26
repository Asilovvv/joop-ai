import 'package:flutter/services.dart';

/// The phone's browser, for the few addresses the app hands over (the billing page). A tiny channel to the Android
/// activity (MainActivity.kt) instead of a package: one call, nothing else to keep up to date.
class Browser {
  const Browser();

  static const _channel = MethodChannel('kg.joop/browser');

  /// True when the browser opened the address; false when it could not (no browser, another platform, a test).
  Future<bool> open(String url) async {
    try {
      return await _channel.invokeMethod<bool>('open', url) ?? false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }
}
