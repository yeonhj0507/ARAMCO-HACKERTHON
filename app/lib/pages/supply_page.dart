import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

/// 공급 전망: Studio A로 읽은 프로젝트를 "2027년 말까지 가동할 가능성" 순서로.
class SupplyPage extends StatefulWidget {
  const SupplyPage({super.key});
  @override
  State<SupplyPage> createState() => _SupplyPageState();
}

class _SupplyPageState extends State<SupplyPage> {
  List<Map<String, dynamic>>? _rows;
  Map<String, dynamic> _plan = {};
  String _filter = 'all';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = Map<String, dynamic>.from(await Api.instance.get('/supply'));
      final p = await Api.instance.get('/plan');
      setState(() {
        _rows = [for (final r in (d['projects'] as List? ?? [])) Map<String, dynamic>.from(r)];
        _plan = Map<String, dynamic>.from(p ?? {});
      });
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  double _p(Map<String, dynamic> r) => ((r['p_2027_12'] as num?) ?? 0).toDouble();

  @override
  Widget build(BuildContext context) {
    final all = _rows ?? [];
    final operating = all.where((r) => r['operating'] == true).length;
    final likely = all.where((r) => _p(r) >= 0.5).length;
    final kr = all.where((r) => ((r['kr_mtpa'] as num?) ?? 0) > 0).length;
    var rows = switch (_filter) {
      'likely' => all.where((r) => _p(r) >= 0.5).toList(),
      'kr' => all.where((r) => ((r['kr_mtpa'] as num?) ?? 0) > 0).toList(),
      _ => all.toList(),
    };
    rows.sort((a, b) => _p(b).compareTo(_p(a)));

    return PageScaffold(
      title: _rows == null ? '불러오는 중이에요' : '2027년 말까지\n$likely곳이 가동할 것 같아요',
      subtitle: '보고서 사이에 일정이 밀린 만큼 불확실성을 크게 잡아 가동 확률을 계산해요.',
      action: IconButton(onPressed: _load, icon: const Icon(Icons.refresh_rounded, color: C.g500)),
      children: [
        Box(
          child: StatRow([
            BigStat('읽은 프로젝트', '${all.length}', unit: '곳'),
            BigStat('지금 생산 중', '$operating', unit: '곳', color: C.green),
            BigStat('한국 계약 물량 확인', '$kr', unit: '곳'),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Choices<String>(
            options: const [('all', '전체'), ('likely', '가동 가능성 높음'), ('kr', '한국 계약 있음')],
            value: _filter,
            onChanged: (v) => setState(() => _filter = v),
          ),
        ),
        Box(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
          child: Column(children: [
            if (rows.isEmpty) const Padding(padding: EdgeInsets.all(16), child: Text('해당하는 프로젝트가 없어요', style: T.sub)),
            for (final r in rows)
              RowItem(
                icon: r['operating'] == true ? Icons.local_fire_department_rounded : Icons.construction_rounded,
                iconColor: r['operating'] == true ? C.green : (_p(r) > 0 ? C.blue : C.g500),
                title: niceName(r['project'].toString()),
                subtitle: [
                  _stage(r['stage']),
                  if (r['online_month'] != null) '가동 ${r['online_month']}',
                  if (((r['kr_mtpa'] as num?) ?? 0) > 0) '한국 ${r['kr_mtpa']} MTPA',
                  if (((r['uncontracted_mtpa'] as num?) ?? 0) > 0) '미계약 ${r['uncontracted_mtpa']} MTPA',
                ].join('  ·  '),
                trailing: Text('${(_p(r) * 100).round()}%',
                    style: T.h3.copyWith(color: _p(r) >= 0.5 ? C.blue : C.g500)),
              ),
          ]),
        ),
        if (_plan.isNotEmpty)
          Box(
            title: '수요와 기지 · ${_plan['plan_name']}',
            child: Details(
              title: 'Studio B가 읽은 값 보기',
              child: RawFields({
                '기준수요 (연도, 도시가스, 발전, 합계 kt)': _plan['base_demand_rows'],
                '기지 (코드, 운영주체, 운영 kt, 계획 kt)': _plan['terminal_rows'],
              }),
            ),
          ),
      ],
    );
  }

  static String _stage(dynamic s) => switch (s?.toString()) {
        'operating' => '상업운전',
        'commissioning' => '시운전',
        'construction' => '건설 중',
        'pre_fid' => '투자 결정 전',
        _ => '단계 미상',
      };
}
