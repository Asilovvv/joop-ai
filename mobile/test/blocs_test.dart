import 'package:bloc_test/bloc_test.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/bloc/auth_bloc.dart';
import 'package:joop_mobile/bloc/bookings_bloc.dart';
import 'package:joop_mobile/bloc/load_status.dart';
import 'package:joop_mobile/bloc/services_cubit.dart';
import 'package:joop_mobile/bloc/summary_cubit.dart';
import 'package:joop_mobile/data/joop_repository.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_joop.dart';

void main() {
  late FakeJoop server;
  late JoopRepository repository;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    server = FakeJoop();
    repository = server.repository();
  });

  group('AuthBloc', () {
    blocTest<AuthBloc, AuthState>(
      'signs in with the panel credentials',
      build: () => AuthBloc(repository),
      act: (bloc) => bloc.add(const AuthLoginRequested('aktish', 'secret-pass')),
      expect: () => [
        const AuthLoading(),
        isA<AuthSignedIn>().having((s) => s.account.businessName, 'business', 'Ак-Тиш Дент'),
      ],
    );

    blocTest<AuthBloc, AuthState>(
      'shows the server message for a wrong password',
      build: () => AuthBloc(repository),
      act: (bloc) => bloc.add(const AuthLoginRequested('aktish', 'wrong')),
      expect: () => [const AuthLoading(), const AuthSignedOut(error: 'Неверный логин или пароль.')],
    );

    test('a saved token is used on the next launch, and logging out forgets it', () async {
      await repository.login('aktish', 'secret-pass');
      final restored = AuthBloc(server.repository())..add(const AuthStarted());
      await expectLater(restored.stream, emits(isA<AuthSignedIn>()));
      restored.add(const AuthLogoutRequested());
      await expectLater(restored.stream, emits(const AuthSignedOut()));
      final again = AuthBloc(server.repository())..add(const AuthStarted());
      await expectLater(again.stream, emits(const AuthSignedOut()));
    });
  });

  group('signed in', () {
    setUp(() => repository.login('aktish', 'secret-pass'));

    blocTest<SummaryCubit, SummaryState>(
      'loads the home screen counts',
      build: () => SummaryCubit(repository),
      act: (cubit) => cubit.load(),
      expect: () => [
        const SummaryState(status: LoadStatus.loading),
        isA<SummaryState>()
            .having((s) => s.summary!.today, 'today', 2)
            .having((s) => s.summary!.tomorrow, 'tomorrow', 1)
            .having((s) => s.summary!.next!.customerName, 'next', 'Айгуль'),
      ],
    );

    blocTest<BookingsBloc, BookingsState>(
      'loads a day, moves to the next one and cancels a booking',
      build: () => BookingsBloc(repository, today: DateTime(2026, 11, 13, 9)),
      act: (bloc) async {
        bloc.add(BookingsDayChanged(DateTime(2026, 11, 13)));
        await Future<void>.delayed(Duration.zero);
        bloc.add(const BookingCancelRequested(2));
        await Future<void>.delayed(Duration.zero);
        bloc.add(BookingsDayChanged(DateTime(2026, 11, 14)));
      },
      skip: 1,
      expect: () => [
        isA<BookingsState>().having((s) => s.bookings.map((b) => b.customerName), 'names', ['Айгуль', 'Бакыт']),
        isA<BookingsState>().having((s) => s.cancelling, 'cancelling', 2),
        isA<BookingsState>()
            .having((s) => s.activeCount, 'active', 1)
            .having((s) => s.notice, 'notice', 'Запись отменена, время снова свободно'),
        isA<BookingsState>().having((s) => s.bookings, 'cleared for the new day', isEmpty),
        isA<BookingsState>().having((s) => s.bookings.single.customerName, 'tomorrow', 'Нурлан'),
      ],
    );

    blocTest<BookingsBloc, BookingsState>(
      'reports when a booking was already cancelled',
      build: () => BookingsBloc(repository, today: DateTime(2026, 11, 13)),
      setUp: () => server.bookings.first['status'] = 'cancelled',
      act: (bloc) => bloc.add(const BookingCancelRequested(1)),
      expect: () => [
        isA<BookingsState>().having((s) => s.cancelling, 'cancelling', 1),
        isA<BookingsState>().having((s) => s.error, 'error', 'Запись уже отменена.'),
      ],
    );

    blocTest<ServicesCubit, ServicesState>(
      'loads the price list',
      build: () => ServicesCubit(repository),
      act: (cubit) => cubit.load(),
      expect: () => [
        const ServicesState(status: LoadStatus.loading),
        isA<ServicesState>().having((s) => s.services.map((x) => x.available), 'available', [true, false]),
      ],
    );
  });
}
