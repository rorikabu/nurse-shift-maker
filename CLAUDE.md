# CLAUDE.md

> このファイルは Claude Code がこのリポジトリで作業する際のコンテキスト・規約を記述します。

## プロジェクト概要

**看護師シフト自動生成ツール**
- 対象: 小規模クリニック（〜15名）
- シフト体系: 2交代制（日勤 / 夜勤）+ 明け + 休
- 目的: 労務制約を満たした上で勤務日数・夜勤回数・純粋な休の3軸でばらつきを最小化するシフトを自動生成
- UI: タブ構成（シフト作成 / ルール・使い方）。同条件で別パターン B も同時生成可能。

## 技術スタック

- **Python 3.14**
- **Streamlit** (UI)
- **OR-Tools CP-SAT** (制約最適化ソルバー)
- **pandas** (データ操作・表示)

## ファイル構成

```
nurse_shift_tool/
├── shift_optimizer.py   # メインアプリ (Streamlit + OR-Tools)
├── test_solver.py       # Streamlit 無しのロジック単体テスト
├── requirements.txt     # 依存パッケージ
├── README.md           # エンドユーザ向け使用法
├── CLAUDE.md           # このファイル (Claude Code 用)
└── SPEC.md             # 詳細仕様 (制約・目的関数・データモデル)
```

## 開発コマンド

```bash
# 依存導入 (venv 推奨)
python3.14 -m venv venv
./venv/bin/pip install -r requirements.txt

# アプリ起動 (ポート 8504, iCloud 誤リロード対策付き)
./venv/bin/streamlit run shift_optimizer.py \
    --server.port 8504 \
    --server.headless true \
    --server.fileWatcherType none

# ロジックの単体確認 (Streamlit 不要)
./venv/bin/python test_solver.py
```

## コード規約

### 命名
- 変数 `x[n, d, s]` は「決定変数 (nurse, day, shift)」で統一。他の意味には使わない
- シフト定数は必ず `SHIFT_REST / SHIFT_DAY / SHIFT_NIGHT / SHIFT_AKE` を参照。マジックナンバー禁止
- 「夜勤を担当できるか」の判定は `can_take_night(nurse_df, n)` ヘルパーを使用（個別に役割と夜勤可をチェックしない）

### 制約の分類
追加する制約は以下のどちらかを明示:
- **ハード制約**: `model.Add(...)` で強制。満たせない場合 INFEASIBLE
- **ソフト制約**: `model.Minimize(...)` の項として組み込み。重みも明示

制約を追加するときは必ず:
1. `SPEC.md` のハード/ソフト一覧にも追記
2. ルール一覧タブの `hard_rules` / `soft_rules` リストにも追加（番号も振り直し）
3. 数式メモ（expander 内）も更新
4. INFEASIBLE 診断（`diagnose_infeasibility` / `deep_diagnose`）に矛盾チェックや緩和テストを追加

### 制約緩和オプション
`build_and_solve()` は以下の override 系引数で個別制約を緩和できる:
- `omit_off_requests`, `omit_weekend_off`
- `override_min_nights`, `override_min_off`, `override_max_off`, `override_min_workdays`, `override_max_consecutive`
- `feasibility_only=True` で目的関数を省略（高速化）
- `forbidden_solution` で別パターン生成（既存解と最低 K セル異なる解を要求）

### テスト
新しい制約を追加したら **必ず `test_solver.py` でも同じ制約を追加** し:
```bash
./venv/bin/python test_solver.py
```
`FEASIBLE` か `OPTIMAL` が出ること。

## 現在の実装状況

### 実装済み (ハード制約 15種類)
- [x] 各人各日ちょうど1シフト
- [x] 1日あたり日勤・夜勤の最低人員 / 上限人員
- [x] 夜勤翌日は必ず明け
- [x] 明けは夜勤翌日のみ発生
- [x] 夜→明→休 パターン (明けの翌日は必ず休)
- [x] 役割「日勤のみ」「夜勤不可」の夜勤禁止
- [x] 「土日休」ONのスタッフは土日固定休
- [x] 希望休の固定 (第1希望のみ)
- [x] 月間夜勤の上下限
- [x] 月間休日 (休のみ) の下限・上限
- [x] 月間 最低勤務日数 (日+夜)
- [x] 連続勤務日数の上限

### 実装済み (ソフト制約)
- [x] 勤務日数の最大-最小差 × 3
- [x] 夜勤回数の最大-最小差 × 2
- [x] 純粋な休 (REST) の最大-最小差 × 2

