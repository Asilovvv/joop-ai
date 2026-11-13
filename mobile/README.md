# Joop AI mobile app

A Flutter app for the business's owner and staff. It signs in with the panel's login and password and shows, from
every channel the AI answers (Telegram, WhatsApp, Instagram, the web chat):

- **Сегодня** — bookings today, tomorrow and in 7 days, and the next visit;
- **Записи** — the bookings of any day, with cancelling (the time becomes free, as in the panel);
- **Прайс** — the price list the AI quotes.

It talks to the server only through [`/api/mobile`](../docs/mobile-api.md). State is managed with Bloc
(`flutter_bloc`): `AuthBloc` and `BookingsBloc`, `SummaryCubit` and `ServicesCubit` in `lib/bloc/`.

The app started from the Smile AI mid-term project (github.com/Asilovvv/ai-clinic-booking): its HTTP client, theme
and Bloc structure; the screens and data are Joop's.

## Run

```bash
cd mobile
flutter pub get
flutter run --dart-define=API_URL=https://your-joop-server
```

Without `API_URL` the app uses `http://localhost:8000` (`http://10.0.2.2:8000` in the Android emulator). The sign-in
screen has «Другой сервер» to change it on the device.

## Tests

`flutter test`: the blocs and a full sign-in → bookings → cancel → price list run against a stand-in server
(`test/fake_joop.dart`), and parsing of responses recorded from a real Joop server (`test/fixtures/`). CI:
[.github/workflows/mobile.yml](../.github/workflows/mobile.yml), which also builds the Android APK.
