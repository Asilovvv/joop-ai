import 'package:shared_preferences/shared_preferences.dart';

import '../core/api_client.dart';
import 'models.dart';

/// Everything the app asks the Joop server. The token is kept on the device between launches.
class JoopRepository {
  JoopRepository(this._api);

  final ApiClient _api;

  static const _tokenKey = 'joop_token';
  static const _serverKey = 'joop_server';

  String get server => _api.baseUrl;

  /// Restores the saved server address and token; null when there is no valid sign-in.
  Future<Account?> restore() async {
    final prefs = await SharedPreferences.getInstance();
    final server = prefs.getString(_serverKey);
    if (server != null) _api.baseUrl = server;
    final token = prefs.getString(_tokenKey);
    if (token == null) return null;
    _api.token = token;
    try {
      return Account.fromJson(await _api.get('/api/mobile/me') as Map<String, dynamic>);
    } on ApiException catch (e) {
      if (e.statusCode == 401) {
        await logout();
        return null;
      }
      rethrow;
    }
  }

  Future<Account> login(String company, String password, {String user = '', String? server}) async {
    final prefs = await SharedPreferences.getInstance();
    if (server != null) {
      _api.baseUrl = server;
      await prefs.setString(_serverKey, _api.baseUrl);
    }
    final data = await _api.post('/api/mobile/login', {'company': company, 'password': password, 'user': user})
        as Map<String, dynamic>;
    _api.token = data['token'] as String;
    await prefs.setString(_tokenKey, _api.token!);
    return Account.fromJson(data);
  }

  /// What a business can be, for the sign-up form: (key, name) pairs and the trial's length in days.
  Future<(List<(String, String)>, int)> niches({String? server}) async {
    if (server != null) _api.baseUrl = server;
    final data = await _api.get('/api/mobile/niches') as Map<String, dynamic>;
    final list = [for (final n in data['niches'] as List) (n['key'] as String, n['label'] as String)];
    return (list, (data['trial_days'] as int?) ?? 0);
  }

  /// Signs a new business up, as the site's /signup does, and keeps the session like [login].
  /// Returns the account and the panel's setup address on this server.
  Future<(Account, String)> signup({required String name, required String niche, required String phone,
      required String password, String contactName = '', String? server}) async {
    final prefs = await SharedPreferences.getInstance();
    if (server != null) {
      _api.baseUrl = server;
      await prefs.setString(_serverKey, _api.baseUrl);
    }
    final data = await _api.post('/api/mobile/signup',
        {'name': name, 'niche': niche, 'phone': phone, 'password': password, 'contact_name': contactName})
        as Map<String, dynamic>;
    _api.token = data['token'] as String;
    await prefs.setString(_tokenKey, _api.token!);
    return (Account.fromJson(data), '${_api.baseUrl}${data['setup_path'] ?? '/panel/setup'}');
  }

  Future<SetupInfo> setup() async => SetupInfo.fromJson(await _api.get('/api/mobile/setup') as Map<String, dynamic>);

  Future<SetupInfo> connectTelegram(String token) async =>
      SetupInfo.fromJson(await _api.post('/api/mobile/setup/telegram', {'token': token}) as Map<String, dynamic>);

  Future<SetupInfo> setPageBooking(bool on) async =>
      SetupInfo.fromJson(await _api.post('/api/mobile/setup/page-booking', {'on': on}) as Map<String, dynamic>);

  Future<List<DialogueMessage>> tryChat() async =>
      _tryMessages(await _api.get('/api/mobile/try') as Map<String, dynamic>);

  /// One message to the AI as a customer; the chat as it stands and what the server said (text, good news).
  Future<(List<DialogueMessage>, List<(String, bool)>)> trySend(String text) async {
    final data = await _api.post('/api/mobile/try', {'text': text}) as Map<String, dynamic>;
    return (
      _tryMessages(data),
      [for (final n in (data['notes'] as List? ?? const [])) ((n as Map)['text'] as String, n['ok'] == true)],
    );
  }

