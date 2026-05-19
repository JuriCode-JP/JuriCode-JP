# データ検証フレームワーク (3 層)

JuriCode-JP は政府公式の法令データ (e-Gov 法令API) から派生する公開データを扱う.
よって、データの「**間違い**」を防ぐ仕組みが本体機能と同等に重要である.
ここで言う「間違い」とは:

1. 法令本文の**改変・要約・誤転記** (CLAUDE.md §4.1, §5 に明記の禁止行為)
2. **古いバージョン**の使い回し (改正反映漏れ)
3. e-Gov 側の**更新を見落とす**
4. **推測**による情報追加 (CLAUDE.md §5: 推測による判例追加は厳禁)

これらを 3 層の自動チェック + 1 層の人間レビューでガードする.

---

## Layer 1: 取得時 (Fetch-time) — `tools/fetch-egov/`

**目的**: e-Gov から取った XML が確かに e-Gov のものであることを記録.

責任範囲:

- e-Gov API 公式エンドポイント (`https://laws.e-gov.go.jp/api/2/`) からのみ取得
- 取得 XML を `cache/<law_id>/<fetched-date>.xml` として保存
- HTTP 応答の `Last-Modified` ヘッダー (もしあれば) を記録
- XML 全体の SHA-256 を算出してキャッシュメタデータに記録

実装場所: `tools/fetch-egov/` (既存スケルトン、Phase 0 で着手済).

---

## Layer 2: 生成時 (Parse-time) — `tools/parse/`

**目的**: e-Gov XML から JuriCode-JP Markdown を生成する際, **テキストが改変されていないこと**を機械的に保証.

責任範囲:

各条文の生成時:

- e-Gov XML から抽出した日本語本文を **canonical 化** (空白統一・改行統一・前後 trim) して SHA-256 を算出
- 同じ canonical 化を Markdown 出力後にも適用 → ハッシュ一致を assert
- 法令単位の `_source-manifest.json` を生成 (詳細下記)

`_source-manifest.json` のスキーマ:

```json
{
  "schema_version": "1.0",
  "law_id": "323AC0000000136",
  "law_name_ja": "警察官職務執行法",
  "source_url": "https://laws.e-gov.go.jp/api/2/law_data/323AC0000000136",
  "source_xml_path": "cache/323AC0000000136/2026-05-19.xml",
  "source_xml_sha256": "abc123...",
  "source_xml_bytes": 12345,
  "source_fetched_at": "2026-05-19",
  "parser": "tools/parse/parse-egov.py",
  "parser_version": "0.1.0",
  "parsed_at": "2026-05-19T10:30:00Z",
  "article_count": 8,
  "articles": [
    {
      "article_id": "keisatsukan-shokumu-shikkou-hou-art-1",
      "article_number": "1",
      "filename": "keisatsukan-shokumu-shikkou-hou-article-1.md",
      "ja_text_sha256": "def456...",
      "ja_text_bytes": 234,
      "paragraph_count": 1
    }
  ]
}
```

このファイルは Markdown と同じディレクトリに置き, Git にコミットする.
**IR (`tools/shared/`) には手を入れない** — 検証メタデータを Markdown frontmatter に混ぜない方針.

---

## Layer 3: CI 時 (CI-time) — `tools/parse/verify.py` + `tools/validate/`

**目的**: PR で投入される全データが、上記マニフェストと**一致し続けている**ことを保証.

`tools/parse/verify.py` の動作:

1. `data/` 配下を再帰的に走査し, `_source-manifest.json` を発見
2. 各マニフェストエントリについて:
   - 対応する Markdown ファイルを読む
   - 日本語本文を canonical 化
   - SHA-256 を再計算
   - マニフェストに記録された `ja_text_sha256` と一致するか確認
3. 不一致があれば **CI を fail させる**

これにより:

- うっかり Markdown を編集 → 検知される
- 法令本文の改変 → 検知される
- マニフェストの改竄 → schema 検証 (`tools/validate/`) でガード

CI ワークフロー (`.github/workflows/ci.yml`) に既存の validate-all.py の後に追加:

```yaml
- name: Verify source-manifest hashes (parse pipeline)
  run: python tools/parse/verify.py --strict
```

---

## Layer 4: 人間レビュー (Human review) — PR 時

