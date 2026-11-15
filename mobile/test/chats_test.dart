import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  testWidgets('the owner opens the chats, finds one and answers it', (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final server = FakeJoop(cafe: true);
    await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'navat');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('open-chats')));
    await tester.pumpAndSettle();
    expect(find.text('ИИ: Передал вопрос администратору.'), findsOneWidget);
    expect(find.text('Спасибо!'), findsOneWidget);
    expect(find.text('ИИ на паузе'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('chats-search')), 'дина');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat-70')), findsNothing);
    expect(find.byKey(const Key('chat-71')), findsOneWidget);

    await tester.enterText(find.byKey(const Key('chats-search')), '');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat-70')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('reply-input')), 'Банкетный зал свободен.');
    await tester.tap(find.byKey(const Key('reply-send')));
    await tester.pumpAndSettle();
    expect(server.calls, contains('POST /api/mobile/conversations/70/reply'));
  });

  testWidgets('a master has no chats button', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final server = FakeJoop()..role = 'master';
    await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'aktish');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('open-chats')), findsNothing);
  });
}
