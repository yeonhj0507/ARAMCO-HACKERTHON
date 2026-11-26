import 'package:flutter/material.dart';

import 'plan_detail.dart' show sName, tName;
import 'theme.dart';
import 'widgets.dart';

/// 검증 시스템 결과를 체크리스트로 보여준다. 항목마다 통과/걸림, 걸린 줄은 사람이 읽는 문장과 막대로.
/// 행 형식 (검증 규칙과 같음)
///   shortage_rows       월,부족kt
///   over_contract_rows  공급원,월,계획척,가능척
///   capacity_rows       기지,월,월말재고kt,저장용량kt
///   safety_rows         기지,월,월말재고kt,안전재고kt
///   mismatch_rows       월,공급원합계kt,요약표kt
class _Rule {
  const _Rule(this.key, this.title, this.desc, {this.blocking = true});
  final String key;
  final String title;
  final String desc;
  final bool blocking; // false면 기록만 (승인은 막지 않음)
}

const _rules = [
  _Rule('over_contract_rows', '계약 한도', '공급원별로 계약된 물량보다 많이 사지 않는지'),
  _Rule('capacity_rows', '저장 용량', '월말 재고가 기지 저장 용량을 넘지 않는지'),
  _Rule('safety_rows', '안전재고', '월말 재고가 안전재고(용량의 15%) 아래로 내려가지 않는지'),
  _Rule('mismatch_rows', '월별 합계', '공급원별 물량 합계와 월별 요약이 맞는지'),
  _Rule('shortage_rows', '수요 충족', '현물까지 사도 모자라는 달이 있는지 (기록만, 승인은 막지 않음)', blocking: false),
];

List<String> _rows(dynamic v) => [for (final x in (v as List? ?? const [])) x.toString()];
num _n(String s) => num.tryParse(s.trim()) ?? 0;

/// 걸린 줄 하나를 문장으로.
String describeRow(String key, String row) {
  final p = row.split(',');
  switch (key) {
    case 'shortage_rows':
      return p.length >= 2 ? '${p[0]} ${num0(_n(p[1]))} kt 부족' : row;
    case 'over_contract_rows':
      return p.length >= 4 ? '${sName(p[0])} ${p[1]}: 계획 ${p[2]}척 > 가능 ${p[3]}척' : row;
    case 'capacity_rows':
      return p.length >= 4 ? '${tName(p[0])} ${p[1]}: 재고 ${num0(_n(p[2]))} kt > 용량 ${num0(_n(p[3]))} kt (${num0(_n(p[2]) - _n(p[3]))} kt 초과)' : row;
    case 'safety_rows':
      return p.length >= 4 ? '${tName(p[0])} ${p[1]}: 재고 ${num0(_n(p[2]))} kt < 안전재고 ${num0(_n(p[3]))} kt (${num0(_n(p[3]) - _n(p[2]))} kt 모자람)' : row;
    case 'mismatch_rows':
      return p.length >= 3 ? '${p[0]}: 공급원 합계 ${num0(_n(p[1]))} kt, 요약 ${num0(_n(p[2]))} kt' : row;
  }
  return row;
}

/// 재고 막대: 용량 대비 재고, 안전재고 위치 표시. capacity/safety 줄에만.
class _StockBar extends StatelessWidget {
  const _StockBar(this.keyName, this.row);
  final String keyName;
  final String row;

  @override
  Widget build(BuildContext context) {
    final p = row.split(',');
    if (p.length < 4) return const SizedBox.shrink();
    final inv = _n(p[2]);
    final ref = _n(p[3]);
    // 용량 초과: 기준 = 용량, 막대 최대 = 재고. 안전재고 미달: 기준 = 안전재고, 막대 최대 = 안전재고 x 2
    final max = keyName == 'capacity_rows' ? (inv > ref ? inv : ref) : ref * 2;
    if (max <= 0) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 4),
      child: LayoutBuilder(
        builder: (c, box) => SizedBox(
          height: 10,
          child: Stack(children: [
            Container(decoration: BoxDecoration(color: C.g100, borderRadius: BorderRadius.circular(5))),
            FractionallySizedBox(
              widthFactor: (inv / max).clamp(0, 1).toDouble(),
              child: Container(decoration: BoxDecoration(color: C.red, borderRadius: BorderRadius.circular(5))),
            ),
            Positioned(
              left: (box.maxWidth * (ref / max).clamp(0, 1).toDouble() - 1).clamp(0, box.maxWidth - 2).toDouble(),
              top: -2,
              bottom: -2,
              child: Container(width: 2, color: C.g900),
            ),
          ]),
        ),
      ),
    );
  }
}

class _RuleTile extends StatelessWidget {
  const _RuleTile(this.rule, this.rows);
  final _Rule rule;
  final List<String> rows;

  @override
  Widget build(BuildContext context) {
    final ok = rows.isEmpty;
    final col = ok ? C.green : (rule.blocking ? C.red : C.orange);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 28,
          height: 28,
          margin: const EdgeInsets.only(right: 12, top: 2),
          decoration: BoxDecoration(color: col.withOpacity(0.12), shape: BoxShape.circle),
          child: Icon(ok ? Icons.check_rounded : (rule.blocking ? Icons.close_rounded : Icons.priority_high_rounded), size: 17, color: col),
        ),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Text(rule.title, style: T.body.copyWith(fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(width: 8),
              Text(ok ? '통과' : '${rows.length}건', style: T.small.copyWith(color: col, fontWeight: FontWeight.w700)),
            ]),
            Text(rule.desc, style: T.small),
            for (final r in rows) ...[
              const SizedBox(height: 6),
              Text(describeRow(rule.key, r), style: T.sub.copyWith(fontSize: 14, color: C.g900)),
              if (rule.key == 'capacity_rows' || rule.key == 'safety_rows') _StockBar(rule.key, r),
            ],
          ]),
        ),
      ]),
    );
  }
}

/// 검증 결과 전체: 맨 위 판정, 아래 항목별 체크리스트, 원본은 접어서.
class CheckView extends StatelessWidget {
  const CheckView(this.check, {super.key, this.showRaw = true});
  final Map<String, dynamic> check;
  final bool showRaw;

  @override
  Widget build(BuildContext context) {
    if (check.isEmpty) return const Text('검증 결과가 없어요', style: T.sub);
    final ok = check['decision'] == '승인 요청';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: ok ? C.greenLight : C.redLight, borderRadius: BorderRadius.circular(12)),
        child: Row(children: [
          Icon(ok ? Icons.verified_rounded : Icons.replay_rounded, color: ok ? C.green : C.red, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '${check['period_start'] ?? ''} ~ ${check['period_end'] ?? ''} 실행안 · ${ok ? '승인 요청 가능' : '다시 계획 필요'}',
              style: T.body.copyWith(fontSize: 15, fontWeight: FontWeight.w700),
            ),
          ),
        ]),
      ),
      const SizedBox(height: 6),
      for (final r in _rules) _RuleTile(r, _rows(check[r.key])),
      if (showRaw) Details(title: '원본 값 보기', child: RawFields(check)),
    ]);
  }
}

/// 재계획의 원인이 된 항목들 (replan_of.violations: {키: [행...]})만 문장으로.
class ViolationList extends StatelessWidget {
  const ViolationList(this.violations, {super.key});
  final Map violations;

  @override
  Widget build(BuildContext context) {
    final items = <Widget>[];
    for (final r in _rules) {
      final rows = _rows(violations[r.key]);
      if (rows.isEmpty) continue;
      items.add(_RuleTile(r, rows));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: items);
  }
}
