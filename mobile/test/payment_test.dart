import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  testWidgets('after a visit the owner records the payment and sees it in today\'s takings', (tester) async {
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

    expect(find.text('Касса сегодня'), findsOneWidget);
    expect(find.text('0 сом'), findsOneWidget);
    expect(find.text('Прошли без оплаты: 1'), findsOneWidget); // the 10:00 visit

    await tester.tap(find.text('Записи').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Оплата').first);
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, '1500'), findsOneWidget); // pre-filled from the price list

    await tester.enterText(find.byKey(const Key('pay-amount')), '1800');
    await tester.tap(find.text('Карта'));
    await tester.pump();
    await tester.tap(find.byKey(const Key('pay-save')));
    await tester.pumpAndSettle();
    expect(server.calls, contains('POST /api/mobile/bookings/1/pay'));
    expect(find.text('Оплата записана'), findsOneWidget);
    expect(find.text('1 800 сом · карта'), findsOneWidget);

    await tester.tap(find.text('Сегодня').last);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('cash-today')), findsOneWidget);
    expect(find.text('1 800 сом'), findsOneWidget);
    expect(find.textContaining('Прошли без оплаты'), findsNothing);

    // A payment recorded by mistake is removed.
    await tester.tap(find.text('Записи').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Оплата').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Удалить оплату'));
    await tester.pumpAndSettle();
    expect(find.text('Оплата удалена'), findsOneWidget);
    expect(find.text('1 800 сом · карта'), findsNothing);
  });

  testWidgets('a payment needs an amount', (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final server = FakeJoop();
    server.bookings.first['suggested_som'] = 0; // a service without a price in the list
    await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'aktish');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Записи').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Оплата').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('pay-save')));
    await tester.pump();
    expect(find.text('Введите сумму'), findsOneWidget);
    expect(server.calls, isNot(contains('POST /api/mobile/bookings/1/pay')));
  });
}
