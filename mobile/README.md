# Joop AI mobile app

A Flutter app for the business's owner and staff. It signs in with the panel's login and password and shows, from
every channel the AI answers (Telegram, WhatsApp, Instagram, the web chat):

- **Сегодня** — bookings today, tomorrow and in 7 days, and the next visit;
- **Записи** — the bookings of any day, with cancelling (the time becomes free, as in the panel);
- **Заказы** — orders the AI collected (cafes, shops, delivery), moved through the panel's steps;
- **Заявки** — questions the AI handed to staff, bookings without a free slot, qualified leads;
- **Прайс** — the price list the AI quotes.

The tabs follow the niche, as the panel's menu does: a clinic has no «Заказы», a shop has no «Сегодня» and «Записи».

While the app is open it checks the server every 30 seconds: a new order or request shows a notice, and the tabs
carry counters of orders nobody accepted and requests nobody closed. Checks stop in the background and run at once when
the app comes back. Notifications on a locked phone need push (Firebase) and are not there yet.

Customers press «Я клиент: записаться», open a business by its code or chat link, and talk to its AI administrator
(prices, free time, booking), with staff replies from the panel in the same chat; «Цены и контакты» shows the card.

It talks to the server only through [`/api/mobile`](../docs/mobile-api.md). State is managed with Bloc
(`flutter_bloc`): `AuthBloc`, `BookingsBloc`, `ChatBloc`, `SummaryCubit`, `OrdersCubit`, `LeadsCubit`, `ServicesCubit` and `PlacesCubit` in `lib/bloc/`.

The app started from the Smile AI mid-term project (github.com/Asilovvv/ai-clinic-booking): its HTTP client, theme
and Bloc structure; the screens and data are Joop's.

## Languages

Russian and Kyrgyz, switched with «RU / KY» on the sign-in screen and in the app bar, and kept on the device. All texts
are in `lib/core/strings.dart`; the Kyrgyz ones need a check by a native speaker, as Joop's own Kyrgyz pages do. The
customer chat sends the language to Joop's web chat (`lang`), whose own messages have Kyrgyz versions; the AI answers
in the language the customer writes in. Order status words are translated in the app by status code, matching
`joop/order_status.py`. Messages the server writes itself (a wrong password, a delivery failure's reason) stay Russian.

## Run

```bash
cd mobile
flutter pub get
flutter run --dart-define=API_URL=https://your-joop-server
```

Without `API_URL` the app uses `http://localhost:8000` (`http://10.0.2.2:8000` in the Android emulator). The sign-in
screen has «Другой сервер» to change it on the device.

## Release

When the Joop server is public (docs/deploy.md), run **Actions → mobile-release → Run workflow** with its address
(`PUBLIC_BASE_URL`, for example `https://joop.kg`). The workflow checks that the server answers and already has
`/api/mobile`, builds the APK with that address built in, and attaches it to a GitHub Release.

## Tests

`flutter test`: the blocs and a full sign-in → bookings → cancel → price list run against a stand-in server
(`test/fake_joop.dart`), and parsing of responses recorded from a real Joop server (`test/fixtures/`). CI:
[.github/workflows/mobile.yml](../.github/workflows/mobile.yml), which also builds the Android APK.
