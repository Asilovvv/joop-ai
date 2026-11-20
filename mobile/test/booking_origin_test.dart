import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/core/strings.dart';
import 'package:joop_mobile/data/models.dart';
import 'package:joop_mobile/ui/booking_tile.dart';

Booking _booking({String channel = '', String source = 'staff'}) => Booking.fromJson({
      'id': 5,
      'start_local': '2026-11-18T10:00:00',
      'service': 'Консультация',
      'staff': 'Айгерим',
      'customer': {'name': 'Айгуль', 'phone': ''},
      'channel': channel,
      'status': 'booked',
      'source': source,
      'confirmed': false,
      'paid': null,
    });

Future<void> _show(WidgetTester tester, Booking b) =>
    tester.pumpWidget(MaterialApp(home: Scaffold(body: BookingTile(booking: b))));

void main() {
  setUp(() => S.current = S.ru);

  test('the app reads where a booking came from', () {
    expect(_booking(source: 'api').source, 'api');
    expect(_booking(channel: 'telegram', source: 'ai').source, 'ai');
  });

  testWidgets('a booking from a partner system or another assistant is «через API», not «Вручную»', (tester) async {
    await _show(tester, _booking(source: 'api'));
    expect(find.text('через API'), findsOneWidget);
    expect(find.text('Вручную'), findsNothing);
  });

  testWidgets('a booking staff made by hand is still «Вручную»; the AI\'s keeps its channel', (tester) async {
    await _show(tester, _booking());
    expect(find.text('Вручную'), findsOneWidget);
    await _show(tester, _booking(channel: 'telegram', source: 'ai'));
    expect(find.text('Telegram'), findsOneWidget);
  });

  testWidgets('a booking the customer made on the booking page is «со страницы записи», not «Вручную»', (tester) async {
    await _show(tester, _booking(source: 'page'));
    expect(find.text('со страницы записи'), findsOneWidget);
    expect(find.text('Вручную'), findsNothing);
  });

  testWidgets('in Kyrgyz too', (tester) async {
    S.current = S.ky;
    await _show(tester, _booking(source: 'api'));
    expect(find.text('API аркылуу'), findsOneWidget);
    await _show(tester, _booking(source: 'page'));
    expect(find.text('жазылуу барагынан'), findsOneWidget);
  });
}
