import 'dart:convert';

import 'package:http/http.dart' as http;

import 'config.dart';

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  final int statusCode;
  final String message;

  @override
  String toString() => message;
}

/// Thin JSON-over-HTTP client for the Joop AI server (/api/mobile).
class ApiClient {
  ApiClient({http.Client? httpClient, String? baseUrl})
      : _http = httpClient ?? http.Client(),
        _baseUrl = _clean(baseUrl ?? AppConfig.defaultApiUrl);

  final http.Client _http;
  String _baseUrl;

  /// Bearer token, set after sign-in.
  String? token;

  String get baseUrl => _baseUrl;

  /// Points the client at another server; an empty value restores the default.
  set baseUrl(String value) =>
      _baseUrl = _clean(value.trim().isEmpty ? AppConfig.defaultApiUrl : value);

  static String _clean(String url) => url.trim().replaceAll(RegExp(r'/+$'), '');

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _uri(String path, [Map<String, String>? query]) {
    final uri = Uri.parse('$_baseUrl$path');
    return query == null || query.isEmpty ? uri : uri.replace(queryParameters: query);
  }

  Future<dynamic> get(String path, {Map<String, String>? query}) =>
      _send(() => _http.get(_uri(path, query), headers: _headers));

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) => _send(
      () => _http.post(_uri(path), headers: _headers, body: jsonEncode(body ?? {})));

  Future<dynamic> patch(String path, Map<String, dynamic> body) =>
      _send(() => _http.patch(_uri(path), headers: _headers, body: jsonEncode(body)));

  Future<dynamic> delete(String path) =>
      _send(() => _http.delete(_uri(path), headers: _headers));

  Future<dynamic> _send(Future<http.Response> Function() request) async {
    final http.Response response;
    try {
      // Long enough for a free cloud server to wake up after it was idle.
      response = await request().timeout(const Duration(seconds: 90));
    } catch (_) {
      throw ApiException(0, 'Нет связи с сервером ($_baseUrl)');
    }
    dynamic data;
    final text = utf8.decode(response.bodyBytes);
    if (text.isNotEmpty) {
      try {
        data = jsonDecode(text);
      } on FormatException {
        data = null;
      }
    }
    if (response.statusCode >= 400) {
      throw ApiException(response.statusCode, _detail(data));
    }
    return data;
  }

  static String _detail(dynamic data) {
    if (data is Map && data['error'] is String) return data['error'] as String;
    if (data is Map && data['detail'] != null) {
      final detail = data['detail'];
      if (detail is String) return detail;
      if (detail is List && detail.isNotEmpty && detail.first is Map) {
        return (detail.first as Map)['msg']?.toString() ?? 'Ошибка запроса';
      }
    }
    return 'Ошибка запроса';
  }
}
