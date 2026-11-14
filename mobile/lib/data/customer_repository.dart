import 'dart:convert';
import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

import '../core/api_client.dart';
import '../core/strings.dart';
import 'models.dart';

/// The customer side: a business's public card and its web chat (`/c/<slug>/chat`), the same AI as in WhatsApp.
///
/// The device keeps the businesses the customer opened, one random visitor token (the web chat knows the customer
/// by it) and the last messages of each chat.
class CustomerRepository {
  CustomerRepository(this._api);

  final ApiClient _api;

  static const _placesKey = 'joop_places';
  static const _visitorKey = 'joop_visitor';
  static const _historyLimit = 60;

  String get server => _api.baseUrl;

  Future<Place> place(String code) async =>
      Place.fromJson(await _api.get('/api/mobile/places/${Uri.encodeComponent(code)}') as Map<String, dynamic>);

  Future<List<SavedPlace>> savedPlaces() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_placesKey);
    if (raw == null) return const [];
    return [for (final row in jsonDecode(raw) as List) SavedPlace.fromJson(row as Map<String, dynamic>)];
  }

  Future<void> savePlaces(List<SavedPlace> places) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_placesKey, jsonEncode([for (final p in places) p.toJson()]));
  }

  Future<String> visitor() async {
    final prefs = await SharedPreferences.getInstance();
    var token = prefs.getString(_visitorKey);
    if (token == null) {
      final random = Random.secure();
      token = List.generate(24, (_) => random.nextInt(16).toRadixString(16)).join();
      await prefs.setString(_visitorKey, token);
    }
    return token;
  }

  /// Sends a message to the business's AI and returns its answer.
  Future<String> send(String slug, String text) async {
    final data = await _api.post('/c/${Uri.encodeComponent(slug)}/chat', {'text': text, 'visitor': await visitor(), 'lang': S.current.code})
        as Map<String, dynamic>;
    return (data['reply'] as String?) ?? '';
  }

  /// Replies the business's staff wrote from the panel after message `after`.
  Future<List<ChatMessage>> updates(String slug, int after) async {
    final data = await _api.get('/c/${Uri.encodeComponent(slug)}/updates',
        query: {'visitor': await visitor(), 'after': '$after'}) as Map<String, dynamic>;
    return [
      for (final row in (data['messages'] as List? ?? const []))
        ChatMessage(fromCustomer: false, text: (row as Map)['text'] as String, staffId: row['id'] as int),
    ];
  }

  Future<List<ChatMessage>> history(String slug) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('joop_chat_$slug');
    if (raw == null) return const [];
    return [for (final row in jsonDecode(raw) as List) ChatMessage.fromJson(row as Map<String, dynamic>)];
  }

  Future<void> saveHistory(String slug, List<ChatMessage> messages) async {
    final prefs = await SharedPreferences.getInstance();
    final kept = messages.length > _historyLimit ? messages.sublist(messages.length - _historyLimit) : messages;
    await prefs.setString('joop_chat_$slug', jsonEncode([for (final m in kept) m.toJson()]));
  }
}

/// What a customer may type to open a business: its code, or its chat or price-page link.
String? codeFrom(String input) {
  final text = input.trim();
  final link = RegExp(r'/(?:c|m)/([A-Za-z0-9_-]+)').firstMatch(text);
  final code = (link?.group(1) ?? text).toLowerCase();
  return RegExp(r'^[a-z0-9_-]{2,64}$').hasMatch(code) ? code : null;
}
