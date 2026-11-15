import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  Future<FakeJoop> signIn(WidgetTester tester, FakeJoop server) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'aktish');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    return server;
  }

  testWidgets('a customer sent a receipt: the owner sees it on the home screen and marks the prepayment received',
      (tester) async {
    final server = FakeJoop();
    server.bookings.first['deposit'] = {'due': 500, 'status': 'check', 'deadline': '2026-11-13T03:00:00Z'};
    await signIn(tester, server);
    expect(find.byKey(const Key('deposits-to-check')), findsOneWidget);
    expect(find.text('прислал чек — проверьте 500 сом'), findsWidgets);

    await tester.tap(find.byKey(const Key('booking-menu-1')).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Предоплата получена'));
    await tester.pumpAndSettle();
    expect(server.calls, contains('POST /api/mobile/bookings/1/deposit'));
    expect(find.text('Предоплата отмечена. Клиенту отправлено подтверждение.'), findsOneWidget);
    expect(find.byKey(const Key('deposits-to-check')), findsNothing); // nothing left to check
  });

  testWidgets('a booking waiting for the money shows until when, and its menu marks it received', (tester) async {
    final server = FakeJoop();
    server.bookings.first['deposit'] = {'due': 500, 'status': 'awaiting', 'deadline': '2026-11-13T09:00:00Z'};
    server.bookings.first['channel'] = '';
    await signIn(tester, server);
    expect(find.byKey(const Key('deposits-to-check')), findsNothing); // the customer has not sent anything yet
    await tester.tap(find.text('Записи').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('ждём предоплату 500 сом до'), findsOneWidget);
    await tester.tap(find.byKey(const Key('booking-menu-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Предоплата получена'));
    await tester.pumpAndSettle();
    expect(find.text('Предоплата отмечена. Подтвердите клиенту сами: написать ему из Joop сейчас нельзя.'), findsOneWidget);
    expect(find.text('предоплата 500 сом получена'), findsOneWidget);
    await tester.tap(find.byKey(const Key('booking-menu-1')));
    await tester.pumpAndSettle();
    expect(find.text('Предоплата получена'), findsNothing); // marked once
  });
}
