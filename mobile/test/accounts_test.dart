import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

Future<FakeJoop> _signIn(WidgetTester tester, {String role = 'owner'}) async {
  SharedPreferences.setMockInitialValues({});
  tester.view.physicalSize = const Size(1080, 4200); // the test font is wider than a phone's
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

Future<void> _addLogin(WidgetTester tester, {required String password, String? master}) async {
  await tester.tap(find.byKey(const Key('account-add')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('account-name')), 'Айгерим');
  await tester.enterText(find.byKey(const Key('account-login')), 'Aigerim');
  await tester.enterText(find.byKey(const Key('account-password')), password);
  if (master != null) {
    await tester.tap(find.byKey(const Key('account-master')));
    await tester.pumpAndSettle();
    await tester.tap(find.text(master).last);
    await tester.pumpAndSettle();
  }
  await tester.tap(find.byKey(const Key('account-save')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the owner gives a master her own login from the phone', (tester) async {
    final server = await _signIn(tester);
    await tester.tap(find.byKey(const Key('menu-accounts')));
    await tester.pumpAndSettle();
    expect(find.text('Пока входят только паролем компании.'), findsOneWidget);
    expect(find.textContaining('логин компании «aktish»'), findsOneWidget);

    await _addLogin(tester, password: 'short'); // the server's refusal, on the screen in front
    expect(find.text('Пароль должен быть не короче 8 символов.'), findsOneWidget);
    expect(server.logins, isEmpty);

    await _addLogin(tester, password: 'aigerim-pass', master: 'Айгерим');
    expect(server.loginCalls.last, allOf(containsPair('login', 'Aigerim'), containsPair('password', 'aigerim-pass'),
        containsPair('staff_id', 1)));
    expect(find.text('Вход «aigerim» создан. Скажите сотруднику: логин компании «aktish», логин «aigerim» и пароль, который вы задали.'),
        findsOneWidget);
    expect(find.text('Айгерим · aigerim'), findsOneWidget);
    expect(find.text('мастер: Айгерим · ещё не входил(а)'), findsOneWidget);

    await tester.tap(find.byKey(const Key('account-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('account-active')));
    await tester.pumpAndSettle();
    expect(server.logins.single['active'], isFalse);
    expect(find.text('мастер: Айгерим · выключен · ещё не входил(а)'), findsOneWidget);

    await tester.tap(find.byKey(const Key('account-1')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('account-new-password')), 'new-aigerim-pass');
    await tester.tap(find.byKey(const Key('account-password-save')));
    await tester.pumpAndSettle();
    expect(server.loginCalls.last, allOf(containsPair('path', '/api/mobile/accounts/1/password'),
        containsPair('password', 'new-aigerim-pass')));
    expect(find.textContaining('Пароль изменён'), findsOneWidget);
  });

  testWidgets('a master has no such menu item', (tester) async {
    await _signIn(tester, role: 'master');
    expect(find.byKey(const Key('menu-accounts')), findsNothing);
    expect(find.byKey(const Key('menu-sign-out')), findsOneWidget);
  });
}
