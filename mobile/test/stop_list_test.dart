import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  testWidgets('the owner takes an item off sale and back; a sold-out one waits for the stock', (tester) async {
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
    await tester.tap(find.text('Прайс').last);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('available-1')));
    await tester.pumpAndSettle();
    expect(server.calls, contains('POST /api/mobile/services/1/available'));
    expect(server.services.first['available'], isFalse);
    expect(find.text('500 сом · Стоп-лист: ИИ не предлагает'), findsOneWidget);

    expect(find.textContaining('от 8 000 сом · из примера — клиентам не называется'), findsOneWidget);
    await tester.tap(find.byKey(const Key('available-2')));
    await tester.pumpAndSettle();
    expect(server.services[1]['available'], isTrue);

    expect(find.text('300 сом · Закончилось на складе'), findsOneWidget);
    expect(tester.widget<Switch>(find.byKey(const Key('available-3'))).onChanged, isNull);
  });
}