  /// «Новый диалог»: how many test bookings were cancelled.
  Future<int> tryReset() async =>
      ((await _api.post('/api/mobile/try/reset', const {}) as Map<String, dynamic>)['cancelled'] as int?) ?? 0;

  static List<DialogueMessage> _tryMessages(Map<String, dynamic> data) =>
      [for (final m in (data['messages'] as List? ?? const [])) DialogueMessage.fromJson(m as Map<String, dynamic>)];

  Future<ContactsInfo> contacts() async =>
      ContactsInfo.fromJson(await _api.get('/api/mobile/contacts') as Map<String, dynamic>);

  Future<ContactsInfo> saveContacts(ContactsInfo info) async =>
      ContactsInfo.fromJson(await _api.post('/api/mobile/contacts', info.toJson()) as Map<String, dynamic>);

  Future<void> logout() async {
    _api.token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
  }

  Future<Summary> summary() async =>
      Summary.fromJson(await _api.get('/api/mobile/summary') as Map<String, dynamic>);

  Future<List<Booking>> bookings(DateTime day) async {
    final data = await _api.get('/api/mobile/bookings', query: {'day': isoDay(day)}) as Map<String, dynamic>;
    return [for (final row in data['bookings'] as List) Booking.fromJson(row as Map<String, dynamic>)];
  }

  Future<Booking> cancel(int bookingId) async {
    final data = await _api.post('/api/mobile/bookings/$bookingId/cancel') as Map<String, dynamic>;
    return Booking.fromJson(data['booking'] as Map<String, dynamic>);
  }

  /// Moves a booking to another free time; returns it and whether the customer was told in their chat.
  Future<(Booking, bool)> move(int bookingId, int slotId) async {
    final data = await _api.post('/api/mobile/bookings/$bookingId/move', {'slot_id': slotId}) as Map<String, dynamic>;
    return (Booking.fromJson(data['booking'] as Map<String, dynamic>), (data['told'] as bool?) ?? false);
  }

  /// Staff saw the prepayment; returns the booking and whether the customer was told in their chat.
  Future<(Booking, bool)> depositPaid(int bookingId) async {
    final data = await _api.post('/api/mobile/bookings/$bookingId/deposit', const {}) as Map<String, dynamic>;
    return (Booking.fromJson(data['booking'] as Map<String, dynamic>), (data['told'] as bool?) ?? false);
  }

  /// What the customer paid after the visit; amount 0 removes a payment recorded by mistake.
  Future<Booking> pay(int bookingId, int amount, String method) async {
    final data = await _api.post('/api/mobile/bookings/$bookingId/pay', {'amount': amount, 'method': method})
        as Map<String, dynamic>;
    return Booking.fromJson(data['booking'] as Map<String, dynamic>);
  }

  Future<CashDay> cash(DateTime day) async =>
      CashDay.fromJson(await _api.get('/api/mobile/cash', query: {'day': isoDay(day)}) as Map<String, dynamic>);

  /// The stop list: false and the AI stops offering it; true and it is on sale again.
  Future<Service> setAvailable(int serviceId, bool available) async {
    final data = await _api.post('/api/mobile/services/$serviceId/available', {'available': available}) as Map<String, dynamic>;
    return Service.fromJson(data['service'] as Map<String, dynamic>);
  }

  /// Customers, newest contact first; [query] is a name or phone, [tag] a tag staff gave. Returns those found
  /// (at most 100), how many there are, and every tag in use.
  Future<(List<CustomerRow>, int, List<String>)> customers({String query = '', String tag = ''}) async {
    final data = await _api.get('/api/mobile/customers', query: {
      if (query.isNotEmpty) 'q': query,
      if (tag.isNotEmpty) 'tag': tag,
    }) as Map<String, dynamic>;
    return (
      [for (final c in data['customers'] as List) CustomerRow.fromJson(c as Map<String, dynamic>)],
      (data['total'] as int?) ?? 0,
      [for (final t in (data['tags'] as List? ?? const [])) t as String],
    );
  }

