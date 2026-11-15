import 'package:bloc_test/bloc_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/bloc/load_status.dart';
import 'package:joop_mobile/bloc/work_cubits.dart';
import 'package:joop_mobile/data/joop_repository.dart';
import 'package:joop_mobile/data/models.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  late FakeJoop server;
  late JoopRepository repository;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    server = FakeJoop(cafe: true);
    repository = server.repository();
    await repository.login('navat', 'secret-pass');
  });

  blocTest<OrdersCubit, WorkState<Order>>(
    'moves an order to its next step and says the customer was told',
    build: () => OrdersCubit(repository),
    act: (cubit) async {
      await cubit.load();
      await cubit.move(cubit.state.items.single, const OrderStep('accepted', 'Принять'));
    },
    skip: 2,
    expect: () => [
      isA<WorkState<Order>>().having((s) => s.busyId, 'busy', 41),
      isA<WorkState<Order>>()
          .having((s) => s.items.single.label, 'label', 'Принят')
          .having((s) => s.items.single.next.map((n) => n.label), 'next', ['В пути', 'Выполнен', 'Отменить'])
          .having((s) => s.notice, 'notice', 'Заказ №41: Принят. Клиенту отправлено сообщение.'),
    ],
  );

  blocTest<OrdersCubit, WorkState<Order>>(
    'a step another person already took reloads the order as it is now',
    build: () => OrdersCubit(repository),
    act: (cubit) async {
      await cubit.load();
      server.orders.single['next'] = <Map<String, String>>[]; // someone closed it meanwhile
      await cubit.move(cubit.state.items.single, const OrderStep('accepted', 'Принять'));
    },
    skip: 3,
    expect: () => [
      isA<WorkState<Order>>().having((s) => s.error, 'error', 'Заказ уже «Новый».'),
      isA<WorkState<Order>>().having((s) => s.status, 'reloading', LoadStatus.loading),
      isA<WorkState<Order>>().having((s) => s.items.single.isOpen, 'open', isFalse),
    ],
  );

  blocTest<LeadsCubit, WorkState<Lead>>(
    'marks a request done',
    build: () => LeadsCubit(repository),
    act: (cubit) async {
      await cubit.load();
      await cubit.markDone(cubit.state.items.single);
    },
    skip: 3,
    expect: () => [
      isA<WorkState<Lead>>()
          .having((s) => s.items.single.done, 'done', isTrue)
          .having((s) => s.items.single.closedBy, 'by', 'Владелец'),
    ],
  );

  test('a background check announces new orders and requests, and stays quiet when it fails', () async {
    final orders = OrdersCubit(repository);
    final leads = LeadsCubit(repository);
    await orders.load();
    await leads.load();
    expect(orders.newCount, 1);

    await orders.refresh();
    expect(orders.state.notice, isNull); // nothing new

    server.orders.insert(0, _newOrder(42));
    server.leads.insert(0, {...server.leads.single, 'id': 10, 'summary': 'Есть ли парковка?'});
    await orders.refresh();
    await leads.refresh();
    expect(orders.state.notice, 'Новый заказ №42');
    expect(orders.newCount, 2);
    expect(leads.state.notice, 'Новая заявка');
    expect(leads.newCount, 2);

    await repository.logout(); // the server now answers 401
    await orders.refresh();
    expect(orders.state.error, isNull);
    expect(orders.state.items, hasLength(2)); // the list stays as it was
    await orders.close();
    await leads.close();
  });

  testWidgets('an open app shows a new order within the check interval, with a counter on the tab', (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final cafe = FakeJoop(cafe: true);
    await tester.pumpWidget(JoopApp(repository: cafe.repository(), customers: cafe.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'navat');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(Badge, '1'), findsWidgets); // one order nobody accepted, one new request

    cafe.orders.insert(0, _newOrder(42));
    await tester.pump(const Duration(seconds: 31));
    await tester.pumpAndSettle();
    expect(find.text('Новый заказ №42'), findsOneWidget);
    expect(find.text('1 × Манты'), findsOneWidget);
    expect(find.widgetWithText(Badge, '2'), findsWidgets);

    int ordersAsked() => cafe.calls.where((c) => c == 'GET /api/mobile/orders').length;
    final before = ordersAsked();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(minutes: 2));
    expect(ordersAsked(), before); // no checks in the background
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(ordersAsked(), before + 1); // back in the app: checked at once

    await tester.tap(find.byTooltip('Выйти')); // stops the checks
    await tester.pumpAndSettle();
  });

  testWidgets('a cafe owner sees orders and requests instead of bookings', (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final cafe = FakeJoop(cafe: true);
    await tester.pumpWidget(JoopApp(repository: cafe.repository(), customers: cafe.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'navat');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();

    expect(find.text('Сегодня'), findsNothing); // a cafe without bookings has no bookings tabs
    expect(find.text('Заказы'), findsWidgets);
    expect(find.text('2 × Плов'), findsOneWidget);
    expect(find.text('1 200 сом'), findsOneWidget);

    await tester.tap(find.widgetWithText(FilledButton, 'Принять'));
    await tester.pumpAndSettle();
    expect(find.text('Заказ №41: Принят. Клиенту отправлено сообщение.'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'В пути'), findsOneWidget);

    await tester.tap(find.text('Заявки').last);
    await tester.pumpAndSettle();
    expect(find.text('Можно банкет на 40 человек?'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Готово'));
    await tester.pumpAndSettle();
    expect(find.text('Закрыл: Владелец'), findsOneWidget);
  });

  dialogueTests();
}

void dialogueTests() {
  Future<FakeJoop> openRequest(WidgetTester tester, [FakeJoop? server]) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final cafe = server ?? FakeJoop(cafe: true);
    await tester.pumpWidget(JoopApp(repository: cafe.repository(), customers: cafe.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('company')), 'navat');
    await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
    await tester.tap(find.byKey(const Key('login')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Заявки').last);
    await tester.pumpAndSettle();
    return cafe;
  }

  testWidgets('the owner answers a request customer from the app, and the request closes', (tester) async {
    final cafe = await openRequest(tester);
    await tester.tap(find.widgetWithText(FilledButton, 'Ответить'));
    await tester.pumpAndSettle();
    expect(find.text('Передал вопрос администратору.'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('reply-input')), 'Да, банкетный зал на 50 мест свободен в субботу.');
    await tester.tap(find.byKey(const Key('reply-send')));
    await tester.pumpAndSettle();
    expect(find.text('Да, банкетный зал на 50 мест свободен в субботу.'), findsOneWidget);
    expect(find.text('Ответ отправлен, заявка закрыта'), findsOneWidget);
    expect(cafe.calls, contains('POST /api/mobile/conversations/70/reply'));
    expect(find.textContaining('продлевает паузу на 12 часов'), findsOneWidget);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Закрыл: Владелец'), findsOneWidget);
  });

  testWidgets('the pause the owner chose is named after a reply', (tester) async {
    final cafe = FakeJoop(cafe: true);
    cafe.dialogues[70]!['takeover_minutes'] = 15;
    await openRequest(tester, cafe);
    await tester.tap(find.widgetWithText(FilledButton, 'Ответить'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('ai-paused')), findsNothing); // the AI still answers
    await tester.enterText(find.byKey(const Key('reply-input')), 'Сейчас уточню.');
    await tester.tap(find.byKey(const Key('reply-send')));
    await tester.pumpAndSettle();
    expect(find.textContaining('продлевает паузу на 15 минут'), findsOneWidget);
  });

  testWidgets('staff switch the AI off in a chat and back on', (tester) async {
    final cafe = await openRequest(tester);
    await tester.tap(find.widgetWithText(FilledButton, 'Ответить'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Выключить ИИ на 24 часа'));
    await tester.pumpAndSettle();
    expect(cafe.calls, contains('POST /api/mobile/conversations/70/ai'));
    expect(find.text('ИИ молчит в этом диалоге 24 часа. Отвечайте клиенту сами.'), findsOneWidget);
    expect(find.byKey(const Key('ai-paused')), findsOneWidget);
    await tester.tap(find.byTooltip('Включить ИИ'));
    await tester.pumpAndSettle();
    expect(cafe.dialogues[70]!['ai_paused'], isFalse);
    expect(find.byKey(const Key('ai-paused')), findsNothing);
  });

  testWidgets('when the channel no longer allows a reply, the app says why and gives the phone', (tester) async {
    final cafe = FakeJoop(cafe: true);
    cafe.dialogues[70]!['reply_blocked'] = 'WhatsApp разрешает отвечать только 24 часа после сообщения клиента.';
    await openRequest(tester, cafe);
    await tester.tap(find.widgetWithText(FilledButton, 'Ответить'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('reply-input')), findsNothing);
    expect(find.textContaining('только 24 часа'), findsOneWidget);
    expect(find.textContaining('+996700111222'), findsOneWidget);
  });
}

Map<String, dynamic> _newOrder(int id) => {
      'id': id, 'created_at': '2026-11-13T07:00:00Z', 'status': 'new', 'label': 'Новый', 'mode': 'pickup',
      'address': '', 'wanted_time': '', 'total': 300, 'channel': 'instagram', 'comment': '',
      'customer': {'name': 'Динара', 'phone': ''},
      'lines': [{'name': 'Манты', 'quantity': 1, 'unit_price': 300}],
      'next': [{'status': 'accepted', 'label': 'Принять'}, {'status': 'cancelled', 'label': 'Отменить'}],
    };
