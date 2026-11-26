import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

const _kinds = {
  'A': ('미국 LNG 보고서', '가동 시점, 일정 지연, 한국 계약, 미계약 물량을 읽어요', Icons.description_rounded, C.blue),
  'C': ('배분 실행안', '승인 전에 용량, 안전재고, 계약, 합계를 검사해요', Icons.rule_rounded, C.orange),
};

/// 문서 읽기: 종류 고르기 -> 파일 고르기 -> 읽기 -> 결과
class ReadPage extends StatefulWidget {
  const ReadPage({super.key});
  @override
  State<ReadPage> createState() => _ReadPageState();
}

class _ReadPageState extends State<ReadPage> {
  String? _kind;
  String? _file;
  Map<String, List<String>> _samples = {};
  Map<String, dynamic>? _job;
  bool _running = false;

  @override
  void initState() {
    super.initState();
    Api.instance.get('/samples').then((s) {
      if (mounted) setState(() => _samples = (s as Map).map((k, v) => MapEntry(k.toString(), List<String>.from(v))));
    }).catchError((e) {
      if (mounted) showError(context, e);
    });
  }

  Future<void> _start(Future<dynamic> Function() starter) async {
    setState(() {
      _running = true;
      _job = null;
    });
    try {
      final j = Map<String, dynamic>.from(await starter());
      final done = await Api.instance.waitJob(j['id'], onUpdate: (u) {
        if (mounted) setState(() => _job = u);
      });
      setState(() => _job = done);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  Future<void> _upload() async {
    final picked = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['pdf'], withData: true);
    final f = picked?.files.single;
    if (f == null || f.bytes == null) return;
    await _start(() => Api.instance.upload(_kind!, f.name, f.bytes!));
  }

  void _reset() => setState(() {
        _job = null;
        _file = null;
      });

  String _fileLabel(String path) {
    final name = path.split('/').last.replaceAll('.pdf', '');
    if (path.contains('a_cases/')) return niceName(name);
    if (path.startsWith('submission/')) return '채점용 ${name.split('_').last}';
    if (path.contains('allocations/')) return '테스트 실행안 ${name.replaceAll('C_set', '')}';
    return name.replaceAll('_', ' ');
  }

  @override
  Widget build(BuildContext context) {
    final done = _job != null && _job!['status'] != 'running';
    if (_running || (_job != null && !done)) {
      return PageScaffold(title: '문서를 읽고 있어요', children: [Working(_job)]);
    }
    if (done) return _result();

    // 1단계: 종류 고르기
    if (_kind == null) {
      return PageScaffold(
        title: '어떤 문서를 읽을까요?',
        subtitle: 'Upstage Studio 워크플로우가 문서를 읽고 최적화에 넣을 값으로 바꿔요.',
        children: [
          Box(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
            child: Column(children: [
              for (final e in _kinds.entries)
                RowItem(
                  icon: e.value.$3,
                  iconColor: e.value.$4,
                  title: e.value.$1,
                  subtitle: '워크플로우 ${e.key} · ${e.value.$2}',
                  onTap: () => setState(() => _kind = e.key),
                ),
            ]),
          ),
        ],
      );
    }

    // 2단계: 파일 고르기
    final files = _samples[_kind] ?? [];
    return PageScaffold(
      title: '${_kinds[_kind]!.$1}를\n골라주세요',
      subtitle: _kinds[_kind]!.$2,
      action: TextButton(onPressed: () => setState(() => _kind = null), child: const Text('종류 다시 고르기')),
      bottom: Row(children: [
        Expanded(child: SecondaryButton('PDF 올리기', onPressed: _upload)),
        const SizedBox(width: 12),
        Expanded(
          flex: 2,
          child: PrimaryButton(_file == null ? '파일을 골라주세요' : '읽기 시작',
              onPressed: _file == null
                  ? null
                  : () => _start(() => Api.instance.post('/documents/run', {'kind': _kind, 'path': _file}))),
        ),
      ]),
      children: [
        Box(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Column(children: [
            if (files.isEmpty) const Padding(padding: EdgeInsets.all(16), child: Text('준비된 문서가 없어요. PDF를 올려주세요.', style: T.sub)),
            for (final f in files)
              InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () => setState(() => _file = f),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
                  decoration: BoxDecoration(
                    color: f == _file ? C.blueLight : null,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(children: [
                    Icon(f == _file ? Icons.radio_button_checked : Icons.radio_button_off,
                        color: f == _file ? C.blue : C.g300, size: 22),
                    const SizedBox(width: 12),
                    Expanded(child: Text(_fileLabel(f), style: T.body)),
                    IconButton(
                      tooltip: '원문 보기',
                      onPressed: () => openUrl(Api.instance.fileUrl(f)),
                      icon: const Icon(Icons.open_in_new_rounded, size: 18, color: C.g500),
                    ),
                  ]),
                ),
              ),
          ]),
        ),
      ],
    );
  }

