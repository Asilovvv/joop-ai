# Joop AI mobile app

A Flutter app for the business's owner and staff. It signs in with the panel's login and password and shows, from
every channel the AI answers (Telegram, WhatsApp, Instagram, the web chat):

- **Сегодня** — bookings today, tomorrow and in 7 days, «Проверьте предоплату» (a customer sent a receipt, or the
  deadline passed: «⋮ → Предоплата получена» tells the customer), the next visit, and «Касса сегодня» (takings, the month, visits
  that passed without a payment), and «ИИ за 14 дней» (what the AI did, as the panel's Сводка; not for masters);
- **Записи** — the bookings of any day, with cancelling (the time becomes free, as in the panel); «Записать» books a
  customer who phoned or walked in into a free time (marked «Вручную», not counted as the AI's work); «⋮ → Перенести» moves a booking to another free time
  (the customer is told in their chat); «Оплата» records
  what the customer paid (amount pre-filled from the price list; cash, card or transfer), as the panel's Касса;
- **Заказы** — orders the AI collected (cafes, shops, delivery), moved through the panel's steps;
- **Брони** (hotels, car rentals, banquet halls instead of «Сегодня» and «Записи») — upcoming room, car or hall bookings by
  date with the guests and the customer; «Отменить бронь» frees the dates, as the panel's «Брони» page; the chat opens from
  the booking; «Забронировать» books a guest who phoned or walked in: dates, then a room (car, hall) with the number still
  free for all the nights, guests, name and phone (marked «вручную», not counted as the AI's work);
- **В работе** (repair shops, car services, opticians, furniture makers; not for masters) — the panel's «Заказы в
  работе»: «Принять заказ» takes a receipt at the counter (what was left, the customer's phone, a free receipt number,
  price, due date), a tap changes its status; «готов» sends the customer the panel's message once, or says whom to call;
  the sign-up example's receipts go with one button;
- **Заявки** — questions the AI handed to staff, bookings without a free slot, qualified leads; «Ответить» opens the
  customer's dialogue and sends the owner's answer through their channel (or says why WhatsApp/Instagram no longer allow it);
- **Диалоги** (the button in the top bar, not for masters) — every real chat the AI is having, newest first, with search
  by name or phone; a tap opens the chat with the reply box and the panel's ready answers above it (a tap puts the
  answer, already filled for this customer, into the box; only the send button sends it);
- **Окна** (in the menu, not for masters) — the day's times by person: «Закрыть день» for an ill doctor (the
  AI stops booking it; the bookings left are listed to move or cancel), a tap closes or opens one time;
- **Меню «⋮»** in the top bar: «Клиенты» (every customer, search by name or phone, filter by tag; a tap opens the card),
  «Окна», «Выйти»;
- **Карточка клиента** — a tap on a booking: visits, what the customer spent, their rating, orders, and the note and
  tags staff keep (the panel's Клиенты; a master sees her own visits);
- **Прайс** — the price list the AI quotes, with the stop list: a switch takes an item off sale (the AI stops offering
  it) and back; sold-out items return through the panel's «Склад», Altegio price lists are switched in Altegio.

The tabs follow the niche, as the panel's menu does: a clinic has no «Заказы», a shop has no «Сегодня» and «Записи».
Above every tab, as on top of every panel page, the line about the end of the trial or paid month while the AI is
about to stop (yellow) or has stopped (red): the owner gets «Перейти к оплате» (the billing page in the browser), staff
are asked to tell the owner.

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

Plain `http://` works only for this device and the same Wi-Fi (localhost, `10.x`, `172.16–31.x`, `192.168.x`,
`*.local`); any other address must be `https://` — the app refuses it before sending anything, so a password never
crosses the internet unencrypted. An address typed without a scheme gets `http://` on the local network and
`https://` elsewhere.

## Showing it on a phone without a public server

A laptop and a phone on the same Wi-Fi (a phone hotspot works too):

1. On the laptop: `python -m joop serve` (it listens on all addresses, port 8000) and find its address on the Wi-Fi
   (`ipconfig getifaddr en0` on a Mac, `ipconfig` on Windows), say `192.168.1.5`.
2. Install the APK from the latest successful **Actions → mobile** run (artifact `joop-mobile-apk`) on the phone.
3. On the sign-in screen: «Другой сервер» → `192.168.1.5:8000`, then the company login and the panel password.

If the phone says there is no connection, check that both are on the same network and that the laptop's firewall
lets port 8000 in.

## Release

When the Joop server is public, run **Actions → mobile-release → Run workflow** with a version (`mobile-v1.0.0`)
and the server's address (`PUBLIC_BASE_URL`, for example `https://joop.kg`). The workflow checks that the server
answers and already has `/api/mobile`, builds the APK with that address built in, signs it with the owner's key and
attaches it to a GitHub Release. The key is made once and lives in the repository secrets: the steps are in
[docs/deploy.md](../docs/deploy.md), section 10.

A phone installs an update only when it is signed with the same key as the installed app. So a release is refused
without the key, or with another key than the previous release's, and the CI artifact above (`joop-mobile-apk`,
signed with a key made for that one run) is for trying only: nothing can update it. What the workflow decides is in
[deploy/app_release.py](../deploy/app_release.py), with tests in `tests/test_app_release.py`; every change to the
app also builds an APK through the same signing steps with a throwaway key.

To build a signed APK on your own machine, name the keystore in `mobile/android/key.properties` (never committed):

```properties
storeFile=/Users/you/joop-signing/joop-release.jks
storePassword=the keystore's password
keyAlias=joop
```

Without that file `flutter build apk --release` signs with the machine's debug key, as `flutter run --release` needs.

## Tests

`flutter test`: the blocs and a full sign-in → bookings → cancel → price list run against a stand-in server
(`test/fake_joop.dart`), and parsing of responses recorded from a real Joop server (`test/fixtures/`). CI:
[.github/workflows/mobile.yml](../.github/workflows/mobile.yml), which also builds the Android APK.
