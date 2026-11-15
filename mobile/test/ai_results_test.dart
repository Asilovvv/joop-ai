import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  Future<void> signIn(WidgetTester tester, FakeJoop server) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'aktish');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
  }

  testWidgets('the owner sees what the AI did in two weeks', (tester) async {
    await signIn(tester, FakeJoop());
    await tester.scrollUntilVisible(find.byKey(const Key('ai-results')), 300, scrollable: find.byType(Scrollable).first);
    expect(find.text('ИИ за 14 дней'), findsOneWidget);
    expect(find.text('128'), findsOneWidget);
    expect(find.text('диалогов с клиентами'), findsOneWidget);
    expect(find.text('записей сделал ИИ'), findsOneWidget);
    expect(find.text('вопросов передано людям'), findsOneWidget);
  });

  testWidgets('a master does not see the whole business figures', (tester) async {
    final server = FakeJoop()..role = 'master';
    await signIn(tester, server);
    expect(find.byKey(const Key('ai-results')), findsNothing);
    expect(server.calls, isNot(contains('GET /api/mobile/ai-results')));
  });
}
