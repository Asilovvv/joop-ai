import 'dart:convert';

import 'package:http/http.dart' as http;

import 'strings.dart';

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

  static String _clean(String url) {
    var clean = url.trim().replaceAll(RegExp(r'/+$'), '');
    if (clean.isNotEmpty && !clean.contains('://')) {
      // «192.168.1.5:8000» or «joop.kg» typed without a scheme: a local server speaks http, the rest https
      final host = clean.split(RegExp('[:/]')).first;
      clean = '${isLocal(host) ? 'http' : 'https'}://$clean';
    }
    return clean;
  }

  /// Plain http only to this device or the same Wi-Fi (a laptop running the server at a demo): over the open
  /// internet the password and the customers' data would travel readable. Android allows http for the app
  /// (usesCleartextTraffic) only because this check stands in front of every request.
  static bool allowed(String url) {
    final uri = Uri.tryParse(url);
    if (uri == null) return false;
    return uri.scheme == 'https' || (uri.scheme == 'http' && isLocal(uri.host));
  }

  /// localhost, the Android emulator's host, and the private ranges 10/8, 172.16/12, 192.168/16, *.local.
  static bool isLocal(String host) {
    final h = host.toLowerCase().replaceAll(RegExp(r'^\[|\]$'), '');
    if (h == 'localhost' || h == '::1' || h.endsWith('.local')) return true;
    // Plain decimal octets only: the system reads «010.8.8.8» as octal (8.8.8.8) and «0x0a» as hex, so a number
    // read differently here would let the password go in plain http to a public address.
    final parts = h.split('.');
    if (parts.length != 4 || !parts.every(RegExp(r'^(0|[1-9][0-9]{0,2})$').hasMatch)) return false;
    final n = parts.map(int.parse).toList();
    if (n.any((x) => x > 255)) return false;
    final a = n[0], b = n[1];
    return a == 127 || a == 10 || (a == 192 && b == 168) || (a == 172 && b >= 16 && b <= 31);
  }

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
    if (!allowed(_baseUrl)) throw ApiException(0, S.current.httpsOnly(_baseUrl));
    final http.Response response;
    try {
      // Long enough for a free cloud server to wake up after it was idle.
      response = await request().timeout(const Duration(seconds: 90));
    } catch (_) {
      throw ApiException(0, S.current.noConnection(_baseUrl));
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
        return (detail.first as Map)['msg']?.toString() ?? S.current.requestFailed;
      }
    }
    return S.current.requestFailed;
  }
}
