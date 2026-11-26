import 'package:equatable/equatable.dart';

import '../core/strings.dart';

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
    this.cash = false,
    this.stays = false,
    this.stayKind = 'room',
    this.peopleLabel = '',
  });

  factory Account.fromJson(Map<String, dynamic> json) {
    final business = json['business'] as Map<String, dynamic>;
    final sections = (json['sections'] as Map?) ?? const {};
    return Account(
      bookings: (sections['bookings'] as bool?) ?? true,
      orders: (sections['orders'] as bool?) ?? false,
      leads: (sections['leads'] as bool?) ?? true,
      cash: (sections['cash'] as bool?) ?? false,
      stays: (sections['stays'] as bool?) ?? false,
      stayKind: (json['stay_kind'] as String?) ?? 'room',
      peopleLabel: (json['people_label'] as String?) ?? '',
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

  /// Payments after visits (the panel's Касса).
  final bool cash;

  /// Hotel rooms, cars or banquet halls booked by dates (the panel's «Брони»), and which of the three.
  final bool stays;

  /// room | car | hall
  final String stayKind;

  /// The people screen's title («Специалисты», «Столы»); empty where this login does not edit them.
  final String peopleLabel;

  bool get isOwner => role == 'owner';

  @override
  List<Object?> get props => [businessName, slug, niche, who, role, bookings, orders, leads, cash, stays, stayKind, peopleLabel];
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
    this.paidSom = 0,
    this.paidMethod = '',
    this.suggestedSom = 0,
    this.customerKey = '',
    this.movable = true,
    this.depositDue = 0,
    this.depositStatus = '',
    this.depositDeadline,
    this.source = '',
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
      paidSom: ((json['paid'] as Map?)?['som'] as int?) ?? 0,
      paidMethod: ((json['paid'] as Map?)?['method'] as String?) ?? '',
      suggestedSom: (json['suggested_som'] as int?) ?? 0,
      customerKey: (json['customer_key'] as String?) ?? '',
      movable: (json['movable'] as bool?) ?? true,
      depositDue: ((json['deposit'] as Map?)?['due'] as int?) ?? 0,
      depositStatus: ((json['deposit'] as Map?)?['status'] as String?) ?? '',
      depositDeadline: (json['deposit'] as Map?)?['deadline'] == null
          ? null
          : DateTime.parse((json['deposit'] as Map)['deadline'] as String).toLocal(),
      source: (json['source'] as String?) ?? '',
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

  /// What the customer paid after the visit, som; 0 = not recorded.
  final int paidSom;

  /// cash | card | transfer
  final String paidMethod;

  /// The price-list amount to pre-fill an unpaid visit's payment with; 0 when unknown.
  final int suggestedSom;

  /// The customer's card (the phone's last nine digits, else the chat); empty when there is none.
  final String customerKey;

  /// The visit has not happened (not paid, not hours ago, not kept in Altegio): it can move to another free time.
  final bool movable;

  /// The prepayment the AI asked for, som; 0 when none.
  final int depositDue;

  /// "" | awaiting | check (the customer sent a receipt) | paid | overdue | expired
  final String depositStatus;

  /// Until when the prepayment is expected (local time).
  final DateTime? depositDeadline;

  /// Who made it: ai | staff | api (a partner's system or another assistant, joop/api.py and joop/mcp.py).
  final String source;

  /// Staff can mark the prepayment received (the panel's «Предоплата получена»).
  bool get depositOpen => isActive && const {'awaiting', 'check', 'overdue'}.contains(depositStatus);

  bool get isActive => status == 'booked';
  bool get isPaid => paidSom > 0;

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
        paidSom: paidSom,
        paidMethod: paidMethod,
        suggestedSom: suggestedSom,
        customerKey: customerKey,
        movable: movable && (status ?? this.status) == 'booked',
        depositDue: depositDue,
        depositStatus: depositStatus,
        depositDeadline: depositDeadline,
        source: source,
      );

  @override
  List<Object?> get props => [
        id, start, service, staff, customerName, customerPhone, channel, status, confirmed, paidSom, paidMethod, //
        suggestedSom, customerKey, movable, depositDue, depositStatus, depositDeadline, source,
      ];
}

