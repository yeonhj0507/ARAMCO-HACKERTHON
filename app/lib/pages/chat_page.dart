import 'dart:convert';
import 'dart:math';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../api.dart';
import '../chat_cards.dart';
import '../theme.dart';
import '../widgets.dart';

/// 기본 화면. 말로 시키면 에이전트가 도구를 골라 쓰고, 결과는 카드로 보인다.
/// 반영, 승인 같은 사람의 결정은 카드의 버튼으로 한다.
class ChatPage extends StatefulWidget {
  const ChatPage({super.key, this.onChanged});
  final VoidCallback? onChanged;

  /// 새 대화: 화면 기록과 서버 쪽 대화 문맥을 같이 비운다.
  static void reset() {
    _ChatPageState._msgs.clear();
    _ChatPageState._session = _ChatPageState._newSession();
  }

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _Step {
  _Step(this.name, this.label, this.running, this.args);
  final String name;
  final String label;
  final String running;
  final Map<String, dynamic> args;
  bool done = false;
  double? seconds;
  String? summary;
  dynamic result;
  Map<String, dynamic>? card;
}

class _Msg {
  _Msg.user(this.text, {this.file}) : mine = true;
  _Msg.agent()
      : mine = false,
        text = '',
        file = null;
  final bool mine;
  final String? file;
  String text;
  List<_Step> steps = [];
  bool working = false;
  String? note;
  String? thinking;
}

class _ChatPageState extends State<ChatPage> {
  // 바로 보기 화면을 다녀와도 대화가 남도록 정적으로 둔다
  static final List<_Msg> _msgs = [];
  static String _session = _newSession();
  static String _newSession() => 'app-${Random().nextInt(1 << 32)}';

  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _focus = FocusNode();
  bool _busy = false;
  PlatformFile? _attach;
  Map<String, dynamic>? _status;

  @override
  void initState() {
    super.initState();
    Api.instance.get('/status').then((s) {
      if (mounted) setState(() => _status = Map<String, dynamic>.from(s));
    }).catchError((_) {});
  }

  List<String> get _suggestions {
    final s = _status;
    final reviews = (s?['a_params']?['pending'] as num?) ?? 0;
    final orders = (s?['orders']?['pending'] as num?) ?? 0;
    return [
      if (reviews > 0) '확인이 필요한 프로젝트 $reviews건 보여줘',
      if (orders > 0) '승인 대기 중인 계획 보여줘',
      '호르무즈가 3개월 막히면 어디서 얼마나 더 사야 하고 비용은 얼마야?',
      '미국 신규 계약 없이 현물로만 버티면 비용이 얼마나 더 들어?',
      '지금 우리나라 LNG 수급 현황 요약해줘',
      '호르무즈 3개월 막히는 상황으로 다음 분기 계획 세워줘',
    ].take(5).toList();
  }