### 実装済み (UI / UX)
- [x] タブ構成（シフト作成 / ルール・使い方）
- [x] パターンA + パターンB 同時生成（同条件・別組み合わせ）
- [x] INFEASIBLE 時の事前数値チェック（`diagnose_infeasibility`）
- [x] INFEASIBLE 時の制約緩和診断（`deep_diagnose`）
- [x] CSV ダウンロード（パターンごと）
- [x] 用語集・トラブルシュート

### 未実装 (優先度順)
- [ ] 前月末シフトの引き継ぎ (月初の明け・休反映)
- [ ] 既存シフトのロック (部分手動調整対応)
- [ ] 希望休の第1〜第3希望 (優先度付き)
- [ ] 有給休暇・研修日の固定
- [ ] ペア制約 (組みたい/避けたい)
- [ ] スキルレベル別の配置要件
- [ ] 土日祝の人員調整 (土日のみ最低人員を別設定)
- [ ] CSV/Excel からのインポート

## ハマりどころメモ

### Python 3.14 + OR-Tools 9.15 のスレッドハング
`CpSolver().Solve()` が並列ワーカー（デフォルト 8）でハングする既知問題。
**必須対応**: `solver.parameters.num_search_workers = 1`

### INFEASIBLE になりやすいパターン
1. **月間休日上限を厳しくしすぎ** → 夜勤しない人が日勤を多く取らされる必要があるが、必要人員制約と衝突
2. **月間最低勤務日数 + 月間休日下限の両立失敗** → 合計が日数を超えると詰む
3. **日勤上限/夜勤上限 < 最低人員** → 即矛盾
4. **夜→明→休 + 月間休日下限が高い + 月間夜勤下限が高い** → 休日数が足りなくなる
5. **土日休スタッフ多数 + 土日の最低人員が標準と同じ** → 土日に必要人員確保不可

### OR-Tools の落とし穴
- `AddMaxEquality` / `AddMinEquality` は整数変数が必要。Bool の合計式を渡す前に IntVar 経由で受けること
- `OnlyEnforceIf` は Bool 変数にしか使えない
- 目的関数の重みは整数化（小数は使えないので 10倍などでスケール）

### pandas 3.0 の API 変更
- `Styler.applymap` は廃止 → `Styler.map` を使用

## 設計思想

### なぜ明け (SHIFT_AKE) を独立シフトにしたか
単純に「夜勤翌日=休」にすると、明けの日にフォローアップ業務（引き継ぎ・記録整理）が入る現実を表現できない。明けを別カテゴリにすることで後から「明けに限り午前のみ出勤可」のような拡張が可能。

### なぜ「休のみ」と「休+明」を区別するか
明けは夜勤に1:1で付随する強制休なので、「真の休日」とは性質が違う。月間休日下限・上限を「休のみ」でカウントすることで、夜勤しない人が休を持ちすぎる問題を直接制御できる。

### 公平性の3軸 (重み 3, 2, 2)
- 勤務日数差 (× 3): 主観的不公平感が最も強いため重み高
- 夜勤回数差 (× 2): 上下限で既に絞られているがバランス調整
- 純粋な休の差 (× 2): 夜勤の有無で休数に差が出るため別軸で調整

### Web 公開対応設計
- ファイル書き込みなし
- 状態は全て `st.session_state`
- 環境変数・ローカルパス依存なし
- → Streamlit Community Cloud 等にそのままデプロイ可能

## 拡張時の指針

### 前月末引き継ぎを実装する場合
- 新パラメータ: `prev_month_last_shift: dict[nurse_id, SHIFT]` を UI から受ける
- day=0 の制約に反映:
  - 前月最終日が夜 → day=0 は明 に固定
  - 前月最終日が明 → day=0 は休 に固定
- 連続勤務カウントも前月末から何連勤かを考慮

### 既存シフトのロック
- `locked: dict[(nurse, day), SHIFT]` を受ける
- 該当する `x[n,d,s]` を 1 に固定、他のシフトは 0

### 希望休の優先度
- 第1希望は現状通りハード制約
- 第2・第3希望はソフト制約化（ペナルティ付き）
- UI は「日付:優先度」のペアで入力

### 土日のみ別人員要件
- サイドバーに `min_day_weekend`, `min_night_weekend` を追加
- `for d in weekend_days:` の人員制約を別途設定