  Future<CustomerCard> customer(String key) async {
    final data = await _api.get('/api/mobile/customers/${Uri.encodeComponent(key)}') as Map<String, dynamic>;
    return CustomerCard.fromJson(data['customer'] as Map<String, dynamic>);
  }

  /// Saves the card's note and tags (comma-separated); returns them as the server keeps them.
  Future<(String, List<String>)> saveNote(String key, String note, String tags) async {
    final data = await _api.post('/api/mobile/customers/${Uri.encodeComponent(key)}', {'note': note, 'tags': tags})
        as Map<String, dynamic>;
    return (data['note'] as String, [for (final t in data['tags'] as List) t as String]);
  }

  Future<List<SchedulePerson>> schedule(DateTime day) async {
    final data = await _api.get('/api/mobile/schedule', query: {'day': isoDay(day)}) as Map<String, dynamic>;
    return [for (final p in data['staff'] as List) SchedulePerson.fromJson(p as Map<String, dynamic>)];
  }

  /// Closes one time, or opens a closed or busy one.
  Future<ScheduleChange> setSlotOpen(int slotId, bool open) async => ScheduleChange.fromJson(
      await _api.post('/api/mobile/schedule/slots/$slotId', {'open': open}) as Map<String, dynamic>);

  /// Closes a person's whole day (ill, on leave) or opens it again.
  Future<ScheduleChange> setDayOpen(int staffId, DateTime day, bool open) async => ScheduleChange.fromJson(await _api
      .post('/api/mobile/schedule/day', {'staff_id': staffId, 'day': isoDay(day), 'open': open}) as Map<String, dynamic>);

  Future<List<FreeSlot>> freeSlots(DateTime day) async {
    final data = await _api.get('/api/mobile/slots', query: {'day': isoDay(day)}) as Map<String, dynamic>;
    return [for (final row in data['slots'] as List) FreeSlot.fromJson(row as Map<String, dynamic>)];
  }

  /// A customer who phoned or walked in, booked into a free time by staff.
  Future<Booking> book({required int slotId, required String name, String phone = '', String service = ''}) async {
    final data = await _api.post('/api/mobile/bookings', {'slot_id': slotId, 'name': name, 'phone': phone, 'service': service})
        as Map<String, dynamic>;
    return Booking.fromJson(data['booking'] as Map<String, dynamic>);
  }

  Future<List<Order>> orders() async {
    final data = await _api.get('/api/mobile/orders') as Map<String, dynamic>;
    return [for (final row in data['orders'] as List) Order.fromJson(row as Map<String, dynamic>)];
  }

  /// Moves an order on; [OrderMove.customerTold] is false when the customer's channel would not take the message.
  Future<OrderMove> moveOrder(int orderId, String status) async {
    final data = await _api.post('/api/mobile/orders/$orderId/status', {'status': status}) as Map<String, dynamic>;
    return OrderMove(Order.fromJson(data['order'] as Map<String, dynamic>), data['customer_told'] as bool?,
        (data['why'] as String?) ?? '');
  }

  Future<List<Lead>> leads() async {
    final data = await _api.get('/api/mobile/leads') as Map<String, dynamic>;
    return [for (final row in data['leads'] as List) Lead.fromJson(row as Map<String, dynamic>)];
  }

  Future<Lead> closeLead(int leadId) async {
    final data = await _api.post('/api/mobile/leads/$leadId/done') as Map<String, dynamic>;
    return Lead.fromJson(data['lead'] as Map<String, dynamic>);
  }

  Future<List<Stay>> stays() async {
    final data = await _api.get('/api/mobile/stays') as Map<String, dynamic>;
    return [for (final row in data['stays'] as List) Stay.fromJson(row as Map<String, dynamic>)];
  }

