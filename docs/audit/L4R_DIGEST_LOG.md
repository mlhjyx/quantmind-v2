# L4+R 方向 Digest Log

> **用途**: L4+R 自主持续循环 §4.1 方向 digest 的 append-only 落点。
> **写入**: CC 每 research cycle + 每 ~5 execute task + 至少每周一次 append 一条 digest(做了什么 / commit / 下一步计划 / 方向判断 / 与上次 digest 方向偏移 / implement:archive:defer 比例)。
> **读取**: user 可异步翻阅 veto/redirect;§4.2 self-audit 抽查方向漂移。
> **体例**: append-only,新 entry 追加在文件末尾(时序正序),0 retroactive edit。
> **来源 spec**: docs/L4R_LOOP_SPEC.md §4.1
> **创建**: 2026-05-22(loop 未启用,首条 digest 待 loop 首次触发)

---

<!-- digest entries appended below by L4+R loop §4.1 -->
