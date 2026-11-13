import 'package:equatable/equatable.dart';

/// The signed-in person and their business, as /api/mobile/login and /api/mobile/me return them.
class Account extends Equatable {
  const Account({
    required this.businessName,
    required this.slug,
    required this.niche,
    required this.who,
    required this.role,
    this.bookings = true,
    this.orders = false,
    this.leads = true,
  });

  factory Account.fromJson(Map<String, dynamic> json) {
    final business = json['business'] as Map<String, dynamic>;
    final sections = (json['sections'] as Map?) ?? const {};
    return Account(
      bookings: (sections['bookings'] as bool?) ?? true,
      orders: (sections['orders'] as bool?) ?? false,
      leads: (sections['leads'] as bool?) ?? true,
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

  /// Sections this login opens, by the business's niche: a cafe has orders, a master only her bookings.
  final bool bookings;
  final bool orders;
  final bool leads;

  bool get isOwner => role == 'owner';

  @override
  List<Object?> get props => [businessName, slug, niche, who, role, bookings, orders, leads];
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

/// A business's public card, for customers.
class Place extends Equatable {
  const Place({
    required this.slug,
    required this.name,
    required this.niche,
    required this.description,
    required this.address,
    required this.phone,
    required this.hours,
    required this.booking,
    required this.services,
  });

  factory Place.fromJson(Map<String, dynamic> json) => Place(
        slug: json['slug'] as String,
        name: json['name'] as String,
        niche: (json['niche'] as String?) ?? '',
        description: (json['description'] as String?) ?? '',
        address: (json['address'] as String?) ?? '',
        phone: (json['phone'] as String?) ?? '',
        hours: (json['hours'] as String?) ?? '',
        booking: (json['booking'] as bool?) ?? false,
        services: [
          for (final row in (json['services'] as List? ?? const []))
            Service.fromJson({...(row as Map<String, dynamic>), 'available': true}),
        ],
      );

  final String slug;
  final String name;
  final String niche;
  final String description;
  final String address;
  final String phone;
  final String hours;

  /// The business takes bookings (a clinic, a salon), not only orders or questions.
  final bool booking;
  final List<Service> services;

  @override
  List<Object?> get props => [slug, name, niche, description, address, phone, hours, booking, services];
}

/// A business the customer opened before, kept on the device.
class SavedPlace extends Equatable {
  const SavedPlace(this.slug, this.name);

  factory SavedPlace.fromJson(Map<String, dynamic> json) => SavedPlace(json['slug'] as String, json['name'] as String);

  final String slug;
  final String name;

  Map<String, dynamic> toJson() => {'slug': slug, 'name': name};

  @override
  List<Object?> get props => [slug, name];
}

class ChatMessage extends Equatable {
  const ChatMessage({required this.fromCustomer, required this.text, this.staffId});

  factory ChatMessage.fromJson(Map<String, dynamic> json) =>
      ChatMessage(fromCustomer: json['me'] as bool, text: json['text'] as String, staffId: json['staff'] as int?);

  final bool fromCustomer;
  final String text;

  /// Set for a reply a staff member wrote from the panel (its message id on the server).
  final int? staffId;

  Map<String, dynamic> toJson() => {'me': fromCustomer, 'text': text, if (staffId != null) 'staff': staffId};

  @override
  List<Object?> get props => [fromCustomer, text, staffId];
}

class OrderLine extends Equatable {
  const OrderLine(this.name, this.quantity, this.unitPrice);

  final String name;
  final int quantity;
  final int? unitPrice;

  @override
  List<Object?> get props => [name, quantity, unitPrice];
}

/// A next status the order can take, with the panel's label («Принят», «В пути», «Готов к выдаче»).
class OrderStep extends Equatable {
  const OrderStep(this.status, this.label);

  final String status;
  final String label;

  @override
  List<Object?> get props => [status, label];
}

class Order extends Equatable {
  const Order({
    required this.id,
    required this.createdAt,
    required this.status,
    required this.label,
    required this.delivery,
    required this.address,
    required this.wantedTime,
    required this.total,
    required this.customerName,
    required this.customerPhone,
    required this.channel,
    required this.comment,
    required this.lines,
    required this.next,
  });

  factory Order.fromJson(Map<String, dynamic> json) {
    final customer = (json['customer'] as Map?) ?? const {};
    return Order(
      id: json['id'] as int,
      createdAt: DateTime.parse(json['created_at'] as String).toLocal(),
      status: json['status'] as String,
      label: (json['label'] as String?) ?? json['status'] as String,
      delivery: json['mode'] == 'delivery',
      address: (json['address'] as String?) ?? '',
      wantedTime: (json['wanted_time'] as String?) ?? '',
      total: json['total'] as int?,
      customerName: (customer['name'] as String?) ?? '',
      customerPhone: (customer['phone'] as String?) ?? '',
      channel: (json['channel'] as String?) ?? '',
      comment: (json['comment'] as String?) ?? '',
      lines: [
        for (final l in (json['lines'] as List? ?? const []))
          OrderLine((l as Map)['name'] as String, (l['quantity'] as int?) ?? 1, l['unit_price'] as int?),
      ],
      next: [
        for (final n in (json['next'] as List? ?? const []))
          OrderStep((n as Map)['status'] as String, n['label'] as String),
      ],
    );
  }

  final int id;
  final DateTime createdAt;

  /// new | accepted | sent | done | cancelled
  final String status;
  final String label;
  final bool delivery;
  final String address;
  final String wantedTime;

  /// Items and delivery, som; null when a price is not exact («от …»).
  final int? total;
  final String customerName;
  final String customerPhone;
  final String channel;
  final String comment;
  final List<OrderLine> lines;
  final List<OrderStep> next;

  bool get isOpen => next.isNotEmpty;

  @override
  List<Object?> get props =>
      [id, createdAt, status, label, delivery, address, wantedTime, total, customerName, customerPhone, channel, comment, lines, next];
}

/// A request: a question the AI handed to staff, a booking without a free slot, or a qualified lead.
class Lead extends Equatable {
  const Lead({
    required this.id,
    required this.createdAt,
    required this.kind,
    required this.summary,
    required this.details,
    required this.customerName,
    required this.customerPhone,
    required this.channel,
    required this.done,
    required this.closedBy,
  });

  factory Lead.fromJson(Map<String, dynamic> json) {
    final customer = (json['customer'] as Map?) ?? const {};
    return Lead(
      id: json['id'] as int,
      createdAt: DateTime.parse(json['created_at'] as String).toLocal(),
      kind: (json['kind'] as String?) ?? 'handoff',
      summary: (json['summary'] as String?) ?? '',
      details: (json['details'] as String?) ?? '',
      customerName: (customer['name'] as String?) ?? '',
      customerPhone: (customer['phone'] as String?) ?? '',
      channel: (json['channel'] as String?) ?? '',
      done: json['status'] == 'done',
      closedBy: (json['closed_by'] as String?) ?? '',
    );
  }

  final int id;
  final DateTime createdAt;

  /// handoff | request | lead | media | error
  final String kind;
  final String summary;
  final String details;
  final String customerName;
  final String customerPhone;
  final String channel;
  final bool done;
  final String closedBy;

  String get kindLabel => switch (kind) {
        'request' => 'Запись без окна',
        'lead' => 'Заявка',
        'media' => 'Фото или файл',
        'error' => 'Сбой',
        _ => 'Вопрос сотруднику',
      };

  @override
  List<Object?> get props => [id, createdAt, kind, summary, details, customerName, customerPhone, channel, done, closedBy];
}
