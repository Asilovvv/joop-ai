import '../data/models.dart';
import 'strings.dart';

String _two(int n) => n.toString().padLeft(2, '0');

/// 09:30
String formatTime(DateTime d) => '${_two(d.hour)}:${_two(d.minute)}';

/// пт, 13 ноя · жм, 13-ноябрь
String formatDay(DateTime d) {
  final s = S.current;
  final wd = s.weekdays[d.weekday - 1], month = s.months[d.month - 1];
  return s.code == 'ky' ? '$wd, ${d.day}-$month' : '$wd, ${d.day} $month';
}

/// The channel a customer wrote from, as the panel names it.
String channelName(String channel) => switch (channel) {
      'telegram' => 'Telegram',
      'whatsapp' => 'WhatsApp',
      'instagram' => 'Instagram',
      'web' => S.current.channelSite,
      '' => S.current.channelManual,
      _ => channel,
    };

/// Where a booking came from, as the panel names it (joop/web/app.py booking_origin): a partner's system or another
/// assistant is «через API», the customer's own pick on the booking page «со страницы записи» — neither has a chat
/// channel, but nobody made them by hand either.
String bookingOrigin(Booking b) => switch (b.source) {
      'api' => S.current.channelApi,
      'page' => S.current.channelPage,
      _ => channelName(b.channel),
    };

/// "1 запись", "2 записи", "5 записей"; "5 жазылуу".
String bookingsWord(int n) => S.current.bookingsCount(n);

/// A stored phone as people read it: +996777444555 -> +996 777 444 555, +77011234567 -> +7 701 123 45 67; anything else
/// stays as it is (the server's display_phone does the same for the panel).
String formatPhone(String phone) {
  final p = phone.trim();
  if (RegExp(r'^\+996\d{9}$').hasMatch(p)) {
    return '${p.substring(0, 4)} ${p.substring(4, 7)} ${p.substring(7, 10)} ${p.substring(10)}';
  }
  if (RegExp(r'^\+7\d{10}$').hasMatch(p)) {
    return '${p.substring(0, 2)} ${p.substring(2, 5)} ${p.substring(5, 8)} ${p.substring(8, 10)} ${p.substring(10)}';
  }
  return p;
}

/// A currency the business named itself — a realty agency writes «120 000 $» — so no «сом» goes on top of it. The same
/// list as the website's menu (joop/web/menu.py CURRENCY); Dart's \b knows only Latin letters, so the words are fenced
/// by «no letter or digit around them» instead («150 за рубашку» is not roubles).
final _currency = RegExp(
    r'сом|kgs|\d\s*с\.|[$€₽₸£¥]|(?<![\p{L}\d])(?:usd|eur|rub|руб|тенге|тг|сум|у\.\s?е)(?![\p{L}\d])',
    caseSensitive: false,
    unicode: true);

/// A number right before one of these is a quantity («1 кг — 450», «60 минут — 1 200»), not the price
/// (joop/web/menu.py UNIT).
final _unit = RegExp(
    r'\s*(?:кг|гр?|мл|л|шт|мм|см|м²|м2|м|мин|минут[аы]?|час(?:а|ов)?|ч|сут(?:ок|ки)?|дн(?:я|ей)?|день|'
    r'ноч(?:ь|и|ей)|мес(?:яц(?:а|ев)?)?|чел(?:овек)?|порц(?:ия|ии|ий)?|занят(?:ие|ия|ий)|урок(?:а|ов)?|'
    r'сеанс(?:а|ов)?|раз(?:а)?)(?![\p{L}\d])',
    caseSensitive: false,
    unicode: true);

const _number = r'\d(?:[\d   ]*\d)?(?:[.,]\d+)?'; // «1 500», «1.500», «1,5»
final _price = RegExp('$_number(?:\\s*[–—-]\\s*$_number)?'); // a range counts as one price

/// A price as the business wrote it, with the currency where a person would say it — right after the price itself,
/// not after a quantity or a unit, by the website's rule (joop/web/menu.py price_label): "500" -> "500 сом",
/// "3 500 за ночь" -> "3 500 сом за ночь", "800 за 60 минут" -> "800 сом за 60 минут", "1 кг — 450" ->
/// "1 кг — 450 сом", "1 500–2 000" -> "1 500–2 000 сом", "0" -> "бесплатно". A price that names a currency
/// («120 000 $», «500 KGS», «2 000 руб.») or has no price in it («по договорённости», «2 часа») stays as written.
String priceWithSom(String price) {
  final som = S.current.som;
  if (RegExp(r'^0+\s*(сом|kgs|с\.?)?$', caseSensitive: false).hasMatch(price.trim())) {
    return S.current.free; // «0 сом» reads like a mistake
  }
  if (_currency.hasMatch(price) || price.toLowerCase().contains(som.toLowerCase())) return price;
  for (final m in _price.allMatches(price)) {
    if (_unit.matchAsPrefix(price, m.end) == null) {
      return '${price.substring(0, m.end)} $som${price.substring(m.end)}';
    }
  }
  return price; // only quantities, or no number at all
}

/// 1200 -> "1 200 сом".
String formatSom(int value) {
  final digits = value.toString();
  final out = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) out.write(' ');
    out.write(digits[i]);
  }
  return '$out ${S.current.som}';
}
