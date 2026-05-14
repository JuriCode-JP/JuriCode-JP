# tools/ — 取得・変換・検証スクリプト

JuriCode-JPで使用するツール群を置くディレクトリ。Pythonを中心に、必要に応じてNode.js等も使用。

## 構成

```
tools/
├── fetch-egov/    # e-Gov 法令APIからの取得
├── parse/         # XML → 中間表現(JuriCode-JP形式)
├── validate/      # スキーマ・データ検証
└── translate/     # 英訳補助(Claude APIなど)
```

各サブディレクトリにREADME.mdで詳細を記載。

## 共通ポリシー

### 言語選定
- メイン言語: **Python 3.11+**
- 補助スクリプト・CLI用途: Node.js / TypeScript も可
- 法令データ自体は言語非依存(Markdown + YAML + JSON)

### 依存管理
- Python: `pyproject.toml` + `uv` または `pip-tools`
- ロックファイルは必ずコミット

### 既存OSSの活用優先
- e-Gov XML パース: [`ja-law-parser`](https://github.com/takuyaa/ja-law-parser) を直接利用検討
- Lawtext変換: [`Lawtext`](https://github.com/yamachig/Lawtext) のCLIをラップ
- 独自パーサーは**ラストリゾート**

### テスト
- 全ツールに対応するテストを `tests/` (将来追加)に配置
- 法令データ自体への破壊的処理(削除、上書き)を伴うツールは必ずdry-runモードを持つ

### キャッシュ・ダウンロード
- e-Gov APIから取得したXMLは `tools/fetch-egov/cache/` にキャッシュ(`.gitignore` で除外)
- ネットワーク不要での再現性を担保

### 認証
- e-Gov 法令APIは現時点で認証不要
- Claude API等の認証は `.env` で管理(`.gitignore` 済)
