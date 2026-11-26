import 'package:flutter/material.dart';

import 'theme.dart';
import 'widgets.dart';

Map<String, dynamic> _m(dynamic x) => x is Map ? Map<String, dynamic>.from(x) : <String, dynamic>{};
List<Map<String, dynamic>> _l(dynamic x) => [for (final e in (x as List? ?? const [])) _m(e)];
num _n(dynamic x) => x is num ? x : num.tryParse('${x ?? ''}') ?? 0;
String _pct(dynamic x) => '${(_n(x) * 100).round()}%';

const _stageNames = {'pre_fid': 'FID 전', 'construction': '건설 중', 'commissioning': '시운전', 'operating': '생산 중'};

/// 5년 조달 계획: 신규 계약 권장, 연도별 조달 구성(현물, 미국 신규, 중동 의존도), 공급원별 비용.
class ProcurementView extends StatelessWidget {
  const ProcurementView(this.p, {super.key, this.effect});
  final Map<String, dynamic> p;
  final Map<String, dynamic>? effect;

  @override
  Widget build(BuildContext context) {
    final contracts = _l(p['new_contracts']);
    final rec = contracts.where((c) => c['recommended'] == true).toList();
    final skip = contracts.where((c) => c['recommended'] != true).toList();
    final years = _l(p['years']);
    final sources = _l(p['sources']);
    final eff = effect;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (eff != null) ...[
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(color: C.greenLight, borderRadius: BorderRadius.circular(14)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('신규 계약 효과 (같은 조건, 기존 계약과 현물로만 샀을 때와 비교)', style: T.small.copyWith(color: C.g700)),
            const SizedBox(height: 8),
            StatRow([
              BigStat('5년 비용 절감', num0(eff['cost_saving_musd']), unit: 'M\$', color: C.green),
              BigStat('현물 구매 감소', num0(eff['spot_kt_reduced']), unit: 'kt'),
              BigStat('${eff['last_year']}년 현물 비중', '${_pct(_m(eff['spot_share_last_year'])['without'])} → ${_pct(_m(eff['spot_share_last_year'])['with'])}'),
            ]),
          ]),
        ),
        const SizedBox(height: 20),
      ],
      if (p['stability_rule'] is Map) ...[_RuleBox(_m(p['stability_rule']), rec), const SizedBox(height: 20)],
      Text(rec.isEmpty ? '권장하는 신규 계약이 없어요' : '신규 계약 권장 ${rec.length}곳', style: T.h3),
      const SizedBox(height: 4),
      for (final c in rec) _ContractRow(c),
      for (final c in skip) _ContractRow(c),
      const SizedBox(height: 20),
      const Text('연도별 조달 구성', style: T.h3),
      const SizedBox(height: 10),
      _YearTable(years),
      const SizedBox(height: 8),
      const Text('장기 비중 = 현물을 뺀 계약 물량의 비율 (원칙 80% 이상). 중동 = 카타르, 오만 장기계약. HHI는 지역 집중도로 낮을수록 다원화돼 있어요.', style: T.small),
      Details(
        title: '공급원별 물량과 평균 단가',
        child: Column(children: [
          for (final s in sources)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(children: [
                Expanded(child: Text('${s['name']}', style: T.sub.copyWith(color: C.g900))),
                SizedBox(width: 110, child: Text('${num0(s['kt'])} kt', style: T.sub, textAlign: TextAlign.right)),
                SizedBox(width: 110, child: Text('${num0(s['cost_musd'])} M\$', style: T.sub, textAlign: TextAlign.right)),
                SizedBox(width: 90, child: Text('${num0(s['avg_usd_t'])} \$/t', style: T.small, textAlign: TextAlign.right)),
              ]),
            ),
        ]),
      ),
    ]);
  }
}

class _ContractRow extends StatelessWidget {
  const _ContractRow(this.c);
  final Map<String, dynamic> c;

