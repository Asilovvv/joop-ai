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

  Future<List<Service>> services() async {
    final data = await _api.get('/api/mobile/services') as Map<String, dynamic>;
    return [for (final row in data['services'] as List) Service.fromJson(row as Map<String, dynamic>)];
  }
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
