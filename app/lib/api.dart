import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// 백엔드 주소. 실행할 때 --dart-define=API_BASE=http://다른주소:8000 으로 바꿀 수 있다.
const String apiBase = String.fromEnvironment('API_BASE', defaultValue: 'http://localhost:8000');

class ApiError implements Exception {
  ApiError(this.message);
  final String message;
  @override
  String toString() => message;
}

class Api {
  Api._();
  static final Api instance = Api._();

  Uri _u(String path, [Map<String, String>? q]) => Uri.parse('$apiBase$path').replace(queryParameters: q);

  dynamic _decode(http.Response r) {
    final body = utf8.decode(r.bodyBytes);
    if (r.statusCode >= 400) {
      try {
        throw ApiError((jsonDecode(body) as Map)['detail'].toString());
      } on FormatException {
        throw ApiError('HTTP ${r.statusCode}: $body');
      }
    }
    return body.isEmpty ? null : jsonDecode(body);
  }

  Future<dynamic> get(String path, [Map<String, String>? q]) async =>
      _decode(await http.get(_u(path, q)).timeout(const Duration(seconds: 60)));

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async => _decode(await http
      .post(_u(path), headers: {'Content-Type': 'application/json'}, body: jsonEncode(body ?? {}))
      .timeout(const Duration(minutes: 3)));

  Future<Map<String, dynamic>> upload(String kind, String filename, List<int> bytes) async {
    final req = http.MultipartRequest('POST', _u('/documents/upload'))
      ..fields['kind'] = kind
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    final res = await http.Response.fromStream(await req.send());
    return Map<String, dynamic>.from(_decode(res));
  }

  /// 채팅 첨부: 저장만 하고 경로를 돌려준다. 읽는 건 에이전트가 한다.
  Future<Map<String, dynamic>> chatUpload(String filename, List<int> bytes) async {
    final req = http.MultipartRequest('POST', _u('/chat/upload'))
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    final res = await http.Response.fromStream(await req.send());
    return Map<String, dynamic>.from(_decode(res));
  }

  /// 작업이 끝날 때까지 2초마다 조회한다. onUpdate로 진행 로그를 받는다.
  Future<Map<String, dynamic>> waitJob(String id,
      {void Function(Map<String, dynamic>)? onUpdate, Duration interval = const Duration(seconds: 2)}) async {
    while (true) {
      final j = Map<String, dynamic>.from(await get('/jobs/$id'));
      onUpdate?.call(j);
      if (j['status'] != 'running') return j;
      await Future.delayed(interval);
    }
  }

  Uri fileUrl(String relPath) => _u('/files', {'path': relPath});
}
