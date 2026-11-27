import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

Future<void> _openContacts(WidgetTester tester, FakeJoop server, String company) async {
  SharedPreferences.setMockInitialValues({});
  tester.view.physicalSize = const Size(1080, 4200); // the whole form on one screen
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('company')), company);
  await tester.enterText(find.byKey(const Key('password')), 'secret-pass');
  await tester.tap(find.byKey(const Key('login')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('app-menu')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('menu-setup')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('open-contacts')));
  await tester.pumpAndSettle();
}

String _text(WidgetTester tester, String key) => tester.widget<TextField>(find.byKey(Key(key))).controller!.text;

void main() {
  testWidgets('a cafe sets its minimum order and delivery from the phone', (tester) async {
    final server = FakeJoop(cafe: true);
    await _openContacts(tester, server, 'navat');
    expect(find.text('Заказы'), findsWidgets);
    expect(find.byKey(const Key('order-terms-example')), findsOneWidget); // the example's sums are marked
    expect([_text(tester, 'contacts-min-order'), _text(tester, 'contacts-delivery-fee'), _text(tester, 'contacts-free-from')],
        ['500', '150', '3000']);

    await tester.enterText(find.byKey(const Key('contacts-delivery-fee')), '20о0'); // a letter is not taken
    expect(_text(tester, 'contacts-delivery-fee'), '200');
    await tester.enterText(find.byKey(const Key('contacts-free-from')), '');
    await tester.tap(find.byKey(const Key('contacts-save')));
    await tester.pumpAndSettle();
    expect(server.contacts['orders'], {'min_order': 500, 'delivery_fee': 200, 'free_delivery_from': 0, 'example': false});
    expect(find.text('Сохранено.'), findsOneWidget);
    expect(find.byKey(const Key('order-terms-example')), findsNothing);
    expect(_text(tester, 'contacts-free-from'), '0');
  });

  testWidgets('a clinic takes no orders: no such card', (tester) async {
    await _openContacts(tester, FakeJoop(), 'aktish');
    expect(find.byKey(const Key('contacts-address')), findsOneWidget);
    expect(find.byKey(const Key('contacts-min-order')), findsNothing);
  });
}
