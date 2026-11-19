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
    // the same cases as the web menu (tests/test_review_fixes_17.py)
    expect(priceWithSom('78 000 \$'), '78 000 \$'); // a realty listing in dollars, was «78 000 сом $»
    expect(priceWithSom('450 \$ в месяц'), '450 \$ в месяц');
    expect(priceWithSom('1 200 USD'), '1 200 USD');
    expect(priceWithSom('90 €'), '90 €');
    expect(priceWithSom('450 у.е. в месяц'), '450 у.е. в месяц');
    expect(priceWithSom('2 000 руб.'), '2 000 руб.');
    expect(priceWithSom('10 000 тенге'), '10 000 тенге');
    expect(priceWithSom('150 за рубашку'), '150 сом за рубашку'); // not roubles
    expect(priceWithSom('от 1 500 до 2 000'), 'от 1 500 до 2 000 сом'); // Altegio's range, was «от 1 500 сом до 2 000»
    expect(priceWithSom('300 до 5 кг'), '300 сом до 5 кг'); // a price and a condition
    expect(priceWithSom('1.500'), '1.500 сом');
    expect(priceWithSom('2.000 за ночь'), '2.000 сом за ночь');
  });
}
