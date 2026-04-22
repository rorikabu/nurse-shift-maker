# SPEC.md — 看護師シフト自動生成ツール 詳細仕様

## 1. モデル定義

### 1.1 集合

| 記号 | 意味 | 範囲 |
|------|------|------|
| `N` | 看護師数 | 3〜15 |
| `D` | その月の日数 | 28〜31 |
| `S` | シフト種別 | {休, 日, 夜, 明} |

### 1.2 シフト定数

```python
SHIFT_REST  = 0   # 休 (完全休日)
SHIFT_DAY   = 1   # 日 (日勤)
SHIFT_NIGHT = 2   # 夜 (夜勤, 翌朝まで)
SHIFT_AKE   = 3   # 明 (夜勤明け)
```

### 1.3 決定変数

```
x[n, d, s] ∈ {0, 1}   (n=0..N-1, d=0..D-1, s∈SHIFTS)
```
`x[n, d, s] = 1` ⇔ 看護師 n が 日 d に シフト s を担当

## 2. ハード制約 (15種類)

### H1. 各人各日 ちょうど1シフト
```
∀n, d:  Σ_s x[n, d, s] = 1
```

### H2. 1日あたりの最低/上限人員
```
∀d:  min_day   ≤ Σ_n x[n, d, SHIFT_DAY]   ≤ max_day
∀d:  min_night ≤ Σ_n x[n, d, SHIFT_NIGHT] ≤ max_night
```

### H3. 夜勤 → 明け の強制
```
∀n, ∀d < D-1:  x[n, d+1, SHIFT_AKE] ≥ x[n, d, SHIFT_NIGHT]
```

### H4. 明け は夜勤の翌日のみ発生
```
∀n:  x[n, 0, SHIFT_AKE] = 0
∀n, ∀d ≥ 1:  x[n, d, SHIFT_AKE] ≤ x[n, d-1, SHIFT_NIGHT]
```

### H5. 夜→明→休 パターン
```
∀n, ∀d < D-1:  x[n, d+1, SHIFT_REST] ≥ x[n, d, SHIFT_AKE]
```

### H6. 役割による夜勤禁止
夜勤を担当できる看護師は、`can_take_night(n) = (役割 != 日勤のみ) AND (夜勤可 == True)`。
```
∀n where not can_take_night(n), ∀d:  x[n, d, SHIFT_NIGHT] = 0
```

### H7. 土日固定休 (土日休 ON のスタッフ)
```
weekend_days = {d | date(year, month, d+1).weekday() ≥ 5}
∀n where 土日休(n) = True, ∀d ∈ weekend_days:  x[n, d, SHIFT_REST] = 1
```

### H8. 希望休の固定
```
∀n, ∀d ∈ off_requests[n]:  x[n, d, SHIFT_REST] = 1
```

### H9. 月間夜勤 上限
```
∀n:  Σ_d x[n, d, SHIFT_NIGHT] ≤ max_nights
```

### H10. 月間夜勤 下限 (夜勤可の看護師のみ)
```
∀n where can_take_night(n):  Σ_d x[n, d, SHIFT_NIGHT] ≥ min_nights
```

### H11. 月間休日 下限 (休のみカウント、明けは別)
```
∀n:  Σ_d x[n, d, SHIFT_REST] ≥ min_off
```

### H12. 月間休日 上限 (休のみカウント)
```
∀n:  Σ_d x[n, d, SHIFT_REST] ≤ max_off
```

### H13. 月間 最低勤務日数 (日勤+夜勤)
```
∀n:  Σ_d (x[n, d, SHIFT_DAY] + x[n, d, SHIFT_NIGHT]) ≥ min_workdays
```

### H14. 連続勤務 上限
任意の `(max_consecutive + 1)` 日の窓に 1日以上 (休 or 明)
```
∀n, ∀d ≤ D - max_consecutive - 1:
    Σ_{k=0..max_consecutive} (x[n, d+k, SHIFT_REST] + x[n, d+k, SHIFT_AKE]) ≥ 1
```

### H15. 別パターン生成 (オプション、`forbidden_solution` 指定時)
既存解 S₀ と最低 K セル異なる解を要求 (K = max(N×4, 12) が既定):
```
Σ_{(n,d) ∈ S₀} (1 - x[n, d, S₀(n,d)]) ≥ K
```

## 3. ソフト制約 (目的関数)

### 補助変数
```
workdays[n] = Σ_d (x[n, d, SHIFT_DAY] + x[n, d, SHIFT_NIGHT])
nights[n]   = Σ_d x[n, d, SHIFT_NIGHT]
rests[n]    = Σ_d x[n, d, SHIFT_REST]

max_wd = max(workdays),  min_wd = min(workdays)
max_ng = max(nights),    min_ng = min(nights)
max_rt = max(rests),     min_rt = min(rests)
```

### 目的関数 (最小化)
```
Z = 3 × (max_wd - min_wd)      # 勤務日数の公平性 (重み高)
  + 2 × (max_ng - min_ng)      # 夜勤回数の公平性
  + 2 × (max_rt - min_rt)      # 純粋な休 (REST) の公平性
```

## 4. UI 仕様

