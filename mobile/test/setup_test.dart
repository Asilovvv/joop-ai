import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

Future<FakeJoop> _signIn(WidgetTester tester, {String role = 'owner'}) async {
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
  testWidgets('the owner connects the Telegram bot and turns on booking by link from the phone', (tester) async {
    final server = await _signIn(tester);
    await tester.tap(find.byKey(const Key('menu-setup')));
    await tester.pumpAndSettle();
    expect(find.text('Готово 1 из 4'), findsOneWidget);
    expect(find.byKey(const Key('step-telegram-todo')), findsOneWidget);
    expect(find.textContaining('https://joop.test/panel/settings'), findsOneWidget); // a step the app does not take

    await tester.enterText(find.byKey(const Key('bot-token')), '123:wrong');
    await tester.tap(find.byKey(const Key('bot-connect')));
    await tester.pumpAndSettle();
    expect(find.text('Telegram не принял токен. Скопируйте его из @BotFather целиком.'), findsOneWidget);
    expect(find.byKey(const Key('step-telegram-todo')), findsOneWidget);

    await tester.enterText(find.byKey(const Key('bot-token')), ' 123456:good-token ');
    await tester.tap(find.byKey(const Key('bot-connect')));
    await tester.pumpAndSettle();
    expect(server.setupCalls.last, {'token': '123456:good-token'});
    expect(find.text('Бот @aktish_bot подключён.'), findsOneWidget);
    expect(find.byKey(const Key('step-telegram-done')), findsOneWidget);
    expect(find.byKey(const Key('bot-token')), findsNothing);
    expect(find.text('Готово 2 из 4'), findsOneWidget);

    await tester.ensureVisible(find.byKey(const Key('page-booking-switch')));
    expect(find.text('https://joop.test/m/aktish/book'), findsOneWidget);
    expect(find.byKey(const Key('page-booking-qr')), findsNothing); // off: nothing to scan yet
    await tester.tap(find.byKey(const Key('page-booking-switch')));
    await tester.pumpAndSettle();
    expect(server.setupCalls.last, {'on': true});
    expect(tester.widget<SwitchListTile>(find.byKey(const Key('page-booking-switch'))).value, isTrue);

    await tester.ensureVisible(find.byKey(const Key('page-booking-qr')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('page-booking-qr')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('qr-full')), findsOneWidget); // shown large, for a customer to scan from the phone
    await tester.tapAt(tester.getCenter(find.byKey(const Key('qr-full'))));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('qr-full')), findsNothing);
  });

  testWidgets('the owner tries the AI in the test chat from the launch checklist', (tester) async {
    final server = await _signIn(tester);
    await tester.tap(find.byKey(const Key('menu-setup')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('step-try-todo')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('open-try')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-try')));
    await tester.pumpAndSettle();
    expect(find.text('Тестовый чат'), findsOneWidget);
    expect(find.textContaining('Эти сообщения нигде не считаются'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('try-input')), 'Сколько стоит консультация?');
    await tester.tap(find.byKey(const Key('try-send')));
    await tester.pumpAndSettle();
    expect(find.text('Сколько стоит консультация?'), findsOneWidget);
    expect(find.text('Консультация стоит 500 сом. Записать вас на завтра в 10:00?'), findsOneWidget);

    await tester.tap(find.byKey(const Key('try-reset')));
    await tester.pumpAndSettle();
    expect(find.text('Сколько стоит консультация?'), findsNothing);
    expect(find.text('Тестовые записи отменены, время снова свободно: 1.'), findsOneWidget);
    expect(server.tryChat, isEmpty);

    server.tryChat.add({'id': 1, 'role': 'customer', 'text': 'Привет', 'created_at': '2026-11-13T07:00:00Z', 'author': ''});
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('step-try-done')), findsOneWidget); // the list is read again on return
  });

  testWidgets('staff do not see the launch checklist', (tester) async {
    await _signIn(tester, role: 'staff');
    expect(find.byKey(const Key('menu-customers')), findsOneWidget);
    expect(find.byKey(const Key('menu-setup')), findsNothing);
  });
}