  @override
  Widget build(BuildContext context) {
    final rec = c['recommended'] == true;
    final py = _m(c['p_by_year']);
    final lastYear = (py.keys.toList()..sort()).lastOrNull;
    final risk = lastYear == null ? '' : ' · $lastYear년 가동 확률 ${_pct(py[lastYear])}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 40,
          height: 40,
          margin: const EdgeInsets.only(right: 14),
          decoration: BoxDecoration(color: rec ? C.blueLight : C.g100, borderRadius: BorderRadius.circular(12)),
          child: Icon(rec ? Icons.handshake_rounded : Icons.hourglass_empty_rounded, color: rec ? C.blue : C.g500, size: 20),
        ),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${c['name']}', style: T.body.copyWith(fontWeight: FontWeight.w700, color: rec ? C.g900 : C.g500)),
            const SizedBox(height: 2),
            Text(
              rec
                  ? '${c['contract_mtpa']} MTPA 계약 · ${c['first_delivery']}부터 · ${_stageNames[c['stage']] ?? c['stage']}$risk'
                  : '이번 기간에는 계약하지 않아요 · 가동 예정 ${c['online_month'] ?? '-'} · ${_stageNames[c['stage']] ?? c['stage']}$risk',
              style: T.small,
            ),
          ]),
        ),
        if (rec)
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('${num0(c['total_kt'])} kt', style: T.body.copyWith(fontWeight: FontWeight.w700)),
            if (c['saving_vs_spot_musd'] != null)
              Text('현물 대비 -${num0(c['saving_vs_spot_musd'])} M\$', style: T.small.copyWith(color: C.green, fontWeight: FontWeight.w600)),
          ]),
      ]),
    );
  }
}

class _YearTable extends StatelessWidget {
  const _YearTable(this.years);
  final List<Map<String, dynamic>> years;

  @override
  Widget build(BuildContext context) {
    TableRow row(List<String> cells, {bool head = false, Color? bg}) => TableRow(
          decoration: BoxDecoration(color: bg),
          children: [
            for (var i = 0; i < cells.length; i++)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 9),
                child: Text(cells[i],
                    textAlign: i == 0 ? TextAlign.left : TextAlign.right,
                    style: head ? T.small.copyWith(fontWeight: FontWeight.w700, color: C.g700) : T.sub.copyWith(fontSize: 14, color: C.g900)),
              ),
          ],
        );
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: Table(
        border: const TableBorder(horizontalInside: BorderSide(color: C.line)),
        columnWidths: const {0: FlexColumnWidth(0.8)},
        children: [
          row(['연도', '조달 kt', '장기 비중', '현물', '미국 신규', '중동', 'HHI', '평균 \$/t'], head: true, bg: C.g100),
          for (final y in years)
            row([
              '${y['year']}',
              num0(y['total_kt']),
              _pct(y['stable_share']),
              num0(y['spot_kt']),
              num0(y['new_us_kt']),
              _pct(y['middle_east_share']),
              num0(y['hhi']),
              num0(y['avg_usd_t']),
            ], bg: _n(y['stability_gap_kt']) > 0 ? C.orangeLight : null),
        ],
      ),
    );
  }
}

/// 장기(안정) 80% : 현물(단기) 20% 원칙을 지키는지.
class _RuleBox extends StatelessWidget {
  const _RuleBox(this.r, this.rec);
  final Map<String, dynamic> r;
  final List<Map<String, dynamic>> rec;

  @override
  Widget build(BuildContext context) {
    final met = r['met'] == true;
    final gaps = _m(r['gap_years']);
    final years = gaps.keys.toList()..sort();
    final firstNew = rec.map((c) => '${c['first_delivery'] ?? ''}').where((x) => x.isNotEmpty).toList()..sort();
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: met ? C.greenLight : C.orangeLight, borderRadius: BorderRadius.circular(14)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(met ? Icons.verified_rounded : Icons.warning_amber_rounded, size: 18, color: met ? C.green : C.orange),
          const SizedBox(width: 8),
          Expanded(child: Text('조달 원칙: ${r['text']}', style: T.sub.copyWith(fontWeight: FontWeight.w700, color: C.g900))),
        ]),
        const SizedBox(height: 8),
        Text(
          met
              ? '모든 해에 원칙을 지켜요.'
              : '${years.map((y) => '$y년 ${num0(gaps[y])} kt').join(', ')}만큼 장기계약이 모자라요. '
                  '그 해에 최대 ${r['max_gap_mtpa']} MTPA를 장기로 더 확보해야 해요'
                  '${firstNew.isEmpty ? '.' : '. 미국 신규 계약은 ${firstNew.first}부터 들어와요.'}'
                  ' 이 공백을 메울 장기 공급처 후보는 아직 데이터에 없어서, 추가 공급처 자료가 필요해요.',
          style: T.sub.copyWith(color: C.g900),
        ),
      ]),
    );
  }
}
