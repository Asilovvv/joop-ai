import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  testWidgets('sign in, see today, open bookings and cancel one', (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final server = FakeJoop();
    await tester.pumpWidget(JoopApp(repository: server.repository(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('company')), 'aktish');
    await tester.enterText(find.byKey(const Key('password')), 'wrong');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    expect(find.text('Неверный логин или пароль.'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    expect(find.text('Ак-Тиш Дент'), findsOneWidget);
    expect(find.text('2 записи'), findsOneWidget);
    expect(find.text('Айгуль'), findsOneWidget); // the next visit

    await tester.tap(find.text('Записи').last);
    await tester.pumpAndSettle();
    expect(find.text('пт, 13 ноя'), findsOneWidget);
    expect(find.text('Бакыт'), findsOneWidget);
    expect(find.text('WhatsApp'), findsWidgets);

    await tester.tap(find.byTooltip('Отменить запись').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Отменить запись'));
    await tester.pumpAndSettle();
    expect(find.text('Запись отменена, время снова свободно'), findsOneWidget);
    expect(find.text('Отменена'), findsOneWidget);
    expect(server.calls, contains('POST /api/mobile/bookings/2/cancel'));

    await tester.tap(find.byTooltip('Следующий день'));
    await tester.pumpAndSettle();
    expect(find.text('Нурлан'), findsOneWidget);

    await tester.tap(find.text('Прайс').last);
    await tester.pumpAndSettle();
    expect(find.text('Консультация'), findsOneWidget);
    expect(find.text('Нет в наличии'), findsOneWidget);

    await tester.tap(find.byTooltip('Выйти'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('login')), findsOneWidget);
  });
}
