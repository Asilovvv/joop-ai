import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  testWidgets('a booking opens the customer card; staff keep a note and tags on it', (tester) async {
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
    await tester.tap(find.text('Записи').last);
    await tester.pumpAndSettle();

    final first = server.bookings.first['customer']['name'] as String;
    await tester.tap(find.text(first).first);
    await tester.pumpAndSettle();
    expect(server.calls, contains('GET /api/mobile/customers/700000001'));
    expect(find.text('4 500 сом'), findsOneWidget);
    expect(find.text('4.7 ★'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('customer-note')), 'Боится уколов');
    await tester.enterText(find.byKey(const Key('customer-tags')), 'VIP, постоянный');
    await tester.ensureVisible(find.byKey(const Key('customer-save')));
    await tester.tap(find.byKey(const Key('customer-save')));
    await tester.pumpAndSettle();
    expect(find.text('Заметка сохранена'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('№77 · Выполнен'), 300, scrollable: find.byType(Scrollable).last);
    expect(find.text('Зубная паста × 2'), findsOneWidget);
    expect(server.notes['700000001'], {'note': 'Боится уколов', 'tags': ['VIP', 'постоянный']});
  });
}
