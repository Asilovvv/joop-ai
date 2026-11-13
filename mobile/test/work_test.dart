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
}
