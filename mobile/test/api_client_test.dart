import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:joop_mobile/core/api_client.dart';

void main() {
  test('plain http only to this device or the same Wi-Fi', () {
    for (final ok in [
      'https://joop.kg',
      'http://localhost:8000',
      'http://10.0.2.2:8000',
      'http://192.168.1.5:8000',
      'http://172.20.10.2:8000',
      'http://10.1.2.3',
      'http://my-laptop.local:8000',
    ]) {
      expect(ApiClient.allowed(ok), isTrue, reason: ok);
    }
    for (final no in [
      'http://joop.kg', 'http://8.8.8.8', 'http://172.32.0.1', 'http://192.169.1.1', 'ftp://joop.kg',
      'http://010.8.8.8', // the system reads it as octal: 8.8.8.8
      'http://0127.0.0.1', // 87.0.0.1
      'http://0x0a.0.0.1', // hex
      'http://10.0.0.256',
    ]) {
      expect(ApiClient.allowed(no), isFalse, reason: no);
    }
  });

  test('a public http address is refused before anything is sent', () async {
    var calls = 0;
    final api = ApiClient(
      baseUrl: 'http://joop.kg',
      httpClient: MockClient((_) async {
        calls++;
        return http.Response('{}', 200);
      }),
    );
    await expectLater(
      api.post('/api/mobile/login', {'password': 'secret'}),
      throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('https://'))),
    );
    expect(calls, 0); // the password never left the phone
  });

  test('an address typed without a scheme gets http on the local network and https elsewhere', () {
    final api = ApiClient(baseUrl: 'https://joop.kg', httpClient: MockClient((_) async => http.Response('{}', 200)));
    api.baseUrl = '192.168.1.5:8000/';
    expect(api.baseUrl, 'http://192.168.1.5:8000');
    api.baseUrl = 'joop.kg';
    expect(api.baseUrl, 'https://joop.kg');
  });
}