  void _toBottom() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
        }
      });

  void _apply(_Msg m, Map<String, dynamic> job) {
    final steps = <_Step>[];
    for (final raw in (job['events'] as List? ?? [])) {
      final e = Map<String, dynamic>.from(raw);
      final args = Map<String, dynamic>.from(e['args'] ?? {});
      if (e['type'] == 'thinking') {
        m.thinking = e['text']?.toString();
      } else if (e['type'] == 'tool_start') {
        steps.add(_Step(e['name'].toString(), e['label'].toString(), (e['running'] ?? e['label']).toString(), args));
      } else if (e['type'] == 'tool_end') {
        var s = steps.where((s) => s.name == e['name'] && !s.done).firstOrNull;
        if (s == null) {
          s = _Step(e['name'].toString(), e['label'].toString(), e['label'].toString(), args);
          steps.add(s);
        }
        s
          ..done = true
          ..seconds = (e['seconds'] as num?)?.toDouble()
          ..summary = e['summary']?.toString()
          ..result = e['result']
          ..card = e['card'] is Map ? Map<String, dynamic>.from(e['card']) : null;
      }
    }
    m.steps = steps;
  }

  Future<void> _pick() async {
    final r = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['pdf'], withData: true);
    final f = r?.files.single;
    if (f != null && f.bytes != null) setState(() => _attach = f);
    _focus.requestFocus();
  }

  Future<void> _send([String? text]) async {
    var q = (text ?? _input.text).trim();
    final file = _attach;
    if ((q.isEmpty && file == null) || _busy) return;
    if (q.isEmpty) q = '첨부한 문서 읽어줘';
    final agent = _Msg.agent()..working = true;
    setState(() {
      _msgs
        ..add(_Msg.user(q, file: file?.name))
        ..add(agent);
      _busy = true;
      _attach = null;
      _input.clear();
    });
    _toBottom();
    try {
      var message = q;
      if (file != null) {
        agent.thinking = '첨부 파일을 올리고 있어요';
        final up = await Api.instance.chatUpload(file.name, file.bytes!);
        message = '$q\n[첨부: ${up['path']}]';
      }
      final j = Map<String, dynamic>.from(await Api.instance.post('/chat/start', {'session': _session, 'message': message}));
      final done = await Api.instance.waitJob(j['id'], interval: const Duration(milliseconds: 700), onUpdate: (u) {
        if (!mounted) return;
        setState(() => _apply(agent, u));
        _toBottom();
      });
      _apply(agent, done);
      final res = Map<String, dynamic>.from(done['result'] ?? {});
      agent.text = done['status'] == 'error' ? '문제가 생겼어요: ${done['error']}' : (res['reply']?.toString() ?? '');
      agent.note = res['note']?.toString();
      if (agent.steps.isNotEmpty) widget.onChanged?.call();
    } catch (e) {
      agent.text = '문제가 생겼어요: $e';
    } finally {
      if (mounted) {
        setState(() {
          agent.working = false;
          _busy = false;
        });
        _toBottom();
        _focus.requestFocus();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Expanded(
        child: ListView(
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(24, 32, 24, 24),
          children: [
            Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 760),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  if (_msgs.isEmpty) _empty(),
                  for (final m in _msgs) m.mine ? _userBubble(m) : _agentMsg(m),
                ]),
              ),
            ),
          ],
        ),
      ),
      _composer(),
    ]);
  }

  Widget _empty() => Padding(
        padding: const EdgeInsets.only(top: 48),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('무엇을 할까요?', style: T.h1),
          const SizedBox(height: 8),
          const Text('상황을 말하면 어디서 얼마나 더 사고 비용이 얼마인지 최적화로 답해요. 미국 프로젝트 보고서를 첨부하면 AI가 판독해서 신규 계약 후보로 넣어요.\n반영과 승인은 결과 카드에서 직접 해요.',
              style: T.sub),
          const SizedBox(height: 28),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final e in _suggestions)
              ActionChip(
                label: Text(e, style: T.body.copyWith(fontSize: 15)),
                backgroundColor: Colors.white,
                side: const BorderSide(color: C.line),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
                onPressed: () => _send(e),
              ),
          ]),
        ]),
      );

  Widget _composer() => Padding(
        padding: const EdgeInsets.fromLTRB(24, 4, 24, 24),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Container(
              padding: const EdgeInsets.fromLTRB(8, 8, 8, 8),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(22),
                border: Border.all(color: C.line),
                boxShadow: const [BoxShadow(color: Color(0x0F000000), blurRadius: 16, offset: Offset(0, 4))],
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                if (_attach != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(8, 4, 8, 4),
                    child: InputChip(
                      avatar: const Icon(Icons.picture_as_pdf_rounded, size: 18, color: C.red),
                      label: Text(_attach!.name, style: T.small.copyWith(color: C.g900)),
                      backgroundColor: C.g100,
                      side: BorderSide.none,
                      onDeleted: () => setState(() => _attach = null),
                    ),
                  ),
                Row(children: [
                  IconButton(
                    tooltip: 'PDF 첨부',
                    onPressed: _busy ? null : _pick,
                    icon: const Icon(Icons.attach_file_rounded, color: C.g500),
                  ),
                  Expanded(
                    child: TextField(
                      controller: _input,
                      focusNode: _focus,
                      autofocus: true,
                      onSubmitted: (_) => _send(),
                      style: T.body,
                      decoration: const InputDecoration(
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                        filled: false,
                        hintText: '예: Cameron 보고서 읽고 반영해줘',
                      ),
                    ),
                  ),
                  IconButton.filled(
                    style: IconButton.styleFrom(backgroundColor: C.blue, disabledBackgroundColor: C.g300),
                    onPressed: _busy ? null : () => _send(),
                    icon: const Icon(Icons.arrow_upward_rounded, color: Colors.white),
                  ),
                ]),
              ]),
            ),
          ),
        ),
      );

  Widget _userBubble(_Msg m) => Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.only(top: 24, bottom: 8, left: 120),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
          decoration: BoxDecoration(color: C.blue, borderRadius: BorderRadius.circular(18)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            if (m.file != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.picture_as_pdf_rounded, size: 16, color: Colors.white),
                  const SizedBox(width: 6),
                  Flexible(child: Text(m.file!, style: T.small.copyWith(color: Colors.white))),
                ]),
              ),
            SelectableText(m.text, style: T.body.copyWith(color: Colors.white)),
          ]),
        ),
      );

  Widget _agentMsg(_Msg m) {
    final cards = [for (final s in m.steps) if (s.card != null) s.card!];
    return Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _ToolLine(m),
        if (m.text.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: SelectionArea(
              child: MarkdownBody(
                data: m.text,
                styleSheet: _md(context),
                onTapLink: (text, href, title) {
                  if (href != null) openUrl(Uri.parse(href));
                },
              ),
            ),
          ),
        for (final c in cards) ChatCard(c, onChanged: widget.onChanged),
        if (m.note != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(m.note!, style: T.small)),
      ]),
    );
  }
}

