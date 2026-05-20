# 用語集 (Glossary)

JuriCode-JPで使用する**法令略称・専門用語の日英対訳辞書**。新しい法令を扱うときは、まずこの表に略称を登録すること。

---

## 1. 法令略称(ローマ字短縮名)

ローマ字略称はファイル・ディレクトリ命名に使用する。ヘボン式、ハイフン区切り、全て小文字。

| 法令名(日本語) | 法令名(英語) | ローマ字略称 | e-Gov 法令ID |
|---|---|---|---|
| 日本国憲法 | The Constitution of Japan | `kenpou` | 321CONSTITUTION |
| 刑法 | Penal Code | `keihou` | 140AC0000000045 |
| 刑事訴訟法 | Code of Criminal Procedure | `keiji-soshou-hou` | 323AC0000000131 |
| 警察法 | Police Act | `keisatsu-hou` | 329AC0000000162 |
| 警察官職務執行法 | Police Duties Execution Act | `keisatsukan-shokumu-shikkou-hou` | 323AC0000000136 |
| 軽犯罪法 | Minor Offenses Act | `keihanzai-hou` | 323AC0000000039 |
| ストーカー行為等の規制等に関する法律 | Anti-Stalking Act | `stalker-kisei-hou` | 412AC0100000081 |
| 民法 | Civil Code | `minpou` | 129AC0000000089 |
| 商法 | Commercial Code | `shouhou` | 132AC0000000048 |
| 会社法 | Companies Act | `kaisha-hou` | 417AC0000000086 |
| 独占禁止法 | Antimonopoly Act | `dokusen-kinshi-hou` | 322AC0000000054 |
| 個人情報の保護に関する法律 | Act on the Protection of Personal Information | `kojin-jouhou-hogo-hou` | 415AC0000000057 |
| 国税通則法 | Act on General Rules for National Taxes | `kokuzei-tsuusoku-hou` | 337AC0000000066 |
| 法人税法 | Corporation Tax Act | `houjin-zei-hou` | 340AC0000000034 |
| 所得税法 | Income Tax Act | `shotoku-zei-hou` | 340AC0000000033 |
| 消費税法 | Consumption Tax Act | `shouhi-zei-hou` | 363AC0000000108 |
| 相続税法 | Inheritance Tax Act | `souzoku-zei-hou` | 325AC0000000073 |
| 地方税法 | Local Tax Act | `chihou-zei-hou` | 325AC0000000226 |
| 道路交通法 | Road Traffic Act | `douro-koutsuu-hou` | 335AC0000000105 |

> **注**: e-Gov 法令ID(法令番号)は本表の参考値。実装時には e-Gov API のレスポンスで最終確認すること。

---

## 2. 法令構造の単位

| 日本語 | 英語(政府公定訳) | YAML key |
|---|---|---|
| 編 | Part | `hen` |
| 章 | Chapter | `shou` |
| 節 | Section | `setsu` |
| 款 | Subsection | `kan` |
| 目 | Division | `moku` |
| 条 | Article | `jou` / `article` |
| 項 | Paragraph | `kou` / `paragraph` |
| 号 | Item | `gou` / `item` |
| 但書 | Proviso | `tadashigaki` / `proviso` |
| 前段 | First sentence | `zendan` |
| 後段 | Second sentence | `koudan` |

---

## 3. 判例関連

| 日本語 | 英語 | 略号 |
|---|---|---|
| 最高裁判所大法廷 | Supreme Court (Grand Bench) | 最大判/最大決 |
| 最高裁判所第一/二/三小法廷 | Supreme Court (First/Second/Third Petty Bench) | 最判/最決 |
| 高等裁判所 | High Court | 高判 |
| 地方裁判所 | District Court | 地判 |
| 簡易裁判所 | Summary Court | 簡判 |
| 家庭裁判所 | Family Court | 家審 |
| 判決 | Judgment | 判 |
| 決定 | Decision (Order) | 決 |
| 命令 | Order | 命 |

### 判例集略称

| 略称 | 正式名 |
|---|---|
| 民集 | 最高裁判所民事判例集 |
| 刑集 | 最高裁判所刑事判例集 |
| 集民 | 最高裁判所裁判集民事 |
| 集刑 | 最高裁判所裁判集刑事 |
| 判時 | 判例時報 |
| 判タ | 判例タイムズ |
| 金判 | 金融・商事判例 |
| LEX/DB | LEX/DB(判例検索データベース) |

---

## 4. 刑法用語

| 日本語 | 英語(政府公定訳) |
|---|---|
| 故意 | Intent / Willful intent |
| 過失 | Negligence |
| 違法性阻却事由 | Grounds of justification |
| 責任阻却事由 | Grounds of excuse |
| 正当防衛 | Self-defense (legitimate defense) |
| 緊急避難 | Necessity (act of necessity) |
| 過剰防衛 | Excessive defense |
| 共犯 | Complicity |
| 教唆 | Incitement |
| 幇助 | Aiding |
| 未遂 | Attempt |
| 既遂 | Consummated offense |
| 拘禁刑 | Imprisonment(2025年6月以降統一) |
| 罰金 | Fine |
| 科料 | Petty fine |

---

## 5. 刑事訴訟用語(抜粋)

| 日本語 | 英語 |
|---|---|
| 起訴 | Indictment / Prosecution |
| 不起訴 | Non-prosecution |
| 略式起訴 | Summary indictment |
| 公訴提起 | Institution of public prosecution |
| 勾留 | Detention |
| 逮捕 | Arrest |
| 捜査 | Investigation |
| 取調べ | Interrogation |
| 調書 | Written statement / Record |
| 公判 | Trial |
| 証拠 | Evidence |
| 自白 | Confession |

---

## 6. ライセンス・出典関連

| 日本語 | 英語 |
|---|---|
| 政府公定訳 | Official translation |
| 日本法令外国語訳データベース | Japanese Law Translation Database System (JLT) |
| パブリックドメイン | Public domain |
| 引用 | Quotation |
| 改変禁止 | No derivatives (ND) |
| 著作権法第13条(権利の目的とならない著作物) | Article 13 of the Copyright Act |

---

## 用語追加のガイドライン

新しい法令や用語を扱う際は:
1. まずこのファイルに登録してから作業すること
2. 政府公定訳がある場合はそれを優先(JLT-DB: http://www.japaneselawtranslation.go.jp/)
3. 公定訳がない場合は `(*community-translation)` の注記を末尾に付ける
4. 登録は PR の `docs:` スコープで
