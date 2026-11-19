import 'package:flutter_test/flutter_test.dart';
import 'package:joop_mobile/core/format.dart';
import 'package:joop_mobile/core/strings.dart';

void main() {
  test('the currency goes right after the price number, as a person says it', () {
    S.current = S.ru;
    expect(priceWithSom('500'), '500 сом');
    expect(priceWithSom('от 3 500'), 'от 3 500 сом');
    expect(priceWithSom('3 500 за ночь'), '3 500 сом за ночь'); // was «3 500 за ночь сом»
    expect(priceWithSom('4 000 в одну сторону'), '4 000 сом в одну сторону');
    expect(priceWithSom('1 500–2 000'), '1 500–2 000 сом');
    expect(priceWithSom('250 сом/кг'), '250 сом/кг'); // already named
    expect(priceWithSom('по договорённости'), 'по договорённости');
    expect(priceWithSom(''), '');
    expect(priceWithSom('0'), 'бесплатно'); // was «0 сом»
    expect(priceWithSom('0 сом'), 'бесплатно');
    expect(priceWithSom('800 за 60 минут'), '800 сом за 60 минут'); // was «800 за 60 сом минут»
    expect(priceWithSom('250 за 1 кг'), '250 сом за 1 кг');
    expect(priceWithSom('200–300'), '200–300 сом');
    expect(priceWithSom('200 - 300 за час'), '200 - 300 сом за час');
    expect(priceWithSom('500 KGS'), '500 KGS');
    expect(priceWithSom('500 с.'), '500 с.');
    expect(priceWithSom('500 Сом'), '500 Сом');
    expect(priceWithSom('1,5'), '1,5 сом');
    // the website's rule (joop/web/menu.py price_label, tests/test_review_241_247.py): a currency the business named
    for (final price in ['120 000 \$', '450 \$ в месяц', '\$300', '100 USD', '50 €', '1 000 ₸', '500 руб', '90 000 тенге',
        '300 KGS', '450 у.е. в месяц']) {
      expect(priceWithSom(price), price);
    }
    expect(priceWithSom('150 за рубашку'), '150 сом за рубашку'); // «руб» inside a word is not roubles
    // decimals, and a quantity before the price
    expect(priceWithSom('1,500'), '1,500 сом');
    expect(priceWithSom('1.500'), '1.500 сом');
    expect(priceWithSom('2,5'), '2,5 сом');
    expect(priceWithSom('1 кг — 450'), '1 кг — 450 сом'); // was «1 сом кг — 450»
    expect(priceWithSom('0,5 л — 120'), '0,5 л — 120 сом');
    expect(priceWithSom('60 минут — 1 200'), '60 минут — 1 200 сом');
    expect(priceWithSom('2 часа'), '2 часа'); // no price in it
  });

  test('phones read with spaces, as in the panel', () {
    expect(formatPhone('+996777444555'), '+996 777 444 555');
    expect(formatPhone('+77011234567'), '+7 701 123 45 67');
    expect(formatPhone('+996 555 000 001'), '+996 555 000 001'); // already as the business typed it
    expect(formatPhone('+4915112345678'), '+4915112345678');
    expect(formatPhone(''), '');
  });

  test('Russian forms after a number', () {
    String f(int n) => ruForm(n, 'диалог', 'диалога', 'диалогов');
    expect([0, 1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 101, 111, 112, 122].map(f).toList(), [
      'диалогов', 'диалог', 'диалога', 'диалога', 'диалогов', 'диалогов', 'диалогов', 'диалогов', 'диалог', 'диалога',
      'диалогов', 'диалог', 'диалогов', 'диалогов', 'диалога'
    ]);
  });
}
