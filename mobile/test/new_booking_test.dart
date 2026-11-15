import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  Future<FakeJoop> signIn(WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final server = FakeJoop();
    await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'aktish');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    return server;
  }

  testWidgets('a customer phoned: the owner books them into a free time and sees them in the day', (tester) async {
    final server = await signIn(tester);
    await tester.tap(find.byKey(const Key('new-booking')));
    await tester.pumpAndSettle();
    expect(find.text('Др. Асанова'), findsOneWidget);
    expect(find.text('Др. Бекова'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const Key('new-booking-save'))).onPressed, isNull); // no time yet

    await tester.tap(find.byKey(const Key('slot-32')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('new-booking-save')));
    await tester.pump();
    expect(find.text('Укажите имя клиента'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('new-booking-name')), 'Динара');
    await tester.enterText(find.byKey(const Key('new-booking-phone')), '0555 123 456');
    await tester.enterText(find.byKey(const Key('new-booking-service')), 'Консультация');
    await tester.tap(find.byKey(const Key('new-booking-save')));
    await tester.pumpAndSettle();

    expect(server.calls, contains('POST /api/mobile/bookings'));
    expect(find.text('Записали: Динара, пт, 13 ноя, 17:00'), findsOneWidget);
    expect(find.text('Динара'), findsOneWidget); // the bookings tab shows the day with her
    expect(find.text('Вручную'), findsWidgets);
  });

  testWidgets('a time taken meanwhile says so and shows the times left', (tester) async {
    final server = await signIn(tester);
    await tester.tap(find.byKey(const Key('new-booking')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('slot-31')));
    server.freeSlots.removeWhere((x) => x['id'] == 31); // the AI booked it a second ago
    await tester.enterText(find.byKey(const Key('new-booking-name')), 'Динара');
    await tester.tap(find.byKey(const Key('new-booking-save')));
    await tester.pumpAndSettle();
    expect(find.text('Это время уже занято. Выберите другое.'), findsOneWidget);
    expect(find.byKey(const Key('slot-31')), findsNothing);
    expect(find.byKey(const Key('slot-32')), findsOneWidget);
    expect(find.text('Динара'), findsOneWidget); // the typed name stays
  });

  testWidgets('a day without free times says so', (tester) async {
    await signIn(tester);
    await tester.tap(find.byKey(const Key('new-booking')));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Следующий день'));
    await tester.pumpAndSettle();
    expect(find.text('На этот день свободного времени нет'), findsOneWidget);
  });

  testWidgets('a booking moves to another free time and the customer is told', (tester) async {
    final server = await signIn(tester);
    await tester.tap(find.text('Записи').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('booking-menu-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Перенести'));
    await tester.pumpAndSettle();
    expect(find.text('Перенести запись'), findsOneWidget);
    expect(find.byKey(const Key('new-booking-name')), findsNothing); // the customer is already known
    expect(find.textContaining('Сейчас: Айгуль'), findsOneWidget);
    await tester.tap(find.byKey(const Key('slot-32')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('new-booking-save')));
    await tester.pumpAndSettle();
    expect(server.calls, contains('POST /api/mobile/bookings/1/move'));
    expect(find.text('Перенесли на пт, 13 ноя, 17:00. Клиенту написали в чат.'), findsOneWidget);
    expect(server.bookings.first['start_local'], '2026-11-13T17:00:00');
  });
}
