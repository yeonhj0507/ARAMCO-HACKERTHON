import 'package:flutter/material.dart';

import 'api.dart';
import 'theme.dart';
import 'widgets.dart';

const terminalNames = {
  'INCHEON': '인천',
  'PYEONGTAEK': '평택',
  'TONGYEONG': '통영',
  'SAMCHEOK': '삼척',
  'DANGJIN': '당진',
  'JEJU': '제주',
  'BORYEONG': '보령',
  'GWANGYANG': '광양',
  'YEOSU': '여수',
  'ULSAN': '울산',
  'TONGYEONG_PRIVATE': '통영(민간)',
};
const sourceNames = {
  'QATAR_LT': '카타르 장기',
  'OMAN_LT': '오만 장기',
  'AUSTRALIA_LT': '호주 장기',
  'MALAYSIA_LT': '말레이시아 장기',
  'OTHER_LT': '기타 장기',
  'US_LT': '미국 장기',
  'US_UNCONTRACTED': '미국 무계약',
  'SPOT': '현물',
};
String tName(dynamic t) => terminalNames[t?.toString()] ?? (t?.toString() ?? '-');
String sName(dynamic s) {
  final v = s?.toString() ?? '-';
  if (v.startsWith('US_NEW_')) return '미국 신규 ${v.substring(7).replaceAll('_LLC', '').replaceAll('_', ' ')}';
  return sourceNames[v] ?? v;
}

Map<String, dynamic> _m(dynamic x) => x is Map ? Map<String, dynamic>.from(x) : <String, dynamic>{};
List<Map<String, dynamic>> _l(dynamic x) => [for (final e in (x as List? ?? const [])) _m(e)];
num _n(dynamic x) => x is num ? x : num.tryParse('${x ?? ''}') ?? 0;
String _c(dynamic x) {
  final v = _n(x);
  return v == v.roundToDouble() ? '${v.round()}' : v.toStringAsFixed(1);
}

/// 계획의 월별, 기지별 배분. 어느 기지에 어디서 몇 척, 월말 재고, 부족, 추가 구매.
class PlanDetailView extends StatefulWidget {
  const PlanDetailView(this.d, {super.key});
  final Map<String, dynamic> d;
  @override
  State<PlanDetailView> createState() => _PlanDetailViewState();
}

class _PlanDetailViewState extends State<PlanDetailView> {
  int _mi = 0;

  @override
  Widget build(BuildContext context) {
    final months = _l(widget.d['months']);
    if (months.isEmpty) return const Text('배분 내용이 없어요', style: T.sub);
    final m = months[_mi.clamp(0, months.length - 1)];
    final short = _n(m['shortage_kt']);
    final terms = _l(m['terminals']);
    final buys = _l(m['purchases']);
    final bySrc = _l(m['by_source']);
    final buyTotals = <String, List<num>>{};
    for (final b in buys) {
      final v = buyTotals.putIfAbsent(b['source'].toString(), () => [0, 0, 0]);
      v[0] += _n(b['cargoes']);
      v[1] += _n(b['kt']);
      v[2] += _n(b['cost_musd']);
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (months.length > 1) ...[
        Choices<int>(
          options: [for (var i = 0; i < months.length; i++) (i, months[i]['month'].toString())],
          value: _mi,
          onChanged: (v) => setState(() => _mi = v),
        ),
        const SizedBox(height: 16),
      ],
      StatRow([
        BigStat('수요', num0(m['demand_kt']), unit: 'kt'),
        BigStat('들여오는 양', num0(m['planned_kt']), unit: 'kt'),
        BigStat('부족', num0(short), unit: 'kt', color: short > 0 ? C.red : null),
      ]),
      if (short > 0)
        Container(
          margin: const EdgeInsets.only(top: 12),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: C.redLight, borderRadius: BorderRadius.circular(12)),
          child: Text('현물까지 최대로 사도 ${num0(short)} kt가 모자라요. 다시 계획해도 줄지 않는 양이라 검증 시스템은 기록만 하고 승인 요청을 냈어요. '
              '수요 조정이나 다른 기관과의 물량 교환이 필요해요.', style: T.sub.copyWith(color: C.g900)),
        ),
      const SizedBox(height: 24),
      const Text('어디서 사나', style: T.h3),
      const SizedBox(height: 4),
      for (final s in bySrc) _SourceRow(s, kind: _kind(s['source'])),
      const SizedBox(height: 20),
      Text(buyTotals.isEmpty ? '추가 구매 없음' : '추가 구매 비용', style: T.h3),
      const SizedBox(height: 4),
      for (final e in buyTotals.entries)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(children: [
            Expanded(child: Text(sName(e.key), style: T.body.copyWith(fontSize: 15))),
            Text('${_c(e.value[0])}척 · ${num0(e.value[1])} kt · ', style: T.sub),
            Text('${num0(e.value[2])} M\$', style: T.body.copyWith(fontSize: 15, fontWeight: FontWeight.w700)),
          ]),
        ),
      Details(
        title: '받는 기지와 월말 재고 (하역 가능 여부 검토)',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('산 물량을 실제로 받을 수 있는지(저장 용량, 안전재고, 하역 횟수) 확인하는 참고 정보예요. 검증 시스템이 이 기준으로 실행안을 검사해요.',
              style: T.small),
          for (final t in terms) _TerminalTile(t),
        ]),
      ),
    ]);
  }
}