**目的**: 機械検証で拾えない**意味的な間違い** (誤訳, 判例の事実誤認, タグの誤分類) をフィルタリング.

PR テンプレート (`.github/PULL_REQUEST_TEMPLATE.md`) に**新規データ追加時**の必須チェック追加:

- [ ] 本文を e-Gov 原典と**目視比較**して文字単位で一致を確認した
- [ ] `version_date` が e-Gov の現行版と一致する
- [ ] `last_verified` を本日付に更新した
- [ ] `_source-manifest.json` の SHA-256 が `tools/parse/verify.py` で PASS する
- [ ] 判例リンクを追加した場合, **裁判所 Web の永続 URL** を実際にアクセスして確認した

「1 コミット 1〜数条」ポリシー (CLAUDE.md §10) と組み合わせて, レビュー粒度を保つ.

---

## 定期的な再検証 (Periodic re-check) — 月次

**目的**: e-Gov 側の更新を見落とさない.

(将来 [FU-006] / [FU-205] と統合)

月次 cron で `tools/track-amendments/check-egov-sync.py` を実行 (未実装):

1. `data/` 配下の全 `_source-manifest.json` を列挙
2. 各 `source_url` で e-Gov から再取得
3. 新しい XML の SHA-256 と record の `source_xml_sha256` を比較
4. 不一致なら GitHub Issue を自動起票し, 改正があった可能性をフラグ

---

## まとめ図

```
            ┌─ Layer 1 ─────────────────┐
            │ tools/fetch-egov/         │
            │ e-Gov API → cache/        │
            │ XML 全体の SHA-256 を記録  │
            └──────────────┬────────────┘
                           ↓
            ┌─ Layer 2 ─────────────────┐
            │ tools/parse/parse-egov.py │
            │ XML → Markdown 1条1ファイル │
            │ + _source-manifest.json    │
            │ (条ごとの本文 SHA-256 記録) │
            └──────────────┬────────────┘
                           ↓
            ┌─ Layer 3 (CI) ────────────┐
            │ tools/parse/verify.py     │
            │ tools/validate/           │
            │ Markdown vs manifest 突合  │
            │ schema 検証                │
            └──────────────┬────────────┘
                           ↓
            ┌─ Layer 4 (人) ────────────┐
            │ PR レビュアー              │
            │ 原典目視比較               │
            │ 意味的整合性確認            │
            └──────────────┬────────────┘
                           ↓
            ┌─ 定期再検証 ─────────────┐
            │ 月次 e-Gov 再取得 & diff   │
            │ 改正検知時 Issue 起票      │
            └───────────────────────────┘
```

---

## 設計上の判断

- **IR を拡張しない**: `source_hash` 等の検証メタは `_source-manifest.json` に分離.
  Pydantic IR のシンプルさを保つため, 利用者が **追加学習** しなければいけない
  spec フィールドを増やさない. ([[feedback-spec-understanding]] の方針と整合)
- **manifest を Git に commit する**: 検証材料が無いと検証できない. `data/` 配下に
  manifest を同居させてアトミックに版管理する.
- **canonical 化のルールを統一**: `python tools/parse/_text_canonicalize.py` に集約.
  parse 側と verify 側で同じ関数を使う. drift を防ぐ.
- **Layer 4 を省略しない**: 機械検証だけでは「意味的に正しい」は保証できない.
  特に判例 (法的位置付け) と英訳 (ニュアンス) は人の判断が要る.

---

## 関連

- [FU-P0-1](follow-ups.md#fu-p0-1-toolsparse-mvp-nlnet-m2) — `tools/parse/` MVP 設計 (この文書を実装する)
- [FU-006](follow-ups.md#fu-006-2026-05-19) — 法令改正の追跡メカニズム設計 (定期再検証)
- [FU-205](follow-ups.md#fu-205-url) — 判例 URL 生存確認 (判例レイヤーの周辺検証)
- [CLAUDE.md §4](../CLAUDE.md) — 必ず守ること: 法令本文の改変禁止
- [CLAUDE.md §5](../CLAUDE.md) — やってはいけないこと: 推測による追加禁止

---

*Last updated: 2026-05-19 / Status: v1.0 initial design — Layer 1 は既存スケルトン, Layer 2-3 は本 PR で実装, Layer 4 は PR テンプレート更新で対応, 定期再検証は FU-006 で実装予定*
