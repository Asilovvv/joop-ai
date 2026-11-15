import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:joop_mobile/core/api_client.dart';
import 'package:joop_mobile/data/customer_repository.dart';
import 'package:joop_mobile/data/joop_repository.dart';

/// A tiny stand-in for the Joop server's /api/mobile, enough for the app's tests.
class FakeJoop {
  FakeJoop({this.cafe = false});

  /// A cafe: orders and requests, no bookings.
  final bool cafe;

  final orders = <Map<String, dynamic>>[
    {
      'id': 41, 'created_at': '2026-11-13T05:10:00Z', 'status': 'new', 'label': 'Новый', 'mode': 'delivery',
      'address': 'Токтогула 1', 'wanted_time': '13:00', 'total': 1200, 'channel': 'telegram', 'comment': '',
      'customer': {'name': 'Азамат', 'phone': '+996555000111'},
      'lines': [{'name': 'Плов', 'quantity': 2, 'unit_price': 600}],
      'next': [{'status': 'accepted', 'label': 'Принять'}, {'status': 'cancelled', 'label': 'Отменить'}],
    },
  ];
  final leads = <Map<String, dynamic>>[
    {
      'id': 9, 'created_at': '2026-11-13T06:00:00Z', 'kind': 'handoff', 'summary': 'Можно банкет на 40 человек?',
      'details': '', 'status': 'new', 'channel': 'whatsapp', 'customer': {'name': 'Айбек', 'phone': ''}, 'closed_by': '',
      'conversation_id': 70,
    },
  ];

  final chats = <Map<String, dynamic>>[
    {'id': 70, 'channel': 'whatsapp', 'customer': {'name': 'Айбек', 'phone': '+996700111222'},
     'last_message_at': '2026-11-13T06:00:05Z', 'last': {'role': 'ai', 'text': 'Передал вопрос администратору.'},
     'ai_paused': false, 'blocked': false},
    {'id': 71, 'channel': 'telegram', 'customer': {'name': 'Динара', 'phone': ''},
     'last_message_at': '2026-11-12T09:00:00Z', 'last': {'role': 'customer', 'text': 'Спасибо!'},
     'ai_paused': true, 'blocked': false},
  ];

  /// Dialogues behind requests; a non-empty reply_blocked makes the reply fail as the server does.
  final dialogues = <int, Map<String, dynamic>>{
    70: {
      'id': 70, 'channel': 'whatsapp', 'customer': {'name': 'Айбек', 'phone': '+996700111222'},
      'ai_paused': false, 'reply_blocked': '',
      'messages': [
        {'id': 1, 'role': 'customer', 'text': 'Можно банкет на 40 человек?', 'created_at': '2026-11-13T06:00:00Z', 'author': ''},
        {'id': 2, 'role': 'ai', 'text': 'Передал вопрос администратору.', 'created_at': '2026-11-13T06:00:05Z', 'author': ''},
      ],
    },
  };

  final bookings = <Map<String, dynamic>>[
    _booking(1, '2026-11-13T10:00:00', 'Айгуль', 'whatsapp'),
    _booking(2, '2026-11-13T15:30:00', 'Бакыт', 'telegram'),
    _booking(3, '2026-11-14T09:00:00', 'Нурлан', 'instagram'),
  ];
  final calls = <String>[];

  /// The day's times by person, for «Окна».
  final schedule = <Map<String, dynamic>>[
    {
      'id': 1, 'name': 'Др. Асанова', 'from_altegio': false,
      'slots': [
        {'id': 41, 'start_local': '2026-11-13T12:00:00', 'state': 'booked', 'seats': 1, 'taken': 1, 'customer': 'Айгуль'},
        {'id': 42, 'start_local': '2026-11-13T13:00:00', 'state': 'free', 'seats': 1, 'taken': 0, 'customer': ''},
        {'id': 43, 'start_local': '2026-11-13T14:00:00', 'state': 'busy', 'seats': 1, 'taken': 0, 'customer': ''},
      ],
    },
    {
      'id': 2, 'name': 'Др. Бекова', 'from_altegio': true,
      'slots': [
        {'id': 51, 'start_local': '2026-11-13T12:00:00', 'state': 'free', 'seats': 1, 'taken': 0, 'customer': ''},
      ],
    },
  ];

