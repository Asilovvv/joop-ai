import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/data/models.dart';

/// Responses recorded from a real Joop server (demo dental clinic), so the app reads what the server really sends.
Map<String, dynamic> fixture(String name) =>
    jsonDecode(File('test/fixtures/$name.json').readAsStringSync()) as Map<String, dynamic>;

void main() {
  test('login', () {
    final a = Account.fromJson(fixture('login'));
    expect(a.businessName, 'Ак-Тиш Дент');
    expect(a.isOwner, isTrue);
  });

  test('bookings, cancelled after the summary was recorded', () {
    final rows = [for (final r in fixture('bookings')['bookings'] as List) Booking.fromJson(r as Map<String, dynamic>)];
    expect(rows.single.customerName, 'Айгуль');
    expect(rows.single.start, DateTime(2026, 11, 14, 9));
    expect(rows.single.isActive, isFalse);
  });

  test('summary and services', () {
    expect(Summary.fromJson(fixture('summary')).week, 0);
    final services = [for (final r in fixture('services')['services'] as List) Service.fromJson(r as Map<String, dynamic>)];
    expect(services.first.price, '500');
    expect(services.length, greaterThan(3));
  });

  test('a WhatsApp dialogue that can no longer be answered', () {
    final d = Dialogue.fromJson(fixture('dialogue'));
    expect(d.customerPhone, '+996700111222');
    expect(d.messages.map((m) => m.role), ['customer', 'ai']);
    expect(d.replyBlocked, contains('WhatsApp'));
  });

  test('free times for a booking made by staff', () {
    final slots = [for (final r in fixture('slots')['slots'] as List) FreeSlot.fromJson(r as Map<String, dynamic>)];
    expect(slots.first.start, DateTime(2026, 11, 16, 9));
    expect(slots.first.staff, 'Айгерим Садыкова');
    expect(slots.first.seats, 1);
  });

  test("a day's takings after a card payment", () {
    final day = CashDay.fromJson(fixture('cash'));
    expect(day.total, 3000);
    expect(day.byMethod, {'card': 3000});
    expect(day.unpaid, isEmpty);
    expect(day.monthTotal, 3000);
  });
}