class Summary extends Equatable {
  const Summary({required this.today, required this.tomorrow, required this.week, this.next, this.deposits = const [], this.period});

  factory Summary.fromJson(Map<String, dynamic> json) => Summary(
        today: json['today'] as int,
        tomorrow: json['tomorrow'] as int,
        week: json['week'] as int,
        next: json['next'] == null ? null : Booking.fromJson(json['next'] as Map<String, dynamic>),
        deposits: [
          for (final b in (json['deposits'] as List? ?? const [])) Booking.fromJson(b as Map<String, dynamic>)
        ],
        period: json['period'] == null ? null : PeriodLine.fromJson(json['period'] as Map<String, dynamic>),
      );

  final int today;
  final int tomorrow;
  final int week;
  final Booking? next;

  /// Upcoming bookings whose prepayment needs a person's look: a receipt was sent, or the deadline passed.
  final List<Booking> deposits;

  /// The panel's line while the AI is about to stop or has stopped for payment; null otherwise.
  final PeriodLine? period;

  @override
  List<Object?> get props => [today, tomorrow, week, next, deposits, period];
}

/// The end of the trial or the paid month (joop/period_end.py), as the panel shows it on every page.
class PeriodLine extends Equatable {
  const PeriodLine({required this.level, required this.text, this.payUrl, this.askOwner = false});

  factory PeriodLine.fromJson(Map<String, dynamic> json) => PeriodLine(
        level: (json['level'] as String?) ?? 'warn',
        text: (json['text'] as String?) ?? '',
        payUrl: json['pay_url'] as String?,
        askOwner: (json['ask_owner'] as bool?) ?? false,
      );

  /// warn: about to stop; error: the AI does not answer customers now.
  final String level;
  final String text;

  /// The billing page, for the owner only, and only when paying is the way out (not while a transfer waits).
  final String? payUrl;

  /// Staff: paying is the owner's, so the line asks them to tell the owner.
  final bool askOwner;

  bool get stopped => level == 'error';

  @override
  List<Object?> get props => [level, text, payUrl, askOwner];
}

class Service extends Equatable {
  const Service({
    required this.id,
    required this.name,
    required this.price,
    required this.category,
    required this.available,
    this.soldOut = false,
    this.fromAltegio = false,
    this.example = false,
    this.nameKy = '',
    this.note = '',
  });

  factory Service.fromJson(Map<String, dynamic> json) => Service(
        id: json['id'] as int,
        name: json['name'] as String,
        price: (json['price'] as String?) ?? '',
        category: (json['category'] as String?) ?? '',
        available: (json['available'] as bool?) ?? true,
        soldOut: (json['sold_out'] as bool?) ?? false,
        fromAltegio: (json['from_altegio'] as bool?) ?? false,
        example: (json['example'] as bool?) ?? false,
        nameKy: (json['name_ky'] as String?) ?? '',
        note: (json['note'] as String?) ?? '',
      );

  final int id;
  final String name;
  final String price;
  final String category;

  /// The AI offers it.
  final bool available;

  /// The stock reached zero: back on sale when the panel's «Склад» gets a new count.
  final bool soldOut;

  /// The salon's Altegio price list sets it, so it is switched there.
  final bool fromAltegio;

  /// Still the sign-up example: the AI does not name it to real customers until the owner changes it.
  final bool example;

  /// The Kyrgyz name, if the owner gave one; the AI uses it in Kyrgyz answers.
  final String nameKy;

  /// What the AI may add about it (duration, what is included).
  final String note;

  /// The owner can put it on the stop list or back from the app.
  bool get switchable => !fromAltegio && !soldOut;

  @override
  List<Object?> get props => [id, name, price, category, available, soldOut, fromAltegio, example, nameKy, note];
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
  List<Object?> get props => [
        id,
        createdAt,
        status,
        label,
        delivery,
        address,
        wantedTime,
        total,
        customerName,
        customerPhone,
        channel,
        comment,
        lines,
        next
      ];
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
    this.conversationId,
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
      conversationId: json['conversation_id'] as int?,
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