  final customerRows = <Map<String, dynamic>>[
    {'key': '700000001', 'name': 'Айгуль', 'phone': '+996700000001', 'channels': ['whatsapp'], 'visits': 3,
     'spend_som': 4500, 'last_visit_local': '2026-11-02T10:00:00', 'tags': ['VIP'], 'note': ''},
    {'key': '555123456', 'name': 'Бакыт', 'phone': '+996555123456', 'channels': [], 'visits': 1,
     'spend_som': 500, 'last_visit_local': null, 'tags': [], 'note': ''},
  ];

  /// owner | staff | master: who the dental login signs in as.
  String role = 'owner';

  final services = <Map<String, dynamic>>[
    {'id': 1, 'name': 'Консультация', 'price': '500', 'category': 'Терапия', 'available': true},
    {'id': 2, 'name': 'Отбеливание', 'price': 'от 8 000', 'category': '', 'available': false},
    {'id': 3, 'name': 'Зубная щётка', 'price': '300', 'category': '', 'available': false, 'sold_out': true},
  ];

  /// Free times staff can book a customer into; booking one takes it, as on the server.
  final freeSlots = <Map<String, dynamic>>[
    {'id': 31, 'start_local': '2026-11-13T12:00:00', 'staff_id': 1, 'staff': 'Др. Асанова', 'seats_left': 1, 'seats': 1},
    {'id': 32, 'start_local': '2026-11-13T17:00:00', 'staff_id': 2, 'staff': 'Др. Бекова', 'seats_left': 1, 'seats': 1},
  ];

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
        'suggested_som': 1500,
        'paid': null,
        'customer_key': id == 1 ? '700000001' : '',
      };

  /// Notes saved on customer cards, by key.
  final notes = <String, Map<String, dynamic>>{};

  static const token = 'good-token';

  late final client = MockClient((request) async {
    final path = request.url.path;
    calls.add('${request.method} $path');
    http.Response json(Object body, [int status = 200]) =>
        http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json; charset=utf-8'});
    final account = cafe
        ? {
            'business': {'id': 2, 'slug': 'navat', 'name': 'Нават', 'niche': 'restaurant'},
            'who': 'Владелец',
            'role': 'owner',
            'sections': {'bookings': false, 'orders': true, 'leads': true},
          }
        : {
            'business': {'id': 1, 'slug': 'aktish', 'name': 'Ак-Тиш Дент', 'niche': 'dental'},
            'who': role == 'master' ? 'Айгерим' : 'Владелец',
            'role': role,
            'sections': {'bookings': true, 'orders': false, 'leads': role != 'master', 'cash': true},
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
      if (body['company'] == (cafe ? 'navat' : 'aktish') && body['password'] == 'secret-pass') {
        return json({'token': token, ...account});
      }
      return json({'error': 'Неверный логин или пароль.'}, 401);
    }
    if (request.headers['Authorization'] != 'Bearer $token') return json({'error': 'Войдите заново.'}, 401);
    if (path == '/api/mobile/me') return json(account);
    if (path == '/api/mobile/summary') {
      final active = bookings.where((b) => b['status'] == 'booked').toList();
      int on(String day) => active.where((b) => (b['start_local'] as String).startsWith(day)).length;
      return json({'today': on('2026-11-13'), 'tomorrow': on('2026-11-14'), 'week': active.length,
          'next': active.isEmpty ? null : active.first,
          'deposits': active.where((b) => (b['deposit'] as Map?)?['status'] == 'check').toList()});
    }
    final deposit = RegExp(r'^/api/mobile/bookings/(\d+)/deposit$').firstMatch(path);
    if (deposit != null) {
      final b = bookings.firstWhere((x) => x['id'] == int.parse(deposit.group(1)!));
      final d = b['deposit'] as Map?;
      if (d == null || !const {'awaiting', 'check', 'overdue'}.contains(d['status'])) {
        return json({'error': 'Эта запись уже не ждёт предоплаты: её отметили раньше или сняли по сроку.'}, 409);
      }
      d['status'] = 'paid';
      return json({'booking': b, 'told': (b['channel'] as String).isNotEmpty});
    }
    final moveTo = RegExp(r'^/api/mobile/bookings/(\d+)/move$').firstMatch(path);
    if (moveTo != null) {
      final b = bookings.firstWhere((x) => x['id'] == int.parse(moveTo.group(1)!));
      final slotId = (jsonDecode(request.body) as Map)['slot_id'];
      final slot = freeSlots.where((x) => x['id'] == slotId).firstOrNull;
      if (slot == null) return json({'error': 'Это время уже занято. Выберите другое.'}, 409);
      freeSlots.remove(slot);
      b['start_local'] = slot['start_local'];
      b['staff'] = slot['staff'];
      return json({'booking': b, 'told': (b['channel'] as String).isNotEmpty});
    }
    final pay = RegExp(r'^/api/mobile/bookings/(\d+)/pay$').firstMatch(path);
    if (pay != null) {
      final b = bookings.firstWhere((x) => x['id'] == int.parse(pay.group(1)!));
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final amount = body['amount'] as int;
      b['paid'] = amount == 0 ? null : {'som': amount, 'method': body['method']};
      b['suggested_som'] = amount == 0 ? 1500 : 0;
      b['movable'] = amount == 0; // a paid visit has happened: it no longer moves
      return json({'booking': b});
    }
    if (path == '/api/mobile/customers') {
      final q = (request.url.queryParameters['q'] ?? '').toLowerCase();
      final tag = request.url.queryParameters['tag'] ?? '';
      final found = customerRows
          .where((c) => (q.isEmpty || (c['name'] as String).toLowerCase().contains(q) || (c['phone'] as String).contains(q)) &&
              (tag.isEmpty || (c['tags'] as List).contains(tag)))
          .toList();
      return json({'customers': found, 'total': found.length, 'tags': ['VIP']});
    }
    final person = RegExp(r'^/api/mobile/customers/(.+)$').firstMatch(path);
    if (person != null) {
      final key = Uri.decodeComponent(person.group(1)!);
      if (key != '700000001') return json({'error': 'Клиент не найден.'}, 404);
      if (request.method == 'POST') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        notes[key] = {
          'note': body['note'],
          'tags': [for (final t in (body['tags'] as String).split(',')) if (t.trim().isNotEmpty) t.trim()],
        };
        return json(notes[key]!);
      }
      final mine = bookings.where((b) => b['customer_key'] == key).toList();
      return json({
        'customer': {
          'key': key, 'name': mine.first['customer']['name'], 'phone': '+996700000001', 'channels': ['telegram'],
          'visits': 3, 'spend_som': 4500, 'rating': 4.7, 'note': notes[key]?['note'] ?? '', 'tags': notes[key]?['tags'] ?? [],
          'upcoming': null, 'bookings': mine,
          'orders': [
            {'id': 77, 'created_at': '2026-10-02T08:00:00Z', 'status': 'done', 'label': 'Выполнен', 'mode': 'pickup',
             'total': 600, 'channel': 'telegram', 'customer': {'name': 'x', 'phone': ''},
             'lines': [{'name': 'Зубная паста', 'quantity': 2, 'unit_price': 300}]},
          ],
        },
      });
    }
    if (path == '/api/mobile/cash') {
      final day = request.url.queryParameters['day']!;
      final rows = bookings.where((b) => (b['start_local'] as String).startsWith(day) && b['status'] == 'booked');
      final paid = rows.where((b) => b['paid'] != null);
      final byMethod = <String, int>{};
      for (final b in paid) {
        final p = b['paid'] as Map;
        byMethod[p['method'] as String] = (byMethod[p['method']] ?? 0) + (p['som'] as int);
      }
      final total = byMethod.values.fold(0, (a, b) => a + b);
      return json({
        'day': day, 'total': total, 'by_method': byMethod, 'visits': rows.length,
        'unpaid': rows.where((b) => b['paid'] == null && (b['start_local'] as String).compareTo('${day}T11:00') < 0).toList(),
        'month': {'total': total, 'paid_visits': paid.length},
      });
    }
    if (path == '/api/mobile/slots') {
      final day = request.url.queryParameters['day']!;
      return json({'day': day, 'slots': freeSlots.where((x) => (x['start_local'] as String).startsWith(day)).toList()});
    }
    if (path == '/api/mobile/bookings' && request.method == 'POST') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final slot = freeSlots.where((x) => x['id'] == body['slot_id']).firstOrNull;
      if (slot == null) return json({'error': 'Это время уже занято. Выберите другое.'}, 409);
      if ((body['phone'] as String).isNotEmpty && (body['phone'] as String).length < 9) {
        return json({'error': 'Телефон не похож на номер. Пример: 0555 123 456.'}, 422);
      }
      freeSlots.remove(slot);
      final made = {
        ..._booking(10 + bookings.length, slot['start_local'] as String, body['name'] as String, ''),
        'staff': slot['staff'], 'service': body['service'], 'source': 'staff',
        'customer': {'name': body['name'], 'phone': body['phone']}, 'confirmed': false,
      };
      bookings.add(made);
      return json({'booking': made});
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
    if (path == '/api/mobile/orders') return json({'orders': orders});
    final move = RegExp(r'^/api/mobile/orders/(\d+)/status$').firstMatch(path);
    if (move != null) {
      final o = orders.firstWhere((o) => o['id'] == int.parse(move.group(1)!));
      final to = (jsonDecode(request.body) as Map)['status'] as String;
      if (!(o['next'] as List).any((n) => n['status'] == to)) return json({'error': 'Заказ уже «${o['label']}».'}, 409);
      const steps = {
        'accepted': ('Принят', [
          {'status': 'sent', 'label': 'В пути'},
          {'status': 'done', 'label': 'Выполнен'},
          {'status': 'cancelled', 'label': 'Отменить'},
        ]),
        'sent': ('В пути', [
          {'status': 'done', 'label': 'Выполнен'},
          {'status': 'cancelled', 'label': 'Отменить'},
        ]),
        'done': ('Выполнен', <Map<String, String>>[]),
        'cancelled': ('Отменён', <Map<String, String>>[]),
      };
      o['status'] = to;
      o['label'] = steps[to]!.$1;
      o['next'] = steps[to]!.$2;
      return json({'order': o, 'customer_told': to == 'accepted' || to == 'sent' ? true : null, 'why': ''});
    }
    if (path == '/api/mobile/leads') return json({'leads': leads});
    final done = RegExp(r'^/api/mobile/leads/(\d+)/done$').firstMatch(path);
    if (done != null) {
      final x = leads.firstWhere((x) => x['id'] == int.parse(done.group(1)!));
      x['status'] = 'done';
      x['closed_by'] = 'Владелец';
      return json({'lead': x});
    }
    if (path == '/api/mobile/schedule') {
      final day = request.url.queryParameters['day']!;
      return json({
        'day': day,
        'staff': [
          for (final p in schedule)
            {...p, 'slots': (p['slots'] as List).where((x) => (x['start_local'] as String).startsWith(day)).toList()},
        ],
      });
    }
    String reopened(Map x) => (x['customer'] as String).isNotEmpty ? 'booked' : 'free';
    final oneTime = RegExp(r'^/api/mobile/schedule/slots/(\d+)$').firstMatch(path);
    if (oneTime != null) {
      final open = (jsonDecode(request.body) as Map)['open'] as bool;
      final x = schedule.expand((p) => p['slots'] as List).firstWhere((x) => x['id'] == int.parse(oneTime.group(1)!)) as Map;
      x['state'] = open ? reopened(x) : 'closed';
      return json({'changed': 1, 'offered': 0, 'bookings': []});
    }
    if (path == '/api/mobile/schedule/day') {
      final body = jsonDecode(request.body) as Map;
      final person = schedule.firstWhere((p) => p['id'] == body['staff_id']);
      if (person['from_altegio'] == true) return json({'error': 'Расписание из Altegio.'}, 409);
      final open = body['open'] as bool;
      final mine = (person['slots'] as List).cast<Map>().where((x) => (x['start_local'] as String).startsWith(body['day'] as String));
      var changed = 0;
      for (final x in mine) {
        if (open ? x['state'] == 'closed' : x['state'] != 'closed') changed++;
        x['state'] = open ? (x['state'] == 'closed' ? reopened(x) : x['state']) : 'closed';
      }
      return json({
        'changed': changed, 'offered': open ? 2 : 0,
        'bookings': open ? [] : [bookings.first],
      });
    }
    if (path == '/api/mobile/ai-results') {
      if (role == 'master') return json({'error': 'Нет доступа.'}, 403);
      return json({'days': 14, 'figures': {'conversations': 128, 'off_hours_conversations': 41, 'bookings': 37,
        'off_hours_bookings': 12, 'requests': 5, 'handed_to_people': 9}});
    }
    if (path == '/api/mobile/conversations') {
      final q = (request.url.queryParameters['q'] ?? '').toLowerCase();
      return json({'conversations': chats.where((c) => q.isEmpty || (c['customer']['name'] as String).toLowerCase().contains(q)).toList()});
    }
    final ai = RegExp(r'^/api/mobile/conversations/(\d+)/ai$').firstMatch(path);
    if (ai != null) {
      final d = dialogues[int.parse(ai.group(1)!)]!;
      final on = (jsonDecode(request.body) as Map)['on'] as bool;
      d['ai_paused'] = !on;
      d['ai_paused_until'] = on ? null : DateTime.now().toUtc().add(const Duration(hours: 24)).toIso8601String();
      return json(d);
    }
    final talk = RegExp(r'^/api/mobile/conversations/(\d+)(/reply)?$').firstMatch(path);
    if (talk != null) {
      final d = dialogues[int.parse(talk.group(1)!)];
      if (d == null) return json({'error': 'Диалог не найден.'}, 404);
      if (talk.group(2) == null) return json(d);
      if ((d['reply_blocked'] as String).isNotEmpty) return json({'error': d['reply_blocked']}, 422);
      final text = (jsonDecode(request.body) as Map)['text'] as String;
      (d['messages'] as List).add(
          {'id': 100, 'role': 'staff', 'text': text, 'created_at': '2026-11-13T07:00:00Z', 'author': 'Владелец'});
      d['ai_paused'] = true;
      final minutes = (d['takeover_minutes'] as int?) ?? 720;
      d['ai_paused_until'] = DateTime.now().toUtc().add(Duration(minutes: minutes)).toIso8601String();
      for (final x in leads.where((x) => x['conversation_id'] == d['id'])) {
        x['status'] = 'done';
        x['closed_by'] = 'Владелец';
      }
      return json(d);
    }
    if (path == '/api/mobile/services') return json({'services': services});
    final stop = RegExp(r'^/api/mobile/services/(\d+)/available$').firstMatch(path);
    if (stop != null) {
      final x = services.firstWhere((x) => x['id'] == int.parse(stop.group(1)!));
      if (x['sold_out'] == true) return json({'error': 'Закончилось на складе.'}, 409);
      x['available'] = (jsonDecode(request.body) as Map)['available'];
      return json({'service': x});
    }
    return json({'error': 'not found'}, 404);
  });

  ApiClient api() => ApiClient(httpClient: client, baseUrl: 'https://joop.test');

  JoopRepository repository() => JoopRepository(api());

  CustomerRepository customers() => CustomerRepository(api());
}