/// Solar 답변(마크다운)을 앱 글꼴과 색에 맞춰 그린다.
MarkdownStyleSheet _md(BuildContext context) {
  final p = T.body.copyWith(fontWeight: FontWeight.w400, height: 1.65);
  return MarkdownStyleSheet.fromTheme(Theme.of(context)).copyWith(
    p: p,
    pPadding: const EdgeInsets.only(bottom: 2),
    h1: T.h3,
    h2: T.h3,
    h3: T.body.copyWith(fontWeight: FontWeight.w700),
    h4: T.body.copyWith(fontWeight: FontWeight.w700),
    h1Padding: const EdgeInsets.only(top: 8),
    h2Padding: const EdgeInsets.only(top: 8),
    h3Padding: const EdgeInsets.only(top: 6),
    strong: const TextStyle(fontWeight: FontWeight.w700, color: C.g900),
    em: const TextStyle(fontStyle: FontStyle.italic),
    listBullet: p,
    listIndent: 22,
    blockSpacing: 10,
    a: p.copyWith(color: C.blue, decoration: TextDecoration.underline),
    code: T.mono.copyWith(fontSize: 13.5, color: C.g900, backgroundColor: C.g100),
    codeblockPadding: const EdgeInsets.all(14),
    codeblockDecoration: BoxDecoration(color: C.g100, borderRadius: BorderRadius.circular(12)),
    blockquote: p.copyWith(color: C.g700),
    blockquotePadding: const EdgeInsets.fromLTRB(14, 8, 12, 8),
    blockquoteDecoration: const BoxDecoration(
      color: C.blueLight,
      border: Border(left: BorderSide(color: C.blue, width: 3)),
    ),
    tableHead: T.sub.copyWith(fontWeight: FontWeight.w700, color: C.g900),
    tableBody: T.sub.copyWith(color: C.g900),
    tableBorder: TableBorder.all(color: C.line, width: 1),
    tableHeadAlign: TextAlign.left,
    tableCellsPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
    tableCellsDecoration: const BoxDecoration(color: Colors.white),
    horizontalRuleDecoration: const BoxDecoration(border: Border(top: BorderSide(color: C.line))),
  );
}

