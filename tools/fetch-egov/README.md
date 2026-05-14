# tools/fetch-egov — e-Gov 法令APIクライアント

e-Gov 法令API (https://laws.e-gov.go.jp/) から法令XMLを取得する。

## 想定構成(計画)

```
fetch-egov/
├── README.md
├── pyproject.toml
├── src/
│   ├── client.py           # APIクライアント本体
│   ├── cache.py            # ローカルキャッシュ
│   ├── law_id_map.py       # 法令ID ↔ 略称マップ
│   └── cli.py              # CLI エントリポイント
├── cache/                  # 取得XMLのローカルキャッシュ(.gitignore)
└── tests/
```

## API 仕様の参考

- 法令APIガイド: https://laws.e-gov.go.jp/apitop/
- 主要エンドポイント(2026年5月時点、要再確認):
  - 法令一覧取得: `/api/2/lawlists/{法令種別}`
  - 法令本文取得(XML): `/api/2/lawdata/{法令ID}`
  - 条文取得: `/api/2/articles/{法令ID}/{条番号}`

## CLI ユースケース(想定)

```bash
# 刑法第36条のXMLを取得してキャッシュ
python -m fetch_egov get-article 140AC0000000045 36

# 刑法全体のXMLを取得
python -m fetch_egov get-law 140AC0000000045

# キャッシュから JuriCode-JP 形式の中間表現を出力(parse/と連携)
python -m fetch_egov to-juricode 140AC0000000045 36 > /tmp/keihou-art-36.md
```

## 注意事項

- APIレート制限: 1秒1リクエスト程度の自主規制(公式の明文制限なし)
- 取得した XML を Git に直接コミットしない(`cache/` はgitignore)
- e-Gov 仕様変更時は `client.py` のバージョンを上げる

## 実装ステータス

**未着手**(2026-05-14時点)。Phase 1着手と同時に最優先実装。