### 4.1 サイドバー入力
| 項目 | 型 | 範囲/既定値 |
|------|------|-------------|
| 年 | int | 2024〜2035 |
| 月 | int | 1〜12 |
| 看護師数 | int | 3〜15 (既定 8) |
| 日勤 最低人数 | int | 1〜10 (既定 3) |
| 日勤 上限人数 | int | 1〜15 (既定 6) |
| 夜勤 最低人数 | int | 1〜5 (既定 1) |
| 夜勤 上限人数 | int | 1〜5 (既定 2) |
| 連続勤務上限 | int | 3〜7 (既定 5) |
| 月間夜勤上限 | int | 2〜12 (既定 8) |
| 月間夜勤下限 | int | 0〜8 (既定 2) |
| 月間休日下限 (休のみ) | int | 4〜14 (既定 8) |
| 月間休日上限 (休のみ) | int | 8〜20 (既定 12) |
| 月間 最低勤務日数 | int | 0〜25 (既定 12) |
| 最大計算時間(秒) | int | 5〜60 (既定 15) |

### 4.2 看護師マスタ (data_editor)
| カラム | 型 | 選択肢 |
|---------|-----|--------|
| 氏名 | str | 自由入力 |
| 役割 | selectbox | 一般 / 日勤のみ |
| 夜勤可 | checkbox | True/False |
| 土日休 | checkbox | True/False (パートさん向け) |

### 4.3 希望休入力
看護師ごとに日付のカンマ区切りテキスト (例: `5,12,19`)

### 4.4 出力
- **タブ A / タブ B**: 同条件で別パターンも同時生成 (要 `gen_two`)
- シフト表: `DataFrame` に色付き表示 (日=緑 / 夜=紺 / 明=黄 / 休=赤)
- 集計表: 看護師ごとの日勤/夜勤/明/休/勤務計/休日計
- CSV ダウンロードボタン (UTF-8 BOM 付き, Excel 互換)
- パターンB タブには A との差分セル数 (%) を表示

## 5. INFEASIBLE 診断

### 5.1 事前チェック (`diagnose_infeasibility`) — 即時
1. 夜勤の人手不足 (必要夜勤総数 vs 容量)
2. 月間夜勤の下限 > 上限
3. 日勤・夜勤の最低 > 上限
4. 全体の勤務量過多 (必要勤務 vs 全員の最大勤務余力)
5. 特定日の希望休＋土日休 集中による稼働不足
6. 土日全般の人員不足

### 5.2 詳細診断 (`deep_diagnose`) — 各 ~4秒
事前チェックで矛盾が見つからなかった場合、以下の緩和を1つずつ試して feasibility を判定:
- 希望休を全て無視
- 土日休を全て無視
- 月間夜勤下限を 0
- 月間休日下限を `max(4, min_off-3)`
- 月間休日上限を `min(20, max_off+3)`
- 月間最低勤務日数を `max(0, min_workdays-3)`
- 連続勤務上限を `max_consecutive + 2`

「✅解けた」となった制約を緩めれば feasible になる旨を案内。

## 6. データ形式

### 6.1 入力 JSON 例 (将来の API 化を想定)
```json
{
  "year": 2026,
  "month": 5,
  "constraints": {
    "min_day": 3, "max_day": 6,
    "min_night": 1, "max_night": 2,
    "max_consecutive": 5,
    "max_nights": 8, "min_nights": 2,
    "min_off": 8, "max_off": 12,
    "min_workdays": 12
  },
  "nurses": [
    {"id": 0, "name": "田中", "role": "一般", "can_night": true,  "weekend_off": false, "off_requests": [5, 12]},
    {"id": 1, "name": "佐藤", "role": "一般", "can_night": true,  "weekend_off": false, "off_requests": []},
    {"id": 2, "name": "鈴木", "role": "日勤のみ", "can_night": false, "weekend_off": true, "off_requests": []}
  ]
}
```

### 6.2 出力 JSON 例
```json
{
  "status": "OPTIMAL",
  "objective": 12,
  "schedule": {
    "0": ["休", "夜", "明", "休", "..."],
    "1": ["日", "日", "夜", "明", "..."]
  },
  "summary": [
    {"id": 0, "day": 10, "night": 6, "ake": 5, "rest": 9}
  ]
}
```

## 7. パフォーマンス目標

| 規模 | 目標時間 (シングルワーカー) |
|------|----------|
| 5名 × 31日 | 5秒以内 |
| 8名 × 31日 | 15秒以内 (時間切れで FEASIBLE 多) |
| 12名 × 31日 | 15秒で FEASIBLE |

**注**: Python 3.14 + OR-Tools 9.15 のスレッドハング回避のため `num_search_workers = 1` 固定。マルチワーカーが復旧すれば 2〜3倍高速化見込み。

## 8. エラーハンドリング

| ステータス | UI 表示 | 対応 |
|-----------|---------|------|
| OPTIMAL | ✅ 最適解 + 目的関数値 | シフト表示 |
| FEASIBLE | ✅ 実行可能解 (時間内に最適化完了せず) | シフト表示 |
| INFEASIBLE | ❌ 制約エラー | 事前チェック → 詳細診断 |
| UNKNOWN/MODEL_INVALID | ⚠️ 時間切れ | 計算時間延長を提案 |

## 9. 今後の拡張ロードマップ

### Phase 1 (実運用投入)
- 前月末シフト引き継ぎ (月初の明け・休反映)
- 既存シフトの部分ロック (手動調整)
- 希望休の優先度 (第1〜第3希望)

### Phase 2 (ユーザビリティ)
- 看護師マスタの CSV インポート
- 過去シフトの保存・再利用
- ブラウザ間永続化 (SQLite)

### Phase 3 (高度化)
- ペア制約 (組みたい/避けたい)
- スキルレベル別配置
- 土日のみ別人員要件 (`min_day_weekend`, `min_night_weekend`)
- 有給・研修日の別入力欄

### Phase 4 (SaaS 化)
- 施設マルチテナント
- 月次バックアップ
- 印刷用 PDF 出力
