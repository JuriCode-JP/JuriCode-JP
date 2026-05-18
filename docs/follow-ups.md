# Follow-up Tracker — Known Limitations & Future Work

> JuriCode-JP の現バージョン (v0.1, 2026-05-18) で**意図的に未実装としている項目**および**改善余地**を一覧化する。
>
> このファイルは外部コントリビューターと将来の自分への "TODO" 兼 "なぜ今こうなっているか" の説明.
> 完了した項目はチェックを入れて行内に commit hash / PR 番号を残す.
>
> **凡例**:
> - **P1** = Phase 1 着手前 (〜2026-06 末) に潰したい
> - **P2** = Phase 1 中期 (2026-07〜09) に対応
> - **P3** = Phase 1 後期 (2026-10〜) に対応、または Phase 2 で見直し

---

## P1 — Phase 1 着手前 (〜2026-06 末)

### [ ] FU-001: `case_id` の命名規約を確定する

**現状**: サンプルファイル内で 2 種類の表記が混在.

- `examples/keihou/keihou-article-36.md` → `scj-1969-12-04-keishu-23-12-1573` (法廷略号なし)
- `tools/shared/tests/test_ir.py` 内のテストデータ → `scj-pb1-1969-12-04-keishu-23-12-1573` (法廷略号 `pb1` あり)
- `tools/shared/src/juricode_shared/ids.py` の `make_case_id()` docstring → 法廷略号あり

**両方とも `CASE_ID_PATTERN` を通る**ため IR validation では落ちないが、コミュニティが追加する判例リンクで規約が拡散する.

**やること**:

1. `docs/ir-spec.md §4.2` (`case_id` セクション) で**正規パターンを明示**
2. 推奨案: 法廷略号は `case_id` に埋め込まず、別フィールド (`bench_abbrev: "first-petty"` 等) で持つ. ID は機械的に決まるべき
3. 既存サンプルとテストデータを統一

**関連**: `docs/glossary.md` (裁判所略号一覧追加検討)

---

### [ ] FU-002: ファイル名規約を `paths.py` に集約する

**現状**: `{law-abbrev}-article-{N}.md` パターンが 3 箇所に重複.

- `tools/shared/src/juricode_shared/paths.py:29` の `article_path()`
- `tools/validate/_validate.py:84-85` の filename mismatch チェック
- `data/phase1-police/*/README.md` の docstring (4 ファイル)

規約変更時に drift しやすい.

**やること**:

```python
# paths.py に追加
def article_filename(law_abbrev: str, article_number: str) -> str:
    return f"{law_abbrev}-article-{article_number}.md"
```

`_validate.py` の該当箇所を `paths.article_filename()` 呼び出しに置き換え.

---

### [ ] FU-003: `Pydantic ValidationError` の structured 出力化

**現状**: `tools/validate/_validate.py:78` で Pydantic の `ValidationError` を文字列化してそのまま users に返している. 技術者には読めるが、新規 contributor には厳しい.

**やること**:

```python
except ValidationError as e:
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = err["msg"]
        errors.append(f"field '{loc}' — {msg}")
```

フィールドパス + 短い説明の形式に整形.

---

### [ ] FU-004: 失敗ケーステスト追加

**現状**: 41 件のテストはあるが、以下の failure path が未カバー.

- 空 frontmatter (`---\n---`)
- frontmatter デリミタ 1 つだけ
- 不正 YAML (`key: : value` 等)
- ParentSection 全 5 レベル (hen/shou/setsu/kan/moku) 同時指定
- `english_translation.paragraphs` の長さが `paragraphs` と異なるケース

**やること**: 上記を `tests/test_ir.py` / `tests/test_frontmatter.py` に追加.

---

### [ ] FU-005: `ir-spec.md §5.3` 警告の実装

**現状**: 仕様にある以下の warning が未実装.

- `translation_status == OFFICIAL` で `english_translation.source` が空 → 警告
- `notes` が 500 字超 → 警告

**やること**: `tools/validate/_validate.py` に warning 出力ロジック追加.

---

## P2 — Phase 1 中期 (2026-07〜09)

### [ ] FU-101: `ARTICLE_ID_PATTERN` の特殊条文対応

**現状**: `r"^[a-z][a-z0-9-]*-art-[0-9]+(-[0-9]+)*$"` は附則・経過措置を弾く.

**やること**: パターンを `r"^[a-z][a-z0-9-]*-art-([a-z0-9]+)(-[a-z0-9]+)*$"` に緩める. または `docs/format-spec.md` に「Phase 1 では本則のみ、附則は Phase 2」と明記.

---

### [ ] FU-102: CLI を `pyproject.toml` の entry point 化

**現状**: `tools/validate/validate-file.py` 等がハイフン命名で Python module としては import できない. `sys.path` パッチで回避.

