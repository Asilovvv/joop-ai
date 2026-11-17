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

/// A price as the business wrote it, with the currency where a person would say it: right after the (last) number.
/// "500" -> "500 сом", "от 3 500" -> "от 3 500 сом", "3 500 за ночь" -> "3 500 сом за ночь", "0" -> "бесплатно"; a price that already names
/// the currency, or has no number («по договорённости»), stays as written.
String priceWithSom(String price) {
  final som = S.current.som;
  if (RegExp(r'^0+$').hasMatch(price.trim())) return S.current.free; // «0 сом» reads like a mistake
  if (price.isEmpty || !RegExp(r'\d').hasMatch(price) || price.contains('сом') || price.contains(som)) return price;
  final last = RegExp(r'\d(?:[\d\u00a0 .,]*\d)?').allMatches(price).last;
  return '${price.substring(0, last.end)} $som${price.substring(last.end)}';
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
