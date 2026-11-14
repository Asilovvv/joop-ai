import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/core/format.dart';
import 'package:joop_mobile/core/strings.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

Future<void> _open(WidgetTester tester, FakeJoop server) async {
  tester.view.physicalSize = const Size(1080, 2340);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
  await tester.pumpAndSettle();
}

Future<void> _choose(WidgetTester tester, String language) async {
  await tester.tap(find.byKey(const Key('language')).first);
  await tester.pumpAndSettle();
  await tester.tap(find.text(language).last);
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    S.current = S.ru;
  });
  tearDown(() => S.current = S.ru);

  test('dates, counts and order words in both languages', () {
    final friday = DateTime(2026, 11, 13);
    expect(formatDay(friday), 'пт, 13 ноя');
    expect(bookingsWord(2), '2 записи');
    expect(S.ru.orderStatus('sent', delivery: false), 'Готов к выдаче');
    expect(S.ru.orderAction('cancelled', delivery: true), 'Отменить');

    S.current = S.ky;
    expect(formatDay(friday), 'жм, 13-ноябрь');
    expect(bookingsWord(2), '2 жазылуу');
    expect(S.ky.orderStatus('sent', delivery: true), 'Жолдо');
    expect(S.ky.orderAction('accepted', delivery: true), 'Кабыл алуу');
    expect(S.ky.leadKinds.keys, S.ru.leadKinds.keys);
    expect(S.ky.orderStatuses.keys, S.ru.orderStatuses.keys);
  });

  testWidgets('the language switches every screen and is remembered', (tester) async {
    final server = FakeJoop(cafe: true);
    await _open(tester, server);
    expect(find.text('Войти'), findsOneWidget);

    await _choose(tester, 'Кыргызча');
    expect(find.text('Кирүү'), findsOneWidget);
    expect(find.text('Мен кардармын: жазылуу'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('company')), 'navat');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    expect(find.text('Буйрутмалар'), findsWidgets);
    expect(find.widgetWithText(FilledButton, 'Кабыл алуу'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Кабыл алуу'));
    await tester.pumpAndSettle();
    expect(find.text('№41 буйрутма: Кабыл алынды. Кардарга билдирүү жөнөтүлдү.'), findsOneWidget);

    // A new launch starts in Kyrgyz and still signed in.
    await tester.pumpWidget(const SizedBox());
    S.current = S.ru;
    await _open(tester, server);
    expect(find.text('Өтүнмө'), findsOneWidget); // the short tab name

    await _choose(tester, 'Русский');
    expect(find.text('Заявки'), findsWidgets);
  });

  testWidgets('a customer writing in Kyrgyz gets the chat in Kyrgyz', (tester) async {
    final server = FakeJoop();
    await _open(tester, server);
    await _choose(tester, 'Кыргызча');
    await tester.tap(find.byKey(const Key('customer')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('place-code')), 'aktish');
    await tester.tap(find.byKey(const Key('place-open')));
    await tester.pumpAndSettle();
    expect(find.text('Баалар жана байланыш'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('chat-input')), 'Консультация канча турат?');
    await tester.tap(find.byKey(const Key('chat-send')));
    await tester.pumpAndSettle();
    expect(server.chat.single['lang'], 'ky'); // Joop's web chat answers its own messages in Kyrgyz
  });
}