  Future<List<FreeRoom>> freeRooms(DateTime checkIn, DateTime checkOut) async {
    final data = await _api.get('/api/mobile/stays/rooms',
        query: {'check_in': isoDay(checkIn), 'check_out': isoDay(checkOut)}) as Map<String, dynamic>;
    return [for (final row in data['rooms'] as List) FreeRoom.fromJson(row as Map<String, dynamic>)];
  }

  /// A guest who phoned or walked in, booked by staff with the AI's rules (dates, capacity, a free room each night).
  Future<Stay> newStay({
    required int roomId,
    required DateTime checkIn,
    required DateTime checkOut,
    required int guests,
    required String name,
    required String phone,
  }) async {
    final data = await _api.post('/api/mobile/stays', {
      'room_id': roomId,
      'check_in': isoDay(checkIn),
      'check_out': isoDay(checkOut),
      'guests': guests,
      'name': name.trim(),
      'phone': phone.trim(),
    }) as Map<String, dynamic>;
    return Stay.fromJson(data['stay'] as Map<String, dynamic>);
  }

  /// The room, car or hall is free again for those dates; the customer is told by staff, as in the panel.
  Future<Stay> cancelStay(int stayId) async {
    final data = await _api.post('/api/mobile/stays/$stayId/cancel') as Map<String, dynamic>;
    return Stay.fromJson(data['stay'] as Map<String, dynamic>);
  }

  Future<AiResults> aiResults() async =>
      AiResults.fromJson(await _api.get('/api/mobile/ai-results') as Map<String, dynamic>);

  Future<List<ChatSummary>> chats({String query = ''}) async {
    final data = await _api.get('/api/mobile/conversations', query: query.isEmpty ? null : {'q': query}) as Map<String, dynamic>;
    return [for (final row in data['conversations'] as List) ChatSummary.fromJson(row as Map<String, dynamic>)];
  }

  Future<Dialogue> dialogue(int conversationId) async =>
      Dialogue.fromJson(await _api.get('/api/mobile/conversations/$conversationId') as Map<String, dynamic>);

  /// Staff take the chat over (the AI stays quiet for a day) or give it back to the AI.
  Future<Dialogue> switchAi(int conversationId, bool on) async => Dialogue.fromJson(
      await _api.post('/api/mobile/conversations/$conversationId/ai', {'on': on}) as Map<String, dynamic>);

  /// Answers the customer through their channel; the server says why when it cannot (422).
  Future<Dialogue> reply(int conversationId, String text) async => Dialogue.fromJson(
      await _api.post('/api/mobile/conversations/$conversationId/reply', {'text': text}) as Map<String, dynamic>);

  Future<List<Service>> services() async => _services(await _api.get('/api/mobile/services') as Map<String, dynamic>);

  /// A new row of the price list; the list as it stands after.
  Future<List<Service>> addService(ServiceDraft draft) async =>
      _services(await _api.post('/api/mobile/services', draft.toJson()) as Map<String, dynamic>);

  Future<List<Service>> updateService(int id, ServiceDraft draft) async =>
      _services(await _api.post('/api/mobile/services/$id', draft.toJson()) as Map<String, dynamic>);

  Future<List<Service>> deleteService(int id) async =>
      _services(await _api.post('/api/mobile/services/$id/delete') as Map<String, dynamic>);

  /// Every row still the sign-up example out at once: how many went, and the list after.
  Future<(int, List<Service>)> deleteExample() async {
    final data = await _api.post('/api/mobile/services/example/delete') as Map<String, dynamic>;
    return ((data['removed'] as int?) ?? 0, _services(data));
  }

  static List<Service> _services(Map<String, dynamic> data) =>
      [for (final row in data['services'] as List) Service.fromJson(row as Map<String, dynamic>)];
}

String isoDay(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

class OrderMove {
  const OrderMove(this.order, this.customerTold, this.why);

  final Order order;

  /// null: this step is not told to the customer; true: told; false: the channel did not take it ([why]).
  final bool? customerTold;
  final String why;
}
