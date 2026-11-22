import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

Future<FakeJoop> _prices(WidgetTester tester, {String role = 'owner'}) async {
  SharedPreferences.setMockInitialValues({});
  tester.view.physicalSize = const Size(1080, 2340);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  final server = FakeJoop()..role = role;
  await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('company')), 'aktish');
  await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
  await tester.tap(find.byKey(const Key('login')));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Прайс').last);
  await tester.pumpAndSettle();
  return server;
}

void main() {
  testWidgets('the owner replaces the example with own prices from the phone', (tester) async {
    final server = await _prices(tester);
    expect(find.byKey(const Key('example-banner')), findsOneWidget);

    // an example row edited becomes the owner's own
    await tester.tap(find.byKey(const Key('service-2')));
    await tester.pumpAndSettle();
    expect(find.text('Позиция прайса'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('service-name')), 'Отбеливание Zoom');
    await tester.enterText(find.byKey(const Key('service-price')), '9500');
    await tester.enterText(find.byKey(const Key('service-note')), 'Около часа');
    await tester.tap(find.byKey(const Key('service-save')));
    await tester.pumpAndSettle();
    expect(server.services[1], containsPair('name', 'Отбеливание Zoom'));
    expect(server.services[1], containsPair('note', 'Около часа'));
    expect(find.text('Отбеливание Zoom'), findsOneWidget);
    expect(find.byKey(const Key('example-banner')), findsNothing); // no example rows left

    // a new row; an empty name is not sent
    await tester.tap(find.byKey(const Key('service-add')));
    await tester.pumpAndSettle();
    expect(find.text('Новая позиция'), findsOneWidget);
    await tester.tap(find.byKey(const Key('service-save')));
    await tester.pumpAndSettle();
    expect(find.text('Напишите название.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('service-name')), 'Чистка');
    await tester.enterText(find.byKey(const Key('service-price')), '2500');
    await tester.tap(find.byKey(const Key('service-save')));
    await tester.pumpAndSettle();
    expect(server.services.last, containsPair('name', 'Чистка'));
    expect(find.text('2500 сом'), findsOneWidget);

    // and deleted again
    await tester.tap(find.text('Чистка'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('service-delete')));
    await tester.pumpAndSettle();
    expect(find.text('Чистка'), findsNothing);
    expect(server.services.map((x) => x['name']), isNot(contains('Чистка')));
  });

  testWidgets('the whole example goes in one tap, after a yes', (tester) async {
    final server = await _prices(tester);
    await tester.tap(find.byKey(const Key('example-delete')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Ваши собственные позиции останутся'), findsOneWidget);
    await tester.tap(find.byKey(const Key('example-delete-yes')));
    await tester.pumpAndSettle();
    expect(find.text('Пример удалён: 1. Добавьте свои позиции с ценами.'), findsOneWidget);
    expect(server.services.map((x) => x['name']), ['Консультация', 'Зубная щётка']);
    expect(find.byKey(const Key('example-banner')), findsNothing);
  });

  testWidgets('a master reads the price list but does not edit it', (tester) async {
    await _prices(tester, role: 'master');
    expect(find.byKey(const Key('service-add')), findsNothing);
    expect(find.byKey(const Key('example-banner')), findsNothing);
    await tester.tap(find.text('Консультация'));
    await tester.pumpAndSettle();
    expect(find.text('Позиция прайса'), findsNothing);
  });
}