  Widget _result() {
    if (_job!['status'] == 'error') {
      return PageScaffold(title: '읽지 못했어요', subtitle: _job!['error']?.toString(), bottom: PrimaryButton('다시 하기', onPressed: _reset), children: const []);
    }
    final r = Map<String, dynamic>.from(_job!['result'] ?? {});
    final f = Map<String, dynamic>.from(r['fields'] ?? {});
    final kind = r['kind']?.toString() ?? _kind;
    final children = <Widget>[];
    late ResultHead head;

    if (kind == 'A') {
      final ok = f['config_status'] == '반영';
      head = ResultHead(ok: ok, title: ok ? '그대로 반영할게요' : '사람 확인이 필요해요', body: f['reason']?.toString());
      children.add(Box(
        child: Column(children: [
          StatRow([
            BigStat('단계', _stage(f['stage'])),
            BigStat('가동 시작', (f['online_month'] ?? '').toString().isEmpty ? '미정' : f['online_month'].toString()),
          ]),
          const SizedBox(height: 20),
          StatRow([
            BigStat('일정 지연', '${f['slip_months'] ?? 0}', unit: '개월', color: (f['slip_months'] ?? 0) > 0 ? C.orange : null),
            BigStat('한국 구매자', (f['kr_buyers'] as List?)?.isNotEmpty == true ? (f['kr_buyers'] as List).join(', ') : '없음'),
          ]),
        ]),
      ));
    } else if (kind == 'B') {
      final ok = f['config_status'] == '반영';
      final rows = List<String>.from(f['base_demand_rows'] ?? const []);
      final first = rows.isNotEmpty ? rows.first.split(',') : <String>[];
      head = ResultHead(ok: ok, title: ok ? '수급계획을 반영했어요' : '사람 확인이 필요해요', body: f['reason']?.toString());
      children.add(Box(
        child: StatRow([
          BigStat('계획 기간', '${f['plan_start_year']}~${f['plan_end_year']}'),
          BigStat('기지', '${(f['terminal_rows'] as List?)?.length ?? 0}', unit: '곳'),
          if (first.length >= 4) BigStat('${first[0]}년 수요', num0(num.tryParse(first[3])), unit: 'kt'),
        ]),
      ));
    } else {
      final ok = f['decision'] == '승인 요청';
      final disagree = List<String>.from(r['disagree'] ?? const []);
      head = ResultHead(
          ok: ok,
          title: ok ? '문제 없어요. 승인을 요청할게요' : '문제가 있어 다시 계획해야 해요',
          body: f['reason']?.toString());
      final issues = <(String, String, List)>[
        ('계약보다 많이 잡은 카고', 'over_contract_rows', f['over_contract_rows'] as List? ?? []),
        ('저장용량을 넘는 재고', 'capacity_rows', f['capacity_rows'] as List? ?? []),
        ('안전재고보다 낮은 재고', 'safety_rows', f['safety_rows'] as List? ?? []),
        ('표끼리 맞지 않는 합계', 'mismatch_rows', f['mismatch_rows'] as List? ?? []),
        ('부족한 물량', 'shortage_rows', f['shortage_rows'] as List? ?? []),
      ];
      children.add(Box(
        child: StatRow([
          BigStat('계획 물량', num0(f['total_planned_kt']), unit: 'kt'),
          BigStat('현물 구매', '${f['spot_cargoes'] ?? 0}', unit: '척'),
        ]),
      ));
      children.add(Box(
        title: '검사 항목',
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 12),
        child: Column(children: [
          for (final (name, _, rows) in issues)
            RowItem(
              icon: rows.isEmpty ? Icons.check_circle_rounded : Icons.error_rounded,
              iconColor: rows.isEmpty ? C.green : C.orange,
              title: name,
              subtitle: rows.isEmpty ? '없어요' : rows.join('  ·  '),
            ),
        ]),
      ));
      if (r['code_check'] != null) {
        children.add(Box(
          child: RowItem(
            icon: disagree.isEmpty ? Icons.handshake_rounded : Icons.compare_arrows_rounded,
            iconColor: disagree.isEmpty ? C.green : C.red,
            title: disagree.isEmpty ? '코드로 다시 계산해도 같은 판정이에요' : 'Studio와 코드 검산이 달라요',
            subtitle: disagree.isEmpty ? 'Studio 판정과 규칙 계산을 서로 맞춰봤어요' : '다른 항목: ${disagree.join(', ')}',
          ),
        ));
      }
      final replan = r['replan'] as Map?;
      if (replan != null) {
        children.add(Box(
          child: RowItem(
            icon: Icons.autorenew_rounded,
            title: '최신 입력으로 다시 계획했어요',
            subtitle: '새 실행안도 Studio C로 검사했어요 · 주문 초안 ${(replan['order'] as Map?)?['order_id']}',
            trailing: Pill.of(replan['status']?.toString()),
          ),
        ));
      }
    }

    return PageScaffold(
      title: '',
      bottom: Row(children: [
        Expanded(child: SecondaryButton('같은 종류 더 읽기', onPressed: _reset)),
        const SizedBox(width: 12),
        Expanded(
            child: PrimaryButton('처음으로',
                onPressed: () => setState(() {
                      _kind = null;
                      _job = null;
                      _file = null;
                    }))),
      ]),
      children: [
        head,
        ...children,
        Box(child: Details(title: 'Studio 출력 원본 보기', child: RawFields(f, highlight: Set<String>.from(r['disagree'] ?? const [])))),
      ],
    );
  }

  static String _stage(dynamic s) => switch (s?.toString()) {
        'operating' => '상업운전',
        'commissioning' => '시운전',
        'construction' => '건설 중',
        'pre_fid' => '투자 결정 전',
        _ => '-',
      };
}
