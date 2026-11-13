import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:joop_mobile/core/api_client.dart';
import 'package:joop_mobile/data/customer_repository.dart';
import 'package:joop_mobile/data/joop_repository.dart';

/// A tiny stand-in for the Joop server's /api/mobile, enough for the app's tests.
class FakeJoop {
  final bookings = <Map<String, dynamic>>[
    _booking(1, '2026-11-13T10:00:00', 'Айгуль', 'whatsapp'),
    _booking(2, '2026-11-13T15:30:00', 'Бакыт', 'telegram'),
    _booking(3, '2026-11-14T09:00:00', 'Нурлан', 'instagram'),
  ];
  final calls = <String>[];

  /// Messages the web chat received, and staff replies waiting for the app to ask.
  final chat = <Map<String, dynamic>>[];
  final staffReplies = <Map<String, dynamic>>[];

  static Map<String, dynamic> _booking(int id, String start, String name, String channel) => {
        'id': id,
        'start_local': start,
        'service': 'Чистка зубов',
        'staff': 'Др. Асанова',
        'customer': {'name': name, 'phone': '+996700000001'},
        'channel': channel,
        'status': 'booked',
        'confirmed': id == 1,
      };

  static const token = 'good-token';

  late final client = MockClient((request) async {
    final path = request.url.path;
    calls.add('${request.method} $path');
    http.Response json(Object body, [int status = 200]) =>
        http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json; charset=utf-8'});
    const account = {
      'business': {'id': 1, 'slug': 'aktish', 'name': 'Ак-Тиш Дент', 'niche': 'dental'},
      'who': 'Владелец',
      'role': 'owner',
    };
    if (path == '/api/mobile/places/aktish') {
      return json({
        'slug': 'aktish', 'name': 'Ак-Тиш Дент', 'niche': 'dental', 'description': 'Семейная стоматология',
        'address': 'ул. Киевская, 95', 'phone': '+996700000000', 'hours': 'Пн–Сб 9:00–19:00', 'booking': true,
        'services': [
          {'id': 1, 'name': 'Консультация', 'price': '500', 'category': ''},
        ],
      });
    }
    if (path.startsWith('/api/mobile/places/')) return json({'error': 'Такой компании нет или её чат выключен.'}, 404);
    if (path == '/c/aktish/chat') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      chat.add(body);
      return json({'reply': 'Консультация стоит 500 сом. Свободно завтра в 10:00, записать?', 'visitor': body['visitor']});
    }
    if (path == '/c/aktish/updates') {
      final after = int.parse(request.url.queryParameters['after'] ?? '0');
      return json({'messages': staffReplies.where((m) => (m['id'] as int) > after).toList()});
    }
    if (path == '/api/mobile/login') {
      final body = jsonDecode(request.body) as Map;
      if (body['company'] == 'aktish' && body['password'] == 'secret-pass') return json({'token': token, ...account});
      return json({'error': 'Неверный логин или пароль.'}, 401);
    }
    if (request.headers['Authorization'] != 'Bearer $token') return json({'error': 'Войдите заново.'}, 401);
    if (path == '/api/mobile/me') return json(account);
    if (path == '/api/mobile/summary') {
      final active = bookings.where((b) => b['status'] == 'booked').toList();
      int on(String day) => active.where((b) => (b['start_local'] as String).startsWith(day)).length;
      return json({'today': on('2026-11-13'), 'tomorrow': on('2026-11-14'), 'week': active.length,
          'next': active.isEmpty ? null : active.first});
    }
    if (path == '/api/mobile/bookings') {
      final day = request.url.queryParameters['day']!;
      return json({'bookings': bookings.where((b) => (b['start_local'] as String).startsWith(day)).toList()});
    }
    final cancel = RegExp(r'^/api/mobile/bookings/(\d+)/cancel$').firstMatch(path);
    if (cancel != null) {
      final b = bookings.firstWhere((b) => b['id'] == int.parse(cancel.group(1)!));
      if (b['status'] != 'booked') return json({'error': 'Запись уже отменена.'}, 409);
      b['status'] = 'cancelled';
      return json({'booking': b, 'waitlist_offered': 0});
    }
    if (path == '/api/mobile/services') {
      return json({
        'services': [
          {'id': 1, 'name': 'Консультация', 'price': '500', 'category': 'Терапия', 'available': true},
          {'id': 2, 'name': 'Отбеливание', 'price': 'от 8 000', 'category': '', 'available': false},
        ]
      });
    }
    return json({'error': 'not found'}, 404);
  });

  ApiClient api() => ApiClient(httpClient: client, baseUrl: 'https://joop.test');

  JoopRepository repository() => JoopRepository(api());

  CustomerRepository customers() => CustomerRepository(api());
}
