import 'package:flutter/material.dart';

/// 색과 글자 크기. 흰 카드, 연회색 바탕, 파란 강조 한 가지만 쓴다.
class C {
  static const blue = Color(0xFF3182F6);
  static const blueLight = Color(0xFFE8F3FF);
  static const bg = Color(0xFFF2F4F6);
  static const card = Colors.white;
  static const line = Color(0xFFE5E8EB);
  static const g900 = Color(0xFF191F28);
  static const g700 = Color(0xFF4E5968);
  static const g500 = Color(0xFF8B95A1);
  static const g300 = Color(0xFFD1D6DB);
  static const g100 = Color(0xFFF2F4F6);
  static const green = Color(0xFF15B886);
  static const greenLight = Color(0xFFE5F8F1);
  static const orange = Color(0xFFFF8A00);
  static const orangeLight = Color(0xFFFFF3E0);
  static const red = Color(0xFFF04452);
  static const redLight = Color(0xFFFEECEE);
}

class T {
  static const _f = 'Pretendard';
  static const h1 = TextStyle(fontFamily: _f, fontSize: 28, height: 1.35, fontWeight: FontWeight.w700, color: C.g900);
  static const h2 = TextStyle(fontFamily: _f, fontSize: 22, height: 1.4, fontWeight: FontWeight.w700, color: C.g900);
  static const h3 = TextStyle(fontFamily: _f, fontSize: 18, height: 1.4, fontWeight: FontWeight.w700, color: C.g900);
  static const body = TextStyle(fontFamily: _f, fontSize: 16, height: 1.5, fontWeight: FontWeight.w500, color: C.g900);
  static const sub = TextStyle(fontFamily: _f, fontSize: 15, height: 1.5, fontWeight: FontWeight.w400, color: C.g700);
  static const small = TextStyle(fontFamily: _f, fontSize: 13, height: 1.45, fontWeight: FontWeight.w400, color: C.g500);
  static const num = TextStyle(fontFamily: _f, fontSize: 30, fontWeight: FontWeight.w700, color: C.g900, height: 1.2);
  static const mono = TextStyle(fontFamily: 'Consolas', fontSize: 13, color: C.g700, height: 1.5);
}

ThemeData buildTheme() {
  return ThemeData(
    useMaterial3: true,
    fontFamily: 'Pretendard',
    scaffoldBackgroundColor: C.bg,
    colorScheme: ColorScheme.fromSeed(seedColor: C.blue, primary: C.blue, surface: Colors.white),
    splashFactory: InkRipple.splashFactory,
    dividerColor: C.line,
    snackBarTheme: const SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: C.g900,
      contentTextStyle: TextStyle(fontFamily: 'Pretendard', fontSize: 15, color: Colors.white),
    ),
  );
}