  /// The dialogue the request came from; null for one made without a chat.
  final int? conversationId;

  String get kindLabel => S.current.leadKinds[kind] ?? S.current.leadKinds['handoff']!;

  @override
  List<Object?> get props =>
      [id, createdAt, kind, summary, details, customerName, customerPhone, channel, done, closedBy, conversationId];
}

/// A hotel room, a car or a banquet hall booked for dates: [checkIn, checkOut), one date for a hall.
class Stay extends Equatable {
  const Stay({
    required this.id,
    required this.room,
    required this.checkIn,
    required this.checkOut,
    required this.nights,
    required this.guests,
    required this.customerName,
    required this.customerPhone,
    required this.channel,
    required this.cancelled,
    this.conversationId,
    this.manual = false,
    this.test = false,
  });

  factory Stay.fromJson(Map<String, dynamic> json) => Stay(
        id: json['id'] as int,
        room: (json['room'] as String?) ?? '',
        checkIn: DateTime.parse(json['check_in'] as String),
        checkOut: DateTime.parse(json['check_out'] as String),
        nights: (json['nights'] as int?) ?? 1,
        guests: (json['guests'] as int?) ?? 1,
        customerName: (json['customer_name'] as String?) ?? '',
        customerPhone: (json['customer_phone'] as String?) ?? '',
        channel: (json['channel'] as String?) ?? '',
        cancelled: json['status'] == 'cancelled',
        conversationId: json['conversation_id'] as int?,
        manual: (json['manual'] as bool?) ?? false,
        test: (json['test'] as bool?) ?? false,
      );

  final int id;
  final String room;
  final DateTime checkIn;
  final DateTime checkOut;
  final int nights;
  final int guests;
  final String customerName;
  final String customerPhone;
  final String channel;
  final bool cancelled;
  final int? conversationId;

  /// Booked by staff from the app («Вручную»), not by the AI.
  final bool manual;

  /// Made in a test chat: it still holds real nights until cancelled.
  final bool test;

  @override
  List<Object?> get props => [
        id, room, checkIn, checkOut, nights, guests, customerName, customerPhone, channel, cancelled, conversationId,
        manual, test,
      ];
}

/// A room type (car, hall) and how many are free for all the chosen nights.
class FreeRoom extends Equatable {
  const FreeRoom({required this.id, required this.name, required this.capacity, required this.free});

  factory FreeRoom.fromJson(Map<String, dynamic> json) => FreeRoom(
        id: json['id'] as int,
        name: (json['name'] as String?) ?? '',
        capacity: (json['capacity'] as int?) ?? 0,
        free: (json['free'] as int?) ?? 0,
      );

  final int id;
  final String name;

  /// Guests per room; 0 = not limited.
  final int capacity;
  final int free;

  @override
  List<Object?> get props => [id, name, capacity, free];
}

class DialogueMessage extends Equatable {
  const DialogueMessage(
      {required this.id, required this.role, required this.text, required this.at, required this.author});

  factory DialogueMessage.fromJson(Map<String, dynamic> json) => DialogueMessage(
        id: json['id'] as int,
        role: json['role'] as String,
        text: json['text'] as String,
        at: DateTime.parse(json['created_at'] as String).toLocal(),
        author: (json['author'] as String?) ?? '',
      );

  final int id;

  /// customer | ai | staff
  final String role;
  final String text;
  final DateTime at;

  /// Who of the staff wrote a staff message.
  final String author;

  bool get fromCustomer => role == 'customer';

  @override
  List<Object?> get props => [id, role, text, at, author];
}

/// What the owner typed for a price-list row, as /api/mobile/services takes it.
class ServiceDraft {
  const ServiceDraft({required this.name, this.price = '', this.nameKy = '', this.note = ''});

  final String name;
  final String price;
  final String nameKy;
  final String note;

  Map<String, dynamic> toJson() => {'name': name, 'price': price, 'name_ky': nameKy, 'note': note};
}