class _TerminalTile extends StatefulWidget {
  const _TerminalTile(this.t);
  final Map<String, dynamic> t;
  @override
  State<_TerminalTile> createState() => _TerminalTileState();
}

class _TerminalTileState extends State<_TerminalTile> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final t = widget.t;
    final inflow = _l(t['inflow']);
    final cap = _n(t['capacity_kt']);
    final inv = _n(t['inventory_kt']);
    final safe = _n(t['safety_kt']);
    final short = _n(t['shortage_kt']);
    final low = cap > 0 && inv < safe;
    return InkWell(
      onTap: inflow.isEmpty ? null : () => setState(() => _open = !_open),
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            SizedBox(width: 92, child: Text(tName(t['terminal']), style: T.body.copyWith(fontWeight: FontWeight.w700))),
            Expanded(
              child: Text(
                  inflow.isEmpty ? '입고 없음 · 수요 ${num0(t['demand_kt'])} kt' : '${_c(t['inflow_cargoes'])}척 입고 (${num0(t['inflow_kt'])} kt) · 수요 ${num0(t['demand_kt'])} kt',
                  style: T.sub.copyWith(fontSize: 14)),
            ),
            if (short > 0) Pill('부족 ${num0(short)} kt', tone: Tone.bad),
            if (inflow.isNotEmpty) Icon(_open ? Icons.expand_less_rounded : Icons.expand_more_rounded, color: C.g300),
          ]),
          if (cap > 0) ...[
            const SizedBox(height: 8),
            Row(children: [
              const SizedBox(width: 92),
              Expanded(
                child: LayoutBuilder(
                  builder: (c, box) => Stack(children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(4),
                      child: LinearProgressIndicator(
                        value: (inv / cap).clamp(0, 1).toDouble(),
                        minHeight: 8,
                        backgroundColor: C.g100,
                        color: low ? C.orange : C.blue,
                      ),
                    ),
                    // 안전재고 위치 표시
                    Positioned(left: box.maxWidth * (safe / cap).clamp(0, 1) - 1, top: 0, bottom: 0, child: Container(width: 2, color: C.g700)),
                  ]),
                ),
              ),
              const SizedBox(width: 10),
              SizedBox(
                width: 150,
                child: Text('월말 ${num0(inv)} / ${num0(cap)} kt', style: T.small, textAlign: TextAlign.right),
              ),
            ]),
          ],
          if (_open)
            Padding(
              padding: const EdgeInsets.only(left: 92, top: 8),
              child: Column(children: [
                for (final f in inflow)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(children: [
                      Expanded(child: Text(sName(f['source']), style: T.sub.copyWith(fontSize: 14, color: C.g900))),
                      Text('${_c(f['cargoes'])}척 · ${num0(f['kt'])} kt', style: T.sub.copyWith(fontSize: 14)),
                    ]),
                  ),
              ]),
            ),
        ]),
      ),
    );
  }
}

/// 바텀시트로 계획 상세 보기.
Future<void> planDetailSheet(BuildContext context, String orderId) async {
  Map<String, dynamic>? d;
  try {
    d = Map<String, dynamic>.from(await Api.instance.get('/orders/$orderId/detail'));
  } catch (e) {
    if (context.mounted) showError(context, e);
  }
  if (d == null || !context.mounted) return;
  final data = d;
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    constraints: const BoxConstraints(maxWidth: 760),
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    builder: (c) => SizedBox(
      height: MediaQuery.of(c).size.height * 0.88,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(28),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            const Expanded(child: Text('조달 상세', style: T.h2)),
            IconButton(onPressed: () => Navigator.pop(c), icon: const Icon(Icons.close_rounded)),
          ]),
          Text('${scen(data)} · 추가 구매 ${_c(_m(data['purchase_total'])['cargoes'])}척, ${num0(_m(data['purchase_total'])['cost_musd'])}M\$',
              style: T.small),
          const SizedBox(height: 20),
          PlanDetailView(data),
        ]),
      ),
    ),
  );
}

String _kind(dynamic s) {
  final v = s?.toString() ?? '';
  if (v == 'SPOT') return '현물 (단기)';
  if (v.startsWith('US_NEW_')) return '신규 장기계약';
  return '장기계약';
}

class _SourceRow extends StatelessWidget {
  const _SourceRow(this.s, {required this.kind});
  final Map<String, dynamic> s;
  final String kind;

  @override
  Widget build(BuildContext context) {
    final spot = kind.startsWith('현물');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          margin: const EdgeInsets.only(right: 12),
          decoration: BoxDecoration(color: spot ? C.orangeLight : C.blueLight, borderRadius: BorderRadius.circular(6)),
          child: Text(kind, style: T.small.copyWith(color: spot ? C.orange : C.blue, fontWeight: FontWeight.w700)),
        ),
        Expanded(child: Text(sName(s['source']), style: T.body.copyWith(fontSize: 15))),
        Text('${_c(s['cargoes'])}척 · ${num0(s['kt'])} kt', style: T.sub),
      ]),
    );
  }
}
