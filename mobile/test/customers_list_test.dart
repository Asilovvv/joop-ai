import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  testWidgets('the owner finds a customer by name or tag and opens the card', (tester) async {
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

    await tester.tap(find.byKey(const Key('app-menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Клиенты'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('customer-700000001')), findsOneWidget);
    expect(find.byKey(const Key('customer-555123456')), findsOneWidget);
    expect(find.textContaining('визитов: 3 · 4 500 сом'), findsOneWidget);
    expect(find.textContaining('+996 700 000 001'), findsOneWidget); // readable, as in the panel (#252)
    expect(find.textContaining('+996700000001'), findsNothing);

    await tester.enterText(find.byKey(const Key('customers-search')), 'бакыт');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('customer-700000001')), findsNothing);
    expect(find.byKey(const Key('customer-555123456')), findsOneWidget);

    await tester.enterText(find.byKey(const Key('customers-search')), '');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('tag-VIP')));
    await tester.pumpAndSettle();
    expect(server.calls.last, 'GET /api/mobile/customers');
    expect(find.byKey(const Key('customer-555123456')), findsNothing);

    await tester.tap(find.byKey(const Key('customer-700000001')));
    await tester.pumpAndSettle();
    expect(server.calls, contains('GET /api/mobile/customers/700000001'));
    expect(find.text('4.7 ★'), findsOneWidget);
    expect(find.textContaining('+996 700 000 001'), findsWidgets);
  });
}
