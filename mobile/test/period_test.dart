import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

Future<void> _home(WidgetTester tester, FakeJoop server, {String company = 'aktish'}) async {
  SharedPreferences.setMockInitialValues({});
  tester.view.physicalSize = const Size(1080, 2340);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('company')), company);
  await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
  await tester.tap(find.byKey(const Key('login')));
  await tester.pumpAndSettle();
}

const _browser = MethodChannel('kg.joop/browser');

void main() {
  testWidgets('nothing to say: no line', (tester) async {
    await _home(tester, FakeJoop());
    expect(find.byKey(const Key('period-warn')), findsNothing);
    expect(find.byKey(const Key('period-error')), findsNothing);
  });

  testWidgets('the owner sees the trial end and opens the billing page in the browser', (tester) async {
    final opened = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(_browser, (call) async {
      opened.add(call.arguments as String);
      return true;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(_browser, null));
    final server = FakeJoop()
      ..period = {
        'level': 'warn',
        'text': 'Пробный период заканчивается 16.11 в 12:00 — осталось 3 дня. Без оплаты ИИ остановится 19.11.',
        'pay_url': 'https://joop.test/panel/billing',
        'ask_owner': false,
      };
    await _home(tester, server);
    expect(find.byKey(const Key('period-warn')), findsOneWidget);
    expect(find.textContaining('осталось 3 дня'), findsOneWidget);
    await tester.tap(find.byKey(const Key('period-pay')));
    await tester.pumpAndSettle();
    expect(opened, ['https://joop.test/panel/billing']);
  });

  testWidgets('without a browser the address is copied and said', (tester) async {
    final copied = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied.add((call.arguments as Map)['text'] as String);
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(_browser, (call) async => false); // no browser
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(_browser, null));
    final server = FakeJoop()
      ..period = {'level': 'error', 'text': 'ИИ не отвечает клиентам с 19.11: пробный период закончился.',
        'pay_url': 'https://joop.test/panel/billing', 'ask_owner': false};
    await _home(tester, server);
    expect(find.byKey(const Key('period-error')), findsOneWidget);
    await tester.tap(find.byKey(const Key('period-pay')));
    await tester.pumpAndSettle();
    expect(copied, ['https://joop.test/panel/billing']);
    expect(find.text('Ссылка на оплату скопирована — откройте её в браузере.'), findsOneWidget);
  });

  testWidgets('staff are asked to tell the owner, with no way to pay', (tester) async {
    final server = FakeJoop()
      ..role = 'staff'
      ..period = {'level': 'error', 'text': 'ИИ не отвечает клиентам с 19.11.', 'pay_url': null, 'ask_owner': true};
    await _home(tester, server);
    expect(find.byKey(const Key('period-ask-owner')), findsOneWidget);
    expect(find.byKey(const Key('period-pay')), findsNothing);
  });

  // Independent review of #308: shops, hotels and rentals have no «Сегодня», and the owner may work in «Заявки».
  const stopped = {
    'level': 'error',
    'text': 'ИИ не отвечает клиентам с 19.11: пробный период закончился. Оплатите подписку.',
    'pay_url': 'https://joop.test/panel/billing',
    'ask_owner': false,
  };

  testWidgets('a hotel and a cafe see the line too, on every tab', (tester) async {
    for (final (server, company) in [(FakeJoop(hotel: true), 'uyut'), (FakeJoop(cafe: true), 'navat')]) {
      server.period = stopped;
      await _home(tester, server, company: company);
      expect(find.text('Сегодня'), findsNothing); // no such tab here
      expect(find.byKey(const Key('period-error')), findsOneWidget);
      await tester.tap(find.text('Заявки'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('period-error')), findsOneWidget);
      expect(find.byKey(const Key('period-pay')), findsOneWidget);
      await tester.pumpWidget(const SizedBox()); // the next business signs in from scratch
    }
  });

  testWidgets('a clinic keeps it above «Записи» as well', (tester) async {
    final server = FakeJoop()..period = stopped;
    await _home(tester, server);
    expect(find.byKey(const Key('period-error')), findsOneWidget);
    await tester.tap(find.text('Записи'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('period-error')), findsOneWidget);
  });
}
