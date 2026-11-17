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
  });
}