/// A customer's dialogue with the business: the AI's answers, staff replies, and whether staff can answer now.
class Dialogue extends Equatable {
  const Dialogue({
    required this.id,
    required this.channel,
    required this.customerName,
    required this.customerPhone,
    required this.aiPaused,
    required this.replyBlocked,
    required this.messages,
    this.aiPausedUntil,
    this.takeoverMinutes = 720,
    this.quickReplies = const [],
  });

  factory Dialogue.fromJson(Map<String, dynamic> json) {
    final customer = (json['customer'] as Map?) ?? const {};
    return Dialogue(
      id: json['id'] as int,
      channel: (json['channel'] as String?) ?? '',
      customerName: (customer['name'] as String?) ?? '',
      customerPhone: (customer['phone'] as String?) ?? '',
      aiPaused: (json['ai_paused'] as bool?) ?? false,
      aiPausedUntil:
          json['ai_paused_until'] == null ? null : DateTime.parse(json['ai_paused_until'] as String).toLocal(),
      takeoverMinutes: (json['takeover_minutes'] as int?) ?? 720,
      quickReplies: [
        for (final r in (json['quick_replies'] as List? ?? const []))
          (title: (r as Map)['title'] as String, text: r['text'] as String),
      ],
      replyBlocked: (json['reply_blocked'] as String?) ?? '',
      messages: [
        for (final m in (json['messages'] as List? ?? const [])) DialogueMessage.fromJson(m as Map<String, dynamic>),
      ],
    );
  }

  final int id;
  final String channel;
  final String customerName;
  final String customerPhone;

  /// The AI stays out of this chat for a while after a staff reply.
  final bool aiPaused;

  /// Until when the AI stays out (local time); null when it answers.
  final DateTime? aiPausedUntil;

  /// How long each staff reply keeps the AI out, as the owner chose in the panel's settings.
  final int takeoverMinutes;

  /// The panel's «Готовые ответы», already filled for this customer.
  final List<({String title, String text})> quickReplies;

  /// Why staff cannot answer now (WhatsApp's and Instagram's 24 hours), from the server; empty when they can.
  final String replyBlocked;
  final List<DialogueMessage> messages;

  @override
  List<Object?> get props => [
        id,
        channel,
        customerName,
        customerPhone,
        aiPaused,
        replyBlocked,
        messages,
        aiPausedUntil,
        takeoverMinutes,
        quickReplies
      ];
}

/// A free time staff can book a customer into (GET /api/mobile/slots).
class FreeSlot extends Equatable {
  const FreeSlot(
      {required this.id,
      required this.start,
      required this.staffId,
      required this.staff,
      required this.seatsLeft,
      required this.seats});

  factory FreeSlot.fromJson(Map<String, dynamic> json) => FreeSlot(
        id: json['id'] as int,
        start: DateTime.parse(json['start_local'] as String),
        staffId: json['staff_id'] as int,
        staff: json['staff'] as String,
        seatsLeft: (json['seats_left'] as int?) ?? 1,
        seats: (json['seats'] as int?) ?? 1,
      );

  final int id;

  /// The business's local time, as bookings carry it.
  final DateTime start;
  final int staffId;
  final String staff;

  /// For a group class: places left of [seats].
  final int seatsLeft;
  final int seats;

  @override
  List<Object?> get props => [id, start, staffId, staff, seatsLeft, seats];
}

/// A day's takings (GET /api/mobile/cash): what was paid, by method, and visits that passed without a payment.
class CashDay extends Equatable {
  const CashDay(
      {required this.total,
      required this.byMethod,
      required this.visits,
      required this.unpaid,
      required this.monthTotal});

  factory CashDay.fromJson(Map<String, dynamic> json) => CashDay(
        total: json['total'] as int,
        byMethod: {for (final e in ((json['by_method'] as Map?) ?? const {}).entries) e.key as String: e.value as int},
        visits: (json['visits'] as int?) ?? 0,
        unpaid: [for (final r in (json['unpaid'] as List? ?? const [])) Booking.fromJson(r as Map<String, dynamic>)],
        monthTotal: ((json['month'] as Map?)?['total'] as int?) ?? 0,
      );

