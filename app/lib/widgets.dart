import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'theme.dart';

// ---------- 화면 틀 ----------

/// 가운데 정렬된 한 줄 기둥. 위에 큰 제목, 아래 카드들, 맨 아래 고정 버튼(선택).
class PageScaffold extends StatelessWidget {
  const PageScaffold({super.key, required this.title, this.subtitle, required this.children, this.bottom, this.action});
  final String title;
  final String? subtitle;
  final List<Widget> children;
  final Widget? bottom;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Expanded(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 40, 24, 40),
          children: [
            Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  if (title.isNotEmpty || action != null) ...[
                    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Expanded(child: Text(title, style: T.h1)),
                      if (action != null) action!,
                    ]),
                    if (subtitle != null) ...[const SizedBox(height: 8), Text(subtitle!, style: T.sub)],
                    const SizedBox(height: 28),
                  ],
                  ...children,
                ]),
              ),
            ),
          ],
        ),
      ),
      if (bottom != null)
        Container(
          color: C.bg,
          padding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
          child: Center(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 720), child: bottom!)),
        ),
    ]);
  }
}

/// 흰 카드. 제목이 있으면 위에 작게.
class Box extends StatelessWidget {
  const Box({super.key, this.title, required this.child, this.padding = const EdgeInsets.all(24), this.trailing});
  final String? title;
  final Widget child;
  final EdgeInsets padding;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: padding,
      decoration: BoxDecoration(color: C.card, borderRadius: BorderRadius.circular(20)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (title != null) ...[
          Row(children: [Expanded(child: Text(title!, style: T.h3)), if (trailing != null) trailing!]),
          const SizedBox(height: 16),
        ],
        child,
      ]),
    );
  }
}

/// 목록 한 줄: 왼쪽 동그라미 아이콘, 제목과 설명, 오른쪽 값과 화살표.
class RowItem extends StatelessWidget {
  const RowItem({super.key, required this.title, this.subtitle, this.icon, this.iconColor, this.trailing, this.onTap});
  final String title;
  final String? subtitle;
  final IconData? icon;
  final Color? iconColor;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final col = iconColor ?? C.blue;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 4),
        child: Row(children: [
          if (icon != null) ...[
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(color: col.withOpacity(0.12), shape: BoxShape.circle),
              child: Icon(icon, color: col, size: 22),
            ),
            const SizedBox(width: 16),
          ],
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: T.body.copyWith(fontWeight: FontWeight.w600)),
              if (subtitle != null) ...[const SizedBox(height: 2), Text(subtitle!, style: T.small)],
            ]),
          ),
          if (trailing != null) ...[const SizedBox(width: 12), trailing!],
          if (onTap != null) const Padding(padding: EdgeInsets.only(left: 6), child: Icon(Icons.chevron_right, color: C.g300)),
        ]),
      ),
    );
  }
}

/// 큰 숫자 하나와 이름.
class BigStat extends StatelessWidget {
  const BigStat(this.label, this.value, {super.key, this.unit = '', this.color});
  final String label;
  final String value;
  final String unit;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: T.small),
      const SizedBox(height: 6),
      Text.rich(TextSpan(children: [
        TextSpan(text: value, style: T.num.copyWith(color: color)),
        if (unit.isNotEmpty) TextSpan(text: ' $unit', style: T.sub),
      ])),
    ]);
  }
}

class StatRow extends StatelessWidget {
  const StatRow(this.stats, {super.key});
  final List<Widget> stats;
  @override
  Widget build(BuildContext context) => Row(children: [for (final s in stats) Expanded(child: s)]);
}

enum Tone { good, warn, bad, info, neutral }

/// 상태 알약. 반영과 승인 요청은 초록, 확인 필요와 재계획은 주황.
class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, this.tone = Tone.neutral});
  final String text;
  final Tone tone;

  factory Pill.of(String? raw) => Pill(label(raw), tone: toneOf(raw));

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = switch (tone) {
      Tone.good => (C.greenLight, C.green),
      Tone.warn => (C.orangeLight, C.orange),
      Tone.bad => (C.redLight, C.red),
      Tone.info => (C.blueLight, C.blue),
      Tone.neutral => (C.g100, C.g700),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
      child: Text(text, style: T.small.copyWith(color: fg, fontWeight: FontWeight.w600)),
    );
  }
}

