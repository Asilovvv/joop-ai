import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  testWidgets('a business signs itself up in the app and lands signed in', (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final server = FakeJoop();
    await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('signup')));
    await tester.pumpAndSettle();
    expect(find.text('Новая компания'), findsOneWidget);
    expect(find.textContaining('14 дней бесплатно, без карты'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('signup-name')), 'Салон Айгерим');
    await tester.enterText(find.byKey(const Key('signup-person')), 'Айгерим');
    await tester.enterText(find.byKey(const Key('signup-phone')), '0555 123 456');
    await tester.enterText(find.byKey(const Key('signup-password')), 'short');
    await tester.tap(find.byKey(const Key('signup-submit')));
    await tester.pumpAndSettle();
    expect(find.text('Укажите название, телефон и пароль не короче 8 символов.'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('signup-password')), 'aigerim-2026');
    await tester.tap(find.byKey(const Key('signup-submit')));
    await tester.pumpAndSettle();
    expect(find.text('Компания создана'), findsOneWidget);
    expect(find.textContaining('Ваш логин: salon-aygerim'), findsOneWidget);
    expect(find.textContaining('/panel/setup'), findsOneWidget);
    expect(server.signups.last, {'name': 'Салон Айгерим', 'niche': 'beauty', 'phone': '0555 123 456',
        'password': 'aigerim-2026', 'contact_name': 'Айгерим'});

    await tester.tap(find.text('Перейти в приложение'));
    await tester.pumpAndSettle();
    expect(find.text('Салон Айгерим'), findsOneWidget); // the home screen, signed in
    expect(find.byKey(const Key('login')), findsNothing);
  });
}