  final int total;
  final Map<String, int> byMethod;
  final int visits;
  final List<Booking> unpaid;
  final int monthTotal;

  @override
  List<Object?> get props => [total, byMethod, visits, unpaid, monthTotal];
}

/// Everything the business knows about one customer, assembled from bookings, orders and dialogues; staff add only a
/// note and tags.
class CustomerCard extends Equatable {
  const CustomerCard({
    required this.key,
    required this.name,
    required this.phone,
    required this.channels,
    required this.visits,
    required this.spendSom,
    required this.rating,
    required this.note,
    required this.tags,
    required this.upcoming,
    required this.bookings,
    required this.orders,
  });

  factory CustomerCard.fromJson(Map<String, dynamic> json) => CustomerCard(
        key: json['key'] as String,
        name: (json['name'] as String?) ?? '',
        phone: (json['phone'] as String?) ?? '',
        channels: [for (final c in (json['channels'] as List? ?? const [])) c as String],
        visits: (json['visits'] as int?) ?? 0,
        spendSom: (json['spend_som'] as int?) ?? 0,
        rating: (json['rating'] as num?)?.toDouble(),
        note: (json['note'] as String?) ?? '',
        tags: [for (final t in (json['tags'] as List? ?? const [])) t as String],
        upcoming: json['upcoming'] == null ? null : Booking.fromJson(json['upcoming'] as Map<String, dynamic>),
        bookings: [
          for (final b in (json['bookings'] as List? ?? const [])) Booking.fromJson(b as Map<String, dynamic>)
        ],
        orders: [for (final o in (json['orders'] as List? ?? const [])) Order.fromJson(o as Map<String, dynamic>)],
      );

  final String key;
  final String name;
  final String phone;
  final List<String> channels;

  /// Visits whose time has come.
  final int visits;

  /// What the customer paid, or the price list where nothing was recorded, plus orders.
  final int spendSom;

  /// The average of the customer's ratings after visits; null when none.
  final double? rating;
  final String note;
  final List<String> tags;
  final Booking? upcoming;
  final List<Booking> bookings;
  final List<Order> orders;

  CustomerCard withNote(String note, List<String> tags) => CustomerCard(
      key: key,
      name: name,
      phone: phone,
      channels: channels,
      visits: visits,
      spendSom: spendSom,
      rating: rating,
      note: note,
      tags: tags,
      upcoming: upcoming,
      bookings: bookings,
      orders: orders);

  @override
  List<Object?> get props =>
      [key, name, phone, channels, visits, spendSom, rating, note, tags, upcoming, bookings, orders];
}

/// A chat in the list (GET /api/mobile/conversations): who, where, the last message.
class ChatSummary extends Equatable {
  const ChatSummary({
    required this.id,
    required this.channel,
    required this.customerName,
    required this.customerPhone,
    required this.lastAt,
    required this.lastRole,
    required this.lastText,
    required this.aiPaused,
    required this.blocked,
  });

  factory ChatSummary.fromJson(Map<String, dynamic> json) {
    final customer = (json['customer'] as Map?) ?? const {};
    final last = json['last'] as Map?;
    return ChatSummary(
      id: json['id'] as int,
      channel: (json['channel'] as String?) ?? '',
      customerName: (customer['name'] as String?) ?? '',
      customerPhone: (customer['phone'] as String?) ?? '',
      lastAt: DateTime.parse(json['last_message_at'] as String).toLocal(),
      lastRole: (last?['role'] as String?) ?? '',
      lastText: (last?['text'] as String?) ?? '',
      aiPaused: (json['ai_paused'] as bool?) ?? false,
      blocked: (json['blocked'] as bool?) ?? false,
    );
  }

  final int id;
  final String channel;
  final String customerName;
  final String customerPhone;
  final DateTime lastAt;

  /// customer | ai | staff; empty for a chat without messages.
  final String lastRole;
  final String lastText;
  final bool aiPaused;
  final bool blocked;

  @override
  List<Object?> get props => [id, channel, customerName, customerPhone, lastAt, lastRole, lastText, aiPaused, blocked];
}

