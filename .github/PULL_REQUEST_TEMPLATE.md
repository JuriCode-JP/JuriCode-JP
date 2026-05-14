<!--
JuriCode-JP PR template

Conventional Commits prefix examples:
  data(keihou): add article 36 (正当防衛)
  data(keihou/199): add Supreme Court 1969-12-04 case link
  schema: require last_verified field
  docs(format-spec): clarify proviso handling
  tools(fetch-egov): initial CLI scaffolding
-->

## 変更内容 / Summary

<!-- このPRで何を変更したか、簡潔に -->

## 種別 / Type of change

- [ ] 法令データの追加 (`data:`)
- [ ] 法令データの修正 (`data:` / `fix:`)
- [ ] 英訳の追加・改善 (`data:` translation)
- [ ] スキーマ変更 (`schema:`)
- [ ] ドキュメント更新 (`docs:`)
- [ ] ツール変更 (`tools:` / `feat:` / `fix:`)
- [ ] その他

## 法令データの追加・修正の場合 / For data PRs

- [ ] 法令本文は e-Gov 公式テキストと**一字一句一致**することを確認した
- [ ] `frontmatter.source_url` が有効
- [ ] `frontmatter.last_verified` を本日の日付に更新
- [ ] `translation_status` が正しい(`official`/`community`/`draft`/`none`)
- [ ] 判例リンクの **URL に実際にアクセス**して有効性を確認(該当する場合)
- [ ] 判例の **citation(掲載誌・巻号・頁)を出典確認** 済み(該当する場合)
- [ ] スキーマ検証を通過: `python tools/validate/validate-file.py [path]`(ツール実装後)

## スキーマ・ドキュメント変更の場合 / For schema/docs PRs

- [ ] 既存サンプル(`examples/`)が新スキーマで検証可能
- [ ] バージョンを bump した(破壊的変更の場合)
- [ ] `docs/format-spec.md` を更新した

## 関連Issue / Related issues

<!-- Closes #123 / Refs #456 -->

## チェックリスト / General checklist

- [ ] コミットメッセージが Conventional Commits に準拠
- [ ] 1コミット1論理単位を心がけた
- [ ] AIアシスタント(Claude等)を使用した場合、本PR記述で明示した
- [ ] 関連ドキュメントを更新した(必要な場合)

## レビュアーへのお願い / Notes for reviewers

<!-- 特に確認してほしい箇所、判断が分かれそうな点など -->