/// 서버 값 -> 사람이 읽는 말
String label(String? raw) => switch (raw) {
      '반영' || 'auto' => '바로 반영',
      'approved' => '확인 후 반영',
      'rejected' => '제외',
      '검토 필요' || 'pending' => '확인 필요',
      '승인 요청' => '문제 없음',
      '재계획 필요' => '다시 계획 필요',
      'PENDING_APPROVAL' => '승인 대기',
      'APPROVED' => '승인 완료',
      'NEEDS_REVIEW' => '판정이 엇갈림',
      'ESCALATED' => '담당자 확인',
      'running' => '진행 중',
      'done' => '완료',
      'error' => '오류',
      null => '-',
      _ => raw,
    };

Tone toneOf(String? raw) => switch (raw) {
      '반영' || 'auto' || 'approved' || '승인 요청' || 'APPROVED' || 'done' => Tone.good,
      '검토 필요' || 'pending' || '재계획 필요' || 'NEEDS_REVIEW' || 'ESCALATED' => Tone.warn,
      'rejected' || 'error' => Tone.bad,
      'PENDING_APPROVAL' || 'running' => Tone.info,
      _ => Tone.neutral,
    };

// ---------- 버튼과 선택 ----------

class PrimaryButton extends StatelessWidget {
  const PrimaryButton(this.text, {super.key, required this.onPressed, this.busy = false, this.color});
  final String text;
  final VoidCallback? onPressed;
  final bool busy;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 56,
      child: FilledButton(
        style: FilledButton.styleFrom(
          backgroundColor: color ?? C.blue,
          disabledBackgroundColor: C.g300,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          textStyle: T.body.copyWith(fontWeight: FontWeight.w700, fontSize: 17),
        ),
        onPressed: busy ? null : onPressed,
        child: busy
            ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
            : Text(text),
      ),
    );
  }
}

class SecondaryButton extends StatelessWidget {
  const SecondaryButton(this.text, {super.key, required this.onPressed});
  final String text;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 56,
      child: TextButton(
        style: TextButton.styleFrom(
          backgroundColor: C.g100,
          foregroundColor: C.g700,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          textStyle: T.body.copyWith(fontWeight: FontWeight.w600),
        ),
        onPressed: onPressed,
        child: Text(text),
      ),
    );
  }
}

/// 알약 모양 선택지 한 줄.
class Choices<V> extends StatelessWidget {
  const Choices({super.key, required this.options, required this.value, required this.onChanged});
  final List<(V, String)> options;
  final V value;
  final void Function(V) onChanged;

  @override
  Widget build(BuildContext context) {
    return Wrap(spacing: 8, runSpacing: 8, children: [
      for (final (v, text) in options)
        InkWell(
          onTap: () => onChanged(v),
          borderRadius: BorderRadius.circular(12),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            decoration: BoxDecoration(
              color: v == value ? C.blue : C.g100,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(text,
                style: T.body.copyWith(
                    fontSize: 15, color: v == value ? Colors.white : C.g700, fontWeight: FontWeight.w600)),
          ),
        ),
    ]);
  }
}

/// 질문 하나와 선택지.
class Question extends StatelessWidget {
  const Question(this.q, this.child, {super.key, this.hint});
  final String q;
  final String? hint;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 28),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(q, style: T.h3),
        if (hint != null) ...[const SizedBox(height: 4), Text(hint!, style: T.small)],
        const SizedBox(height: 14),
        child,
      ]),
    );
  }
}

// ---------- 진행과 결과 ----------

/// 진행 중일 때: 큰 스피너와 지금 하는 일 한 줄.
class Working extends StatelessWidget {
  const Working(this.job, {super.key, this.steps = const []});
  final Map<String, dynamic>? job;
  final List<String> steps;