/// What the AI did lately (GET /api/mobile/ai-results): figures by key, only those the niche has, in server order.
class AiResults extends Equatable {
  const AiResults({required this.days, required this.figures});

  factory AiResults.fromJson(Map<String, dynamic> json) => AiResults(
        days: json['days'] as int,
        figures: {for (final e in (json['figures'] as Map).entries) e.key as String: e.value as int},
      );

  final int days;
  final Map<String, int> figures;

  @override
  List<Object?> get props => [days, figures];
}

/// One time in the day's schedule (GET /api/mobile/schedule).
class ScheduleSlot extends Equatable {
  const ScheduleSlot({
    required this.id,
    required this.start,
    required this.state,
    required this.seats,
    required this.taken,
    required this.customer,
  });

  factory ScheduleSlot.fromJson(Map<String, dynamic> json) => ScheduleSlot(
        id: json['id'] as int,
        start: DateTime.parse(json['start_local'] as String),
        state: json['state'] as String,
        seats: (json['seats'] as int?) ?? 1,
        taken: (json['taken'] as int?) ?? 0,
        customer: (json['customer'] as String?) ?? '',
      );

  final int id;
  final DateTime start;

  /// free | closed (staff closed it: the AI does not book it) | busy (marked so, without a booking) | booked
  final String state;
  final int seats;
  final int taken;
  final String customer;

  bool get isGroup => seats > 1;

  @override
  List<Object?> get props => [id, start, state, seats, taken, customer];
}

/// A person's times on the chosen day.
class SchedulePerson extends Equatable {
  const SchedulePerson({required this.id, required this.name, required this.fromAltegio, required this.slots});

  factory SchedulePerson.fromJson(Map<String, dynamic> json) => SchedulePerson(
        id: json['id'] as int,
        name: json['name'] as String,
        fromAltegio: (json['from_altegio'] as bool?) ?? false,
        slots: [for (final x in (json['slots'] as List? ?? const [])) ScheduleSlot.fromJson(x as Map<String, dynamic>)],
      );

  final int id;
  final String name;

  /// The schedule comes from Altegio and is changed there.
  final bool fromAltegio;
  final List<ScheduleSlot> slots;

  @override
  List<Object?> get props => [id, name, fromAltegio, slots];
}

/// What closing or opening changed; [bookings] are those left in closed times, to move or cancel.
class ScheduleChange {
  const ScheduleChange({required this.changed, required this.offered, required this.bookings});

  factory ScheduleChange.fromJson(Map<String, dynamic> json) => ScheduleChange(
        changed: (json['changed'] as int?) ?? 0,
        offered: (json['offered'] as int?) ?? 0,
        bookings: [
          for (final b in (json['bookings'] as List? ?? const [])) Booking.fromJson(b as Map<String, dynamic>)
        ],
      );

  final int changed;
  final int offered;
  final List<Booking> bookings;
}

/// A customer in the list (GET /api/mobile/customers).
class CustomerRow extends Equatable {
  const CustomerRow({
    required this.key,
    required this.name,
    required this.phone,
    required this.channels,
    required this.visits,
    required this.spendSom,
    required this.lastVisit,
    required this.tags,
  });

  factory CustomerRow.fromJson(Map<String, dynamic> json) => CustomerRow(
        key: json['key'] as String,
        name: (json['name'] as String?) ?? '',
        phone: (json['phone'] as String?) ?? '',
        channels: [for (final c in (json['channels'] as List? ?? const [])) c as String],
        visits: (json['visits'] as int?) ?? 0,
        spendSom: (json['spend_som'] as int?) ?? 0,
        lastVisit: json['last_visit_local'] == null ? null : DateTime.parse(json['last_visit_local'] as String),
        tags: [for (final t in (json['tags'] as List? ?? const [])) t as String],
      );

  final String key;
  final String name;
  final String phone;
  final List<String> channels;
  final int visits;
  final int spendSom;
  final DateTime? lastVisit;
  final List<String> tags;

  @override
  List<Object?> get props => [key, name, phone, channels, visits, spendSom, lastVisit, tags];
}


