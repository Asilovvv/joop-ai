import 'package:bloc_test/bloc_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/bloc/chat_bloc.dart';
import 'package:joop_mobile/bloc/places_cubit.dart';
import 'package:joop_mobile/data/customer_repository.dart';
import 'package:joop_mobile/data/models.dart';
import 'package:joop_mobile/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  late FakeJoop server;
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    server = FakeJoop();
  });

  test('a code is read from what a customer types or pastes', () {
    expect(codeFrom(' AkTish '), 'aktish');
    expect(codeFrom('https://joop.kg/c/aktish?embed=1'), 'aktish');
    expect(codeFrom('https://joop.kg/m/aktish'), 'aktish');
    expect(codeFrom('ак тиш'), isNull);
  });

  blocTest<PlacesCubit, PlacesState>(
    'opens a business by its link and remembers it; an unknown code gets the server message',
    build: () => PlacesCubit(server.customers()),
    act: (cubit) async {
      await cubit.open('https://joop.kg/c/aktish');
      await cubit.open('nobody');
    },
    expect: () => [
      const PlacesState(adding: true),
      isA<PlacesState>()
          .having((s) => s.opened!.name, 'opened', 'Ак-Тиш Дент')
          .having((s) => s.places, 'saved', [const SavedPlace('aktish', 'Ак-Тиш Дент')]),
      isA<PlacesState>().having((s) => s.adding, 'adding', true),
      isA<PlacesState>().having((s) => s.error, 'error', 'Такой компании нет или её чат выключен.'),
    ],
  );

  test('the chat sends with one visitor token, keeps history and picks up staff replies', () async {
    final repo = server.customers();
    final bloc = ChatBloc(repo, 'aktish', poll: Duration.zero)..add(const ChatOpened());
    await Future<void>.delayed(const Duration(milliseconds: 50));
    bloc.add(const ChatMessageSent('Сколько стоит консультация?'));
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(bloc.state.messages.map((m) => m.fromCustomer), [true, false]);
    expect(bloc.state.messages.last.text, contains('500 сом'));
    expect(RegExp(r'^[a-f0-9]{24}$').hasMatch(server.chat.single['visitor'] as String), isTrue);

    server.staffReplies.add({'id': 7, 'text': 'Ждём вас завтра!'});
    bloc.add(const ChatPolled());
    await Future<void>.delayed(const Duration(milliseconds: 50));
    bloc.add(const ChatPolled()); // the same reply is not added twice
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(bloc.state.messages.where((m) => m.staffId == 7), hasLength(1));
    await bloc.close();

    final reopened = ChatBloc(server.customers(), 'aktish', poll: Duration.zero)..add(const ChatOpened());
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(reopened.state.messages, hasLength(3));
    await reopened.close();
  });

  testWidgets('a customer opens a business and books through its AI', (tester) async {
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(JoopApp(repository: server.repository(), customers: server.customers(), today: DateTime(2026, 11, 13)));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('customer')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('place-code')), 'aktish');
    await tester.tap(find.byKey(const Key('place-open')));
    await tester.pumpAndSettle();
    expect(find.text('Ак-Тиш Дент'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('chat-input')), 'Хочу на консультацию');
    await tester.tap(find.byKey(const Key('chat-send')));
    await tester.pumpAndSettle();
    expect(find.text('Хочу на консультацию'), findsOneWidget);
    expect(find.textContaining('Свободно завтра в 10:00'), findsOneWidget);

    await tester.tap(find.text('Цены и контакты'));
    await tester.pumpAndSettle();
    expect(find.text('500 сом'), findsOneWidget);
    expect(find.text('ул. Киевская, 95'), findsOneWidget);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Мои компании'), findsOneWidget);
  });
}
