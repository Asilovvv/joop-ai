import 'package:equatable/equatable.dart';

/// The signed-in person and their business, as /api/mobile/login and /api/mobile/me return them.
class Account extends Equatable {
  const Account({
    required this.businessName,
    required this.slug,
    required this.niche,
    required this.who,
    required this.role,
  });

  factory Account.fromJson(Map<String, dynamic> json) {
    final business = json['business'] as Map<String, dynamic>;
    return Account(
      businessName: business['name'] as String,
      slug: business['slug'] as String,
      niche: (business['niche'] as String?) ?? '',
      who: json['who'] as String,
      role: json['role'] as String,
    );
  }

  final String businessName;
  final String slug;
  final String niche;
  final String who;

  /// owner | staff | master (a master sees only her own bookings).
  final String role;

  bool get isOwner => role == 'owner';

  @override
  List<Object?> get props => [businessName, slug, niche, who, role];
}

class Booking extends Equatable {
  const Booking({
    required this.id,
    required this.start,
    required this.service,
    required this.staff,
    required this.customerName,
    required this.customerPhone,
    required this.channel,
    required this.status,
    required this.confirmed,
  });

  factory Booking.fromJson(Map<String, dynamic> json) {
    final customer = (json['customer'] as Map?) ?? const {};
    return Booking(
      id: json['id'] as int,
      // The business's local time, as the server stores it.
      start: DateTime.parse(json['start_local'] as String),
      service: (json['service'] as String?) ?? '',
      staff: (json['staff'] as String?) ?? '',
      customerName: (customer['name'] as String?) ?? '',
      customerPhone: (customer['phone'] as String?) ?? '',
      channel: (json['channel'] as String?) ?? '',
      status: json['status'] as String,
      confirmed: (json['confirmed'] as bool?) ?? false,
    );
  }

  final int id;
  final DateTime start;
  final String service;
  final String staff;
  final String customerName;
  final String customerPhone;
  final String channel;

  /// booked | cancelled
  final String status;

  /// The customer answered "да" to the reminder.
  final bool confirmed;

  bool get isActive => status == 'booked';

  Booking copyWith({String? status}) => Booking(
        id: id,
        start: start,
        service: service,
        staff: staff,
        customerName: customerName,
        customerPhone: customerPhone,
        channel: channel,
        status: status ?? this.status,
        confirmed: confirmed,
      );

  @override
  List<Object?> get props => [id, start, service, staff, customerName, customerPhone, channel, status, confirmed];
}

class Summary extends Equatable {
  const Summary({required this.today, required this.tomorrow, required this.week, this.next});

  factory Summary.fromJson(Map<String, dynamic> json) => Summary(
        today: json['today'] as int,
        tomorrow: json['tomorrow'] as int,
        week: json['week'] as int,
        next: json['next'] == null ? null : Booking.fromJson(json['next'] as Map<String, dynamic>),
      );

  final int today;
  final int tomorrow;
  final int week;
  final Booking? next;

  @override
  List<Object?> get props => [today, tomorrow, week, next];
}

class Service extends Equatable {
  const Service({required this.id, required this.name, required this.price, required this.category, required this.available});

  factory Service.fromJson(Map<String, dynamic> json) => Service(
        id: json['id'] as int,
        name: json['name'] as String,
        price: (json['price'] as String?) ?? '',
        category: (json['category'] as String?) ?? '',
        available: (json['available'] as bool?) ?? true,
      );

  final int id;
  final String name;
  final String price;
  final String category;
  final bool available;

  @override
  List<Object?> get props => [id, name, price, category, available];
}