/// One step of the panel's launch checklist («Запуск»), as /api/mobile/setup gives it.
class SetupStep extends Equatable {
  const SetupStep({required this.key, required this.done, required this.title, required this.hint, this.panel = ''});

  factory SetupStep.fromJson(Map<String, dynamic> json) => SetupStep(
        key: json['key'] as String,
        done: json['done'] as bool,
        title: json['title'] as String,
        hint: (json['hint'] as String?) ?? '',
        panel: (json['panel'] as String?) ?? '',
      );

  final String key;
  final bool done;
  final String title;
  final String hint;

  /// The panel's page for this step, for steps the app does not take itself.
  final String panel;

  @override
  List<Object?> get props => [key, done, title, hint, panel];
}

/// The owner's launch checklist, with the two steps the app takes: the Telegram bot and booking by link.
class SetupInfo extends Equatable {
  const SetupInfo({
    required this.steps,
    required this.botConnected,
    this.botUsername = '',
    this.pageAvailable = false,
    this.pageOn = false,
    this.pageWorks = false,
    this.pageWhy = '',
    this.pageUrl = '',
    this.pageQr = const [],
    this.notes = const [],
    this.onlineLabel = '',
    this.onlineOn = false,
    this.onlineTables = false,
    this.onlineUrl = '',
    this.onlineQr = const [],
  });

  factory SetupInfo.fromJson(Map<String, dynamic> json) {
    final telegram = (json['telegram'] as Map?) ?? const {};
    final page = (json['page_booking'] as Map?) ?? const {};
    final online = (json['online'] as Map?) ?? const {};
    return SetupInfo(
      steps: [for (final s in (json['steps'] as List? ?? const [])) SetupStep.fromJson(s as Map<String, dynamic>)],
      botConnected: (telegram['connected'] as bool?) ?? false,
      botUsername: (telegram['username'] as String?) ?? '',
      pageAvailable: (page['available'] as bool?) ?? false,
      pageOn: (page['on'] as bool?) ?? false,
      pageWorks: (page['works'] as bool?) ?? false,
      pageWhy: (page['why'] as String?) ?? '',
      pageUrl: (page['url'] as String?) ?? '',
      pageQr: [for (final r in (page['qr'] as List? ?? const [])) r as String],
      notes: [for (final n in (json['notes'] as List? ?? const [])) ((n as Map)['text'] as String, n['ok'] == true)],
      onlineLabel: (online['label'] as String?) ?? '',
      onlineOn: (online['on'] as bool?) ?? false,
      onlineTables: (online['tables'] as bool?) ?? false,
      onlineUrl: (online['url'] as String?) ?? '',
      onlineQr: [for (final r in (online['qr'] as List? ?? const [])) r as String],
    );
  }

  final List<SetupStep> steps;
  final bool botConnected;
  final String botUsername;
  final bool pageAvailable;
  final bool pageOn;

  /// On and taking bookings now (an open page, a working subscription).
  final bool pageWorks;

  /// Why not: page | niche | altegio | off | unpaid (joop/page_booking.py unavailable).
  final String pageWhy;
  final String pageUrl;

  /// The page's QR code: one string of 0/1 a row, without the quiet zone (the app draws it).
  final List<String> pageQr;

  /// The public page (prices, contacts, buttons into the chats; a cafe's QR menu): its name as the panel says it,
  /// whether it is open, whether guests order from it by table, its address and QR code.
  final String onlineLabel;
  final bool onlineOn;
  final bool onlineTables;
  final String onlineUrl;
  final List<String> onlineQr;

  /// What the server said about the last change, (text, good news).
  final List<(String, bool)> notes;

  int get done => steps.where((s) => s.done).length;

  @override
  List<Object?> get props => [steps, botConnected, botUsername, pageAvailable, pageOn, pageWorks, pageWhy, pageUrl, pageQr, notes, onlineLabel, onlineOn, onlineTables, onlineUrl, onlineQr];
}


/// The business's contacts and opening hours, as /api/mobile/contacts gives them. `example`: fields still the
/// sign-up example's (address, phone, hours_text), which customers are not told.
class ContactsInfo extends Equatable {
  const ContactsInfo({
    this.address = '',
    this.phone = '',
    this.hoursText = '',
    this.workStart = '09:00',
    this.workEnd = '18:00',
    this.daysOff = const {},
    this.example = const {},
  });

