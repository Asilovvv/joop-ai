import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  Future<FakeJoop> signIn(WidgetTester tester, [FakeJoop? prepared]) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final server = prepared ?? FakeJoop();
    await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'aktish');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Записи').last);
    await tester.pumpAndSettle();
    return server;
  }

  Map<String, dynamic> slot(FakeJoop server, int id) =>
      server.schedule.expand((p) => p['slots'] as List).firstWhere((x) => x['id'] == id) as Map<String, dynamic>;

  testWidgets('a doctor is ill: the owner closes her day, sees whom to move, and opens it later', (tester) async {
    final server = await signIn(tester);
    await tester.tap(find.byKey(const Key('app-menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('menu-schedule')));
    await tester.pumpAndSettle();
    expect(find.text('12:00 · Айгуль'), findsOneWidget);
    expect(find.text('14:00 · занято'), findsOneWidget);

    await tester.tap(find.byKey(const Key('slot-42'))); // one free time
    await tester.pumpAndSettle();
    expect(server.calls, contains('POST /api/mobile/schedule/slots/42'));
    expect(slot(server, 42)['state'], 'closed');
    expect(find.text('Закрыто времени: 1. ИИ не будет на него записывать.'), findsOneWidget);
    expect(find.text('13:00 · закрыто'), findsOneWidget);

    await tester.tap(find.byKey(const Key('close-day-1')));
    await tester.pumpAndSettle();
    expect(find.text('Остались записи'), findsOneWidget); // the patients to move: they do not know yet
    expect(find.textContaining('10:00 — Айгуль'), findsOneWidget);
    await tester.tap(find.text('Понятно'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('close-day-1')), findsNothing);

    await tester.tap(find.byKey(const Key('open-day-1')));
    await tester.pumpAndSettle();
    expect(find.text('Открыто времени: 3. Предложено клиентам из листа ожидания: 2.'), findsOneWidget);
    expect(slot(server, 41)['state'], 'booked');
    expect(slot(server, 42)['state'], 'free');
  });

  testWidgets('an Altegio schedule is changed in Altegio', (tester) async {
    await signIn(tester);
    await tester.tap(find.byKey(const Key('app-menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('menu-schedule')));
    await tester.pumpAndSettle();
    expect(find.text('Расписание из Altegio — меняйте его там.'), findsOneWidget);
    expect(find.byKey(const Key('close-day-2')), findsNothing);
    expect(tester.widget<ActionChip>(find.byKey(const Key('slot-51'))).onPressed, isNull);
  });

  testWidgets('a master has no «Окна»', (tester) async {
    await signIn(tester, FakeJoop()..role = 'master');
    await tester.tap(find.byKey(const Key('app-menu')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('menu-schedule')), findsNothing);
    expect(find.byKey(const Key('menu-customers')), findsOneWidget); // her own customers, as in the panel
  });
}
