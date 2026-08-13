# 贡献与合并门禁

本仓库的所有 Pull Request（包括文档修正和紧急修复）都必须经过当前
HEAD 对应的 Codex review，才能合并到 `main`。CI 通过不等于 review 完成。

## 必须遵循的顺序

1. 从最新 `main` 创建分支，并将 PR 先创建为 Draft。
2. 完成提交后，确认 `dependency-audit` 与 `test-and-build` 已运行。
3. 将 PR 标记为 Ready for review，或在 PR 会话中发送 `@codex review`。
4. 等待 Codex 对当前 HEAD 给出 review、评论线程或无建议的成功反馈。
5. 对每一条 Codex 意见在原线程内回复：
   - 已修改：说明修改位置和验证结果；
   - 不修改：说明可复核的原因；
   - 已过时或重复：仍需说明原因。
6. 完成回复后解决对应线程，并确认 PR 页面没有未解决会话。
7. 如果期间发生任何 `push`、rebase、合入基础分支或其他 HEAD 变化，旧的
   Codex 结果立即失效；清空 PR 模板中的 review 记录，从第 2 步重新执行。
8. 合并者在点击 Merge 前再次核对：记录的 HEAD 等于 PR 当前 HEAD、Codex
   已完成本轮检查、所有线程已回复并解决、两项必需 CI 均为成功。

可用 `git rev-parse HEAD` 取得完整 40 位 HEAD。PR 模板必须记录该 SHA 以及
Codex review 或触发请求的 GitHub 链接。若 Codex review 正文给出
`Reviewed commit`，它必须指向当前 HEAD；若 Codex 在没有建议时只留下成功
反应，则该反应必须对应当前 HEAD 产生之后的本轮 review 请求，并且之后不能
再有新提交。

## 哪些部分由 GitHub 强制

`main` 当前的分支保护会强制要求分支为最新、`dependency-audit` 和
`test-and-build` 成功、所有会话已解决，并对管理员同样生效。因此，一旦
Codex 创建了评论线程，未解决线程会阻止合并。

“等待 Codex 对当前 HEAD 完成 review”目前是维护者必须执行的人工门禁，而不
是一个现成的 GitHub required check。Codex App 可能通过 review、线程或成功
反应返回结果，仓库不能仅凭普通 CI 可靠证明它已检查当前 HEAD。除非将来
Codex 提供稳定的逐提交状态检查，并由仓库管理员把该检查加入分支保护，否则
不得把 PR 模板的复选框描述为自动技术强制，也不得在 Codex 返回前合并。

## 合并者核对单

- PR 模板中的“已审查 HEAD”为当前完整 SHA；
- Codex 证据产生于该 HEAD 之后，且明确覆盖该提交；
- 每条意见都有同线程回复，没有未解决线程；
- review 后没有新提交；
- 两项必需 CI 均成功，Merge 按钮不存在待处理会话提示。