  factory ContactsInfo.fromJson(Map<String, dynamic> json) => ContactsInfo(
        address: (json['address'] as String?) ?? '',
        phone: (json['phone'] as String?) ?? '',
        hoursText: (json['hours_text'] as String?) ?? '',
        workStart: (json['work_start'] as String?) ?? '09:00',
        workEnd: (json['work_end'] as String?) ?? '18:00',
        daysOff: {for (final d in (json['days_off'] as List? ?? const [])) d as int},
        example: {for (final f in (json['example'] as List? ?? const [])) f as String},
      );

  final String address;
  final String phone;
  final String hoursText;

  /// When bookable times start and end, HH:MM.
  final String workStart;
  final String workEnd;

  /// ISO weekdays: 1 = Monday ... 7 = Sunday.
  final Set<int> daysOff;
  final Set<String> example;

  Map<String, dynamic> toJson() => {
        'address': address,
        'phone': phone,
        'hours_text': hoursText,
        'work_start': workStart,
        'work_end': workEnd,
        'days_off': (daysOff.toList()..sort()),
      };

  @override
  List<Object?> get props => [address, phone, hoursText, workStart, workEnd, daysOff, example];
}


/// One of the business's people (or tables, groups), as /api/mobile/staff gives them.
class Person extends Equatable {
  const Person({required this.id, required this.name, this.role = '', this.handles = '', this.capacity = 0,
      this.groupSize = 0, this.example = false, this.free = 0});

  factory Person.fromJson(Map<String, dynamic> json) => Person(
        id: json['id'] as int,
        name: json['name'] as String,
        role: (json['role'] as String?) ?? '',
        handles: (json['handles'] as String?) ?? '',
        capacity: (json['capacity'] as int?) ?? 0,
        groupSize: (json['group_size'] as int?) ?? 0,
        example: (json['example'] as bool?) ?? false,
        free: (json['free'] as int?) ?? 0,
      );

  final int id;
  final String name;
  final String role;

  /// What this person takes: the AI picks whom to book by it.
  final String handles;

  /// Seats of a table or hall (party-size niches), 0 = not relevant.
  final int capacity;

  /// Places in a group class, 0 = one booking a time.
  final int groupSize;

  /// Still the sign-up example: customers are not booked to them.
  final bool example;

  /// Free times ahead: 0 means the AI cannot book anyone to this person.
  final int free;

  Map<String, dynamic> toJson() =>
      {'name': name, 'role': role, 'handles': handles, 'capacity': capacity, 'group_size': groupSize};

  @override
  List<Object?> get props => [id, name, role, handles, capacity, groupSize, example, free];
}

/// The people screen: its title and item word by niche, which numbers it asks for, and the list.
class PeopleInfo extends Equatable {
  const PeopleInfo({required this.label, required this.item, required this.people, this.capacity = false,
      this.group = false, this.booking = false, this.workStart = '09:00', this.workEnd = '18:00'});

  factory PeopleInfo.fromJson(Map<String, dynamic> json) => PeopleInfo(
        label: json['label'] as String,
        item: (json['item'] as String?) ?? '',
        capacity: (json['capacity'] as bool?) ?? false,
        group: (json['group'] as bool?) ?? false,
        booking: (json['booking'] as bool?) ?? false,
        workStart: (json['work_start'] as String?) ?? '09:00',
        workEnd: (json['work_end'] as String?) ?? '18:00',
        people: [for (final p in (json['staff'] as List? ?? const [])) Person.fromJson(p as Map<String, dynamic>)],
      );

  final String label;
  final String item;
  final bool capacity;
  final bool group;

  /// Customers book these people's time (not just ask for them by name).
  final bool booking;

  /// The business's hours: the default for opening free times.
  final String workStart;
  final String workEnd;
  final List<Person> people;

  @override
  List<Object?> get props => [label, item, capacity, group, booking, workStart, workEnd, people];
}
