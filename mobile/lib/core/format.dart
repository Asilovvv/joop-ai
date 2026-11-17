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

/// "1 запись", "2 записи", "5 записей"; "5 жазылуу".
String bookingsWord(int n) => S.current.bookingsCount(n);

/// A price as the business wrote it, with the currency where a person would say it: right after the price itself — the
/// first number, or a range of them. "500" -> "500 сом", "от 3 500" -> "от 3 500 сом", "3 500 за ночь" ->
/// "3 500 сом за ночь", "800 за 60 минут" -> "800 сом за 60 минут", "200–300" -> "200–300 сом", "0" -> "бесплатно".
/// A price that already names the currency (сом, KGS, с.), or has no number («по договорённости»), stays as written.
String priceWithSom(String price) {
  final som = S.current.som;
  if (RegExp(r'^0+\s*(сом|kgs|с\.?)?$', caseSensitive: false).hasMatch(price.trim())) {
    return S.current.free; // «0 сом» reads like a mistake
  }
  final named = RegExp(r'сом|kgs|\d\s*с\.|' + RegExp.escape(som), caseSensitive: false).hasMatch(price);
  if (price.isEmpty || !RegExp(r'\d').hasMatch(price) || named) return price;
  const number = r'\d(?:[\d\u00a0 ]*\d)?(?:[.,]\d+)?';
  final first = RegExp('$number(?:\\s*[–—-]\\s*$number)?').firstMatch(price)!;
  return '${price.substring(0, first.end)} $som${price.substring(first.end)}';
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
