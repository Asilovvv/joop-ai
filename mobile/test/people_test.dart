import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

Future<FakeJoop> _people(WidgetTester tester, {String role = 'owner'}) async {
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
  await tester.tap(find.byKey(const Key('app-menu')));
  await tester.pumpAndSettle();
  return server;
}

void main() {
  testWidgets('the owner swaps the example for own people from the phone', (tester) async {
    final server = await _people(tester);
    await tester.tap(find.byKey(const Key('menu-people')));
    await tester.pumpAndSettle();
    expect(find.text('Врачи'), findsOneWidget);
    expect(find.byKey(const Key('people-example-banner')), findsOneWidget);
    expect(find.text('пример'), findsOneWidget);

    // the example removed after a yes
    await tester.tap(find.byKey(const Key('people-example-delete')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Ваши люди и записи останутся'), findsOneWidget);
    await tester.tap(find.byKey(const Key('people-example-yes')));
    await tester.pumpAndSettle();
    expect(find.text('Пример удалён: 1, с их свободными окнами. Добавьте своих.'), findsOneWidget);
    expect(find.byKey(const Key('people-example-banner')), findsNothing);
    expect(server.people.map((x) => x['name']), ['Айгерим']);

    // a new one; an empty name is not sent
    await tester.tap(find.byKey(const Key('person-add')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('person-save')));
    await tester.pumpAndSettle();
    expect(find.text('Напишите название.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('person-name')), 'Бакыт Асанов');
    await tester.enterText(find.byKey(const Key('person-handles')), 'удаление, импланты');
    await tester.tap(find.byKey(const Key('person-save')));
    await tester.pumpAndSettle();
    expect(server.people.last, containsPair('handles', 'удаление, импланты'));
    expect(find.text('Бакыт Асанов'), findsOneWidget);
    expect(find.byKey(const Key('person-capacity')), findsNothing); // a clinic: no seats to ask for

    // edited, then retired
    await tester.tap(find.text('Бакыт Асанов'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('person-role')), 'хирург');
    await tester.tap(find.byKey(const Key('person-save')));
    await tester.pumpAndSettle();
    expect(server.people.last, containsPair('role', 'хирург'));
    await tester.tap(find.text('Бакыт Асанов'));
    await tester.pumpAndSettle();
    expect(find.text('Записи к нему останутся, свободные окна удалятся.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('person-delete')));
    await tester.pumpAndSettle();
    expect(find.text('Бакыт Асанов'), findsNothing);
    expect(server.people.map((x) => x['name']), ['Айгерим']);
  });

  testWidgets('a refusal is said on the screen and changes nothing', (tester) async {
    final server = await _people(tester);
    server.refusePeople = 'На бесплатном тарифе один мастер.';
    await tester.tap(find.byKey(const Key('menu-people')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('person-add')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('person-name')), 'Второй');
    await tester.tap(find.byKey(const Key('person-save')));
    await tester.pumpAndSettle();
    expect(find.text('На бесплатном тарифе один мастер.'), findsOneWidget);
    expect(find.text('Второй'), findsNothing);
    expect(server.people, hasLength(2));
  });

  testWidgets('a master has no people screen', (tester) async {
    await _people(tester, role: 'master');
    expect(find.byKey(const Key('menu-people')), findsNothing);
  });
}
