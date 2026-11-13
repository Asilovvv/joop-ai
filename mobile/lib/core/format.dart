String _two(int n) => n.toString().padLeft(2, '0');

const _weekdays = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];
const _months = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

/// 09:30
String formatTime(DateTime d) => '${_two(d.hour)}:${_two(d.minute)}';

/// пт, 13 ноя
String formatDay(DateTime d) => '${_weekdays[d.weekday - 1]}, ${d.day} ${_months[d.month - 1]}';

/// The channel a customer wrote from, as the panel names it.
String channelName(String channel) => switch (channel) {
      'telegram' => 'Telegram',
      'whatsapp' => 'WhatsApp',
      'instagram' => 'Instagram',
      'web' => 'Сайт',
      '' => 'Вручную',
      _ => channel,
    };

/// "1 запись", "2 записи", "5 записей".
String bookingsWord(int n) {
  final last2 = n % 100, last = n % 10;
  if (last2 >= 11 && last2 <= 14) return '$n записей';
  if (last == 1) return '$n запись';
  if (last >= 2 && last <= 4) return '$n записи';
  return '$n записей';
}
