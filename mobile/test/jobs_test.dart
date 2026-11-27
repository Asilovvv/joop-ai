import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

Future<FakeJoop> _signIn(WidgetTester tester, FakeJoop server, String company) async {
  SharedPreferences.setMockInitialValues({});
  tester.view.physicalSize = const Size(1080, 4200); // the test font is wider than a phone's
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('company')), company);
  await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
  await tester.tap(find.byKey(const Key('login')));
  await tester.pumpAndSettle();
  return server;
}

Future<void> _addJob(WidgetTester tester, {required String item, required String phone, String name = ''}) async {
  await tester.tap(find.byKey(const Key('job-add')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('job-item')), item);
  await tester.enterText(find.byKey(const Key('job-phone')), phone);
  if (name.isNotEmpty) await tester.enterText(find.byKey(const Key('job-name')), name);
  await tester.tap(find.byKey(const Key('job-save')));
  await tester.pumpAndSettle();
}

Future<void> _setStatus(WidgetTester tester, int id, String status) async {
  await tester.tap(find.byKey(Key('job-$id')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(Key('job-status-$status')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('job-edit-save')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('a repair shop takes receipts and marks them ready at the counter', (tester) async {
    final server = await _signIn(tester, FakeJoop(repair: true), 'remont');
    await tester.tap(find.text('В работе'));
    await tester.pumpAndSettle();
    expect(find.text('Заказы в работе'), findsOneWidget); // the app bar
    expect(find.byKey(const Key('jobs-example-banner')), findsOneWidget);
    expect(find.text('готов, можно забирать'), findsOneWidget);
    expect(find.textContaining('срок 16.11'), findsOneWidget);

    // the example's receipts out after a yes
    await tester.tap(find.byKey(const Key('jobs-example-delete')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('jobs-example-yes')));
    await tester.pumpAndSettle();
    expect(find.text('Удалено квитанций из примера: 2.'), findsOneWidget);
    expect(find.text('Нет заказов в работе.'), findsOneWidget);
    expect(server.jobs, isEmpty);

    // what was left and the phone are asked before anything is sent
    await tester.tap(find.byKey(const Key('job-add')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byKey(const Key('job-number'))).controller!.text, '50001');
    await tester.tap(find.byKey(const Key('job-save')));
    await tester.pumpAndSettle();
    expect(find.text('Заполните: по этому ИИ найдёт заказ'), findsNWidgets(2));
    expect(server.jobs, isEmpty);
    await tester.enterText(find.byKey(const Key('job-item')), 'Куртка, химчистка');
    await tester.enterText(find.byKey(const Key('job-phone')), '0555 404 404');
    await tester.enterText(find.byKey(const Key('job-name')), 'Нурлан');
    await tester.enterText(find.byKey(const Key('job-price')), '600 сом');
    await tester.tap(find.byKey(const Key('job-due')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('job-save')));
    await tester.pumpAndSettle();
    expect(find.text('Заказ №50001 принят. Назовите клиенту номер квитанции: по нему и телефону ИИ ответит, готово ли.'),
        findsOneWidget);
    expect(server.jobs.single, containsPair('customer_name', 'Нурлан'));
    expect(server.jobs.single['ready_by'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
    expect(find.text('№50001 · Куртка, химчистка'), findsOneWidget);

    // «готов»: the customer who wrote in a chat is told
    await _setStatus(tester, 10, 'ready');
    expect(server.jobChanges.last, containsPair('status', 'ready'));
    expect(find.text('Заказ №50001 готов. Клиенту отправлено сообщение.'), findsOneWidget);
    expect(find.text('готов, можно забирать · клиенту написали'), findsOneWidget);

    // a receipt number already given is refused on the screen in front
    await tester.tap(find.byKey(const Key('job-add')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byKey(const Key('job-number'))).controller!.text, '50002');
    await tester.enterText(find.byKey(const Key('job-number')), '50001');
    await tester.enterText(find.byKey(const Key('job-item')), 'Шуба');
    await tester.enterText(find.byKey(const Key('job-phone')), '0555 404 404');
    await tester.tap(find.byKey(const Key('job-save')));
    await tester.pumpAndSettle();
    expect(find.text('Квитанция №50001 уже есть.'), findsOneWidget);
    expect(server.jobs.length, 1);

    // a customer who never wrote: staff are told to call
    await _addJob(tester, item: 'Брюки, ушить', phone: '0700 111 222');
    await _setStatus(tester, 11, 'ready');
    expect(find.textContaining('Позвоните: 0700 111 222'), findsOneWidget);

    // issued: under «Выданные и отменённые», no longer opened for a change
    await _setStatus(tester, 10, 'issued');
    expect(find.text('Заказ №50001: выдан.'), findsOneWidget);
    expect(find.text('Выданные и отменённые'), findsOneWidget);
    final calls = server.jobChanges.length;
    await tester.tap(find.byKey(const Key('job-10')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('job-edit-save')), findsNothing);
    expect(server.jobChanges.length, calls);

    // search by the item's words
    await tester.enterText(find.byKey(const Key('jobs-search')), 'брюки');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('job-11')), findsOneWidget);
    expect(find.byKey(const Key('job-10')), findsNothing);
  });

  testWidgets('a clinic has no receipts tab', (tester) async {
    await _signIn(tester, FakeJoop(), 'aktish');
    expect(find.text('В работе'), findsNothing);
  });
}