**やること**: `pyproject.toml` に `[project.scripts]` を追加.

```toml
[project.scripts]
juricode-validate-file = "juricode_validate.cli:validate_file_main"
juricode-validate-all = "juricode_validate.cli:validate_all_main"
```

`pip install -e ".[dev]"` 後にどこからでも `juricode-validate-file path.md` で動く.

---

### [ ] FU-103: `juricode-shared` を proper installable に

**現状**: `tools/validate/_validate.py` に `sys.path.insert` でパス追加. monorepo の構造変更で壊れやすい.

**やること**: workspace 化. uv または pip-tools で `tools/shared`, `tools/validate`, `tools/fetch-egov` を editable install で一括管理.

---

### [ ] FU-104: `source_url` を `pydantic.HttpUrl` 化

**現状**: `str` のみ. URL でない値も通る.

**やること**: `tools/shared/src/juricode_shared/ir.py` の `JuriCodeArticle.source_url` を `HttpUrl` に. 既存サンプルが通るかは事前に検証.

---

### [ ] FU-105: `law_id` フォーマット regex 化

**現状**: `str` のみ. e-Gov 法令 ID 形式 (例: `140AC0000000045` = `[元号略][年]AC[type][番号]`) を強制していない.

**やること**: 正確な形式を `docs/ir-spec.md` に書いた上で regex 化.

---

## P3 — Phase 1 後期以降 (2026-10〜) / Phase 2 検討

### [ ] FU-201: `ParentSection` を多言語対応構造に変更

**現状**: `hen: int + hen_name_ja + hen_name_en` flat 構造. 中国語・韓国語追加時にフィールドが増殖.

**Phase 2 でやること** (Phase 1 中は不要):

```python
class ParentLevel(BaseModel):
    number: int
    names: dict[str, str]  # {"ja": "第一編 総則", "en": "Part I", ...}

class ParentSection(BaseModel):
    hen: ParentLevel | None
    shou: ParentLevel | None
    ...
```

ただし Phase 1 では JA/EN のみで足りるため、データマイグレーションコストとのトレードオフで判断.

---

### [ ] FU-202: `Paragraph.text` の設計を spec で明文化

**現状**: `text` は frontmatter には含まれず Markdown body から `tools/parse/` で埋める設計だが、ir.py の docstring にしか書かれていない. 外部の IR JSON 利用者は気付けない.

**やること**: `docs/ir-spec.md §3.2` に「frontmatter には text を載せない、body から populate される」を明記. 必要なら `IRMetaOnly` / `IRWithBody` の型分離も検討.

---

### [ ] FU-203: frontmatter ダンプ順序の制御

**現状**: `frontmatter.dump_frontmatter()` は Pydantic model 定義順で出力. canonical sample のキー順と微妙にずれる可能性. round-trip 自体は問題ないが PR diff が肥大化する.

**やること**: 重要度低. canonical なフィールド順序を `_FIELD_ORDER` リストで明示制御.

---

### [ ] FU-204: `field_validator` の `info` を `ValidationInfo` 型に

**現状**: `info: Any` で書いている (Pydantic v2 の型を明示していない).

**やること**:

```python
from pydantic import ValidationInfo

@field_validator(...)
def some_validator(cls, v, info: ValidationInfo):
    ...
```

mypy / pyright で型がより厳密に追える.

---

### [ ] FU-205: 判例 URL 生存確認スクリプト

**現状**: `tools/validate/` の README で予告済みだが未実装.

**やること**: `tools/validate/check-case-urls.py` を実装. `--since-days 30` で過去 30 日以内に未確認の URL を再検証. 503/404 を warning にする.

---

## 完了済み

完了した項目はここに timestamp 付きで移動する.

### 2026-05-18

- ✅ **P0-1: `SourceFormat` を 4 値に拡張** — `docs/ir-spec.md §3.1` で `e-gov-html` 追加 + 各値の使い分けガイド付記
- ✅ **P0-2: IR integrity rule 3 件追加** — `cases_relevant_paragraph_exists`, `english_translation_implies_status`, `machine_translated → DRAFT` 推奨警告
- ✅ **P0-3: canonical サンプルのタグを vocabulary 準拠に** — `刑事法` を必須カテゴリ B として追加

---

## 関連

- 内部レビュー文書 (gitignored): `business/code-reviews/2026-05-18-tools-and-schema-review.md`
- 仕様書: [docs/ir-spec.md](./ir-spec.md), [docs/format-spec.md](./format-spec.md), [docs/tag-vocabulary.md](./tag-vocabulary.md)
- 検証ツール: [tools/validate/README.md](../tools/validate/README.md)

---

*Last updated: 2026-05-18 / Maintained by: CHOKAI Co.,Ltd. / Status: v0.1 initial follow-up tracker*
