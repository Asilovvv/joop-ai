import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

Future<FakeJoop> _signIn(WidgetTester tester) async {
  SharedPreferences.setMockInitialValues({});
  tester.view.physicalSize = const Size(1080, 4200); // the test font is wider than a phone's
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  final server = FakeJoop(hotel: true);
  await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('company')), 'uyut');
  await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
  await tester.tap(find.byKey(const Key('login')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('app-menu')));
  await tester.pumpAndSettle();
  return server;
}

void main() {
  testWidgets('a hotel swaps the example rooms for its own from the phone', (tester) async {
    final server = await _signIn(tester);
    await tester.tap(find.byKey(const Key('menu-setup')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-people'))); // the launch list's «Номера» step opens the screen
    await tester.pumpAndSettle();
    expect(find.textContaining('настоящим клиентам ИИ его не предлагает и не бронирует'), findsOneWidget);
    expect(find.text('номер на двоих · номеров: 6 · мест: 2'), findsOneWidget);
    expect(find.byKey(const Key('windows-1')), findsNothing); // rooms have no times to open

    await tester.tap(find.byKey(const Key('people-example-delete')));
    await tester.pumpAndSettle();
    expect(find.text('Удалить весь пример? Ваши строки и брони останутся.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('people-example-yes')));
    await tester.pumpAndSettle();
    expect(server.people, isEmpty);

    await tester.tap(find.byKey(const Key('person-add')));
    await tester.pumpAndSettle();
    expect(find.text('Название'), findsOneWidget);
    expect(find.byKey(const Key('person-handles')), findsNothing);
    expect(find.text('Номеров этого типа'), findsOneWidget);
    expect(find.text('Гостей в номере'), findsOneWidget);
    expect(tester.widget<TextField>(find.byKey(const Key('person-units'))).controller!.text, '1');
    await tester.enterText(find.byKey(const Key('person-name')), 'Стандарт');
    await tester.enterText(find.byKey(const Key('person-role')), 'номер на двоих');
    await tester.enterText(find.byKey(const Key('person-units')), '5');
    await tester.enterText(find.byKey(const Key('person-capacity')), '2');
    await tester.tap(find.byKey(const Key('person-save')));
    await tester.pumpAndSettle();
    expect(server.people.single, allOf(containsPair('name', 'Стандарт'), containsPair('group_size', 5), containsPair('capacity', 2)));
    expect(find.text('номер на двоих · номеров: 5 · мест: 2'), findsOneWidget);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('step-rooms-done')), findsOneWidget);
  });
}