/// 도구 사용 표시. 일하는 동안은 지금 하는 일 한 줄, 끝나면 "도구 2개 사용" 한 줄로 접힌다.
/// 눌러야 단계와 원본 결과가 보인다.
class _ToolLine extends StatefulWidget {
  const _ToolLine(this.m);
  final _Msg m;
  @override
  State<_ToolLine> createState() => _ToolLineState();
}

class _ToolLineState extends State<_ToolLine> {
  bool _open = false;
  final Set<int> _raw = {};

  @override
  Widget build(BuildContext context) {
    final m = widget.m;
    if (!m.working && m.steps.isEmpty) return const SizedBox.shrink();
    final running = m.steps.where((s) => !s.done).lastOrNull;
    final grey = T.sub.copyWith(fontSize: 14, color: C.g500);

    if (m.working && !_open) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [
          const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
          const SizedBox(width: 10),
          Flexible(child: Text(running?.running ?? m.thinking ?? '생각하고 있어요', style: grey)),
          if (m.steps.any((s) => s.done))
            TextButton(onPressed: () => setState(() => _open = true), child: Text('지난 단계 ${m.steps.where((s) => s.done).length}개', style: grey)),
        ]),
      );
    }

    final total = m.steps.fold<double>(0, (a, s) => a + (s.seconds ?? 0));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () => setState(() => _open = !_open),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Flexible(
              child: Text(
                m.working
                    ? (running?.running ?? '진행 중')
                    : '${m.steps.map((s) => s.label).toSet().join(', ')} · ${total.toStringAsFixed(0)}초',
                style: grey),
            ),
            Icon(_open ? Icons.expand_less_rounded : Icons.chevron_right_rounded, size: 18, color: C.g500),
          ]),
        ),
      ),
      if (_open)
        Container(
          margin: const EdgeInsets.only(bottom: 4),
          padding: const EdgeInsets.only(left: 12),
          decoration: const BoxDecoration(border: Border(left: BorderSide(color: C.line, width: 2))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (var i = 0; i < m.steps.length; i++) _step(i, m.steps[i]),
          ]),
        ),
    ]);
  }

  Widget _step(int i, _Step s) {
    final args = s.args.entries.map((e) => '${e.key}=${e.value}').join(', ');
    final open = _raw.contains(i);
    return InkWell(
      onTap: s.done ? () => setState(() => open ? _raw.remove(i) : _raw.add(i)) : null,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            s.done
                ? const Icon(Icons.check_rounded, size: 16, color: C.green)
                : const SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: 8),
            Text(s.label, style: T.sub.copyWith(fontSize: 14, fontWeight: FontWeight.w600, color: C.g700)),
            const SizedBox(width: 8),
            Flexible(child: Text('${s.name}($args)', style: T.mono.copyWith(fontSize: 12, color: C.g500), overflow: TextOverflow.ellipsis)),
            if (s.seconds != null) Text('  ${s.seconds!.toStringAsFixed(1)}초', style: T.small),
          ]),
          if (s.summary != null)
            Padding(padding: const EdgeInsets.only(left: 24, top: 2), child: Text(s.summary!, style: T.small)),
          if (open)
            Container(
              margin: const EdgeInsets.only(left: 24, top: 6),
              padding: const EdgeInsets.all(10),
              constraints: const BoxConstraints(maxHeight: 260),
              decoration: BoxDecoration(color: const Color(0xFF1E2530), borderRadius: BorderRadius.circular(10)),
              child: SingleChildScrollView(
                child: SelectableText(const JsonEncoder.withIndent('  ').convert(s.result),
                    style: T.mono.copyWith(fontSize: 12, color: const Color(0xFFD6DEEB))),
              ),
            ),
        ]),
      ),
    );
  }
}