  @override
  Widget build(BuildContext context) {
    final log = [for (final l in (job?['log'] as List? ?? [])) l.toString()].where((l) => !l.startsWith('Traceback')).toList();
    return Box(
      child: Column(children: [
        const SizedBox(height: 12),
        const SizedBox(width: 44, height: 44, child: CircularProgressIndicator(strokeWidth: 4)),
        const SizedBox(height: 20),
        Text(log.isEmpty ? '시작하고 있어요' : _friendly(log.last), style: T.h3, textAlign: TextAlign.center),
        const SizedBox(height: 6),
        Text('AI가 문서를 판독하는 데 30초에서 1분쯤 걸려요', style: T.small, textAlign: TextAlign.center),
        const SizedBox(height: 12),
      ]),
    );
  }

  static String _friendly(String l) {
    if (l.contains('워크플로우') || l.contains('판독')) return '문서를 판독하고 있어요';
    if (l.contains('재계획') || l.contains('다시 돌')) return '문제가 있어 다시 계획하고 있어요';
    if (l.contains('검증 시스템') || (l.contains('Studio') && l.contains('검산'))) return '실행안을 검증했어요';
    return l.length > 40 ? '${l.substring(0, 40)}…' : l;
  }
}

/// Studio 출력 원본 (자세히 보기).
class RawFields extends StatelessWidget {
  const RawFields(this.fields, {super.key, this.highlight = const {}});
  final Map<String, dynamic> fields;
  final Set<String> highlight;

  @override
  Widget build(BuildContext context) {
    final ks = fields.keys.where((k) => !k.startsWith('_')).toList();
    return Column(children: [
      for (final k in ks)
        Container(
          color: highlight.contains(k) ? C.orangeLight : null,
          padding: const EdgeInsets.symmetric(vertical: 10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: 170, child: Text(k, style: T.mono.copyWith(color: C.g500))),
            Expanded(child: SelectableText(fmt(fields[k]), style: T.mono.copyWith(color: C.g900))),
          ]),
        ),
    ]);
  }
}

class Details extends StatelessWidget {
  const Details({super.key, required this.title, required this.child});
  final String title;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: 8),
        title: Text(title, style: T.sub.copyWith(fontWeight: FontWeight.w600)),
        children: [child],
      ),
    );
  }
}

/// 결과 맨 위: 동그란 아이콘, 큰 한 줄, 작은 설명.
class ResultHead extends StatelessWidget {
  const ResultHead({super.key, required this.ok, required this.title, this.body});
  final bool ok;
  final String title;
  final String? body;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 52,
          height: 52,
          decoration: BoxDecoration(color: ok ? C.greenLight : C.orangeLight, shape: BoxShape.circle),
          child: Icon(ok ? Icons.check_rounded : Icons.priority_high_rounded, color: ok ? C.green : C.orange, size: 30),
        ),
        const SizedBox(height: 16),
        Text(title, style: T.h2),
        if (body != null) ...[const SizedBox(height: 8), Text(body!, style: T.sub)],
      ]),
    );
  }
}

// ---------- 도우미 ----------

String fmt(dynamic v) {
  if (v == null) return '-';
  if (v is List) return v.isEmpty ? '없음' : v.join('\n');
  if (v is Map) return const JsonEncoder.withIndent('  ').convert(v);
  final s = v.toString();
  return s.isEmpty ? '없음' : s;
}

/// 폴더 이름 같은 키를 읽기 쉬운 이름으로.
String niceName(String key) => key.replaceAll('_', ' ').replaceAll(RegExp(r'\s+(LLC|L P|LP|S A P I de C V|S de R L de C V)$'), '');

/// 시나리오를 사람이 읽는 말로 (서버가 조건으로 만든 scenario_label을 먼저 쓴다).
String scen(Map? x) => (x?['scenario_label'] ?? x?['scenario'] ?? '').toString();

String num0(dynamic v) {
  if (v == null) return '0';
  final n = v is num ? v : num.tryParse(v.toString()) ?? 0;
  final s = n.round().toString();
  return s.replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (m) => ',');
}

void toast(BuildContext context, String msg) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
}

void showError(BuildContext context, Object e) => toast(context, '문제가 생겼어요: $e');

Future<void> openUrl(Uri url) async {
  await launchUrl(url, mode: LaunchMode.externalApplication);
}
