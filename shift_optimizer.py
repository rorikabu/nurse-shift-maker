"""
看護師シフト自動生成ツール (2交代制・クリニック向け)
============================================
- Streamlit UI (タブ構成: シフト作成 / ルール・使い方)
- OR-Tools CP-SAT による制約最適化
- 最大15名程度まで高速に解ける
- Web 公開 (Streamlit Community Cloud 等) を想定:
  * ファイル書き込みを行わない
  * 全状態を st.session_state に保持
  * 環境変数・ローカルパス依存なし
"""

import calendar
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import holidays
import pandas as pd
import streamlit as st
from ortools.sat.python import cp_model

# ==========================================================
# ページ設定
# ==========================================================
st.set_page_config(page_title="助産師シフトメーカー 🌸", layout="wide", page_icon="🩺")

# ---- カスタムCSS: ふんわり可愛い看護師テイスト ----
st.markdown(
    """
<style>
    /* タイトル: グラデーション風の可愛いピンク */
    h1 {
        color: #E91E63 !important;
        font-weight: 700;
        letter-spacing: 0.02em;
        background: linear-gradient(90deg, #FCE4EC 0%, #FFFFFF 100%);
        padding: 0.6rem 1.2rem;
        border-radius: 18px;
        border-left: 6px solid #F48FB1;
        margin-bottom: 0.5rem;
    }
    /* 各セクション見出し */
    h2, h3 {
        color: #C2185B !important;
        border-bottom: 2px dashed #F8BBD0;
        padding-bottom: 0.3rem;
        margin-top: 1.2rem !important;
    }
    /* ボタン: 丸くふんわり */
    .stButton > button {
        border-radius: 22px !important;
        border: 2px solid #F48FB1 !important;
        background: linear-gradient(135deg, #FCE4EC 0%, #F8BBD0 100%) !important;
        color: #880E4F !important;
        font-weight: 700 !important;
        padding: 0.5rem 1.5rem !important;
        box-shadow: 0 3px 8px rgba(244, 143, 177, 0.25) !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 5px 12px rgba(244, 143, 177, 0.4) !important;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #F48FB1 0%, #EC407A 100%) !important;
        color: white !important;
    }
    /* ダウンロードボタン */
    .stDownloadButton > button {
        border-radius: 18px !important;
        background: #B2DFDB !important;
        border: 2px solid #80CBC4 !important;
        color: #004D40 !important;
        font-weight: 600 !important;
    }
    /* タブ: 丸くて可愛く */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        background: #FFFFFF;
        border: 2px solid #F8BBD0;
        border-radius: 16px 16px 0 0;
        padding: 0.5rem 1.2rem;
        color: #C2185B;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #F48FB1 0%, #FCE4EC 100%) !important;
        color: #880E4F !important;
    }
    /* サイドバー: 優しい色 */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #FCE4EC 0%, #FFF8FA 100%) !important;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #AD1457 !important;
    }
    /* コンテナ・カード */
    div[data-testid="stContainer"] {
        border-radius: 16px !important;
    }
    /* チェックボックス・スライダーのアクセント色 */
    .stCheckbox > label > div[role="checkbox"][aria-checked="true"] {
        background-color: #F48FB1 !important;
    }
    /* 各種メッセージ */
    div[data-testid="stAlert"] {
        border-radius: 14px !important;
        border-left-width: 5px !important;
    }
    /* テーブルの角丸 */
    .stDataFrame {
        border-radius: 14px !important;
        overflow: hidden;
    }
    /* カードコンテナ (ルール一覧の枠) */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #FFFFFF;
        border-radius: 16px !important;
        border: 1.5px solid #F8BBD0 !important;
        box-shadow: 0 2px 6px rgba(244, 143, 177, 0.12);
    }
</style>
    """,
    unsafe_allow_html=True,
)

st.title("🩺 助産師シフトメーカー 🌸")
st.caption("✨ 2交代制（日勤・夜勤）/ クリニックさん向け / 公平・かんたん・自動でシフト作成 ✨")

# シフト定義
SHIFT_REST = 0    # 休
SHIFT_DAY = 1     # 日勤
SHIFT_NIGHT = 2   # 夜勤
SHIFT_AKE = 3     # 明け (夜勤翌日の休み)
SHIFTS = [SHIFT_REST, SHIFT_DAY, SHIFT_NIGHT, SHIFT_AKE]
SHIFT_LABEL = {0: "休", 1: "日", 2: "夜", 3: "明"}

# 看護師リストのスキーマ版数。カラム追加・選択肢変更時にインクリメントすると
# 古いセッションのデータが自動的に初期化される。
NURSE_DF_SCHEMA_VERSION = 4

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]
JP_HOLIDAYS = holidays.Japan()

# 保存先 (アプリと同じフォルダ)。ローカル利用を想定。
# 注: Streamlit Community Cloud 等の共有環境では、複数ユーザーで1ファイルを共用する
# ことになるため、ユーザー識別が必要な場合は別途対応が必要。
STATE_FILE = Path(__file__).resolve().parent / "nurse_shift_state.json"

# 保存/復元対象のサイドバー設定キー
SIDEBAR_KEYS = [
    "year", "month", "num_nurses",
    "min_day", "max_day", "min_night", "max_night",
    "max_consecutive", "max_nights", "min_nights",
    "min_off", "max_off", "min_workdays",
    "max_ake_to_night",
    "time_limit",
]


def load_saved_state():
    """保存済み状態を読み込む。エラー時は空辞書を返す。"""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(nurse_df, off_requests_text, settings=None):
    """看護師リスト・希望休・サイドバー設定を JSON で保存する。"""
    try:
        payload = {
            "schema_version": NURSE_DF_SCHEMA_VERSION,
            "nurses": nurse_df.to_dict(orient="records"),
            "off_requests_text": off_requests_text,
            "settings": settings or {},
        }
        STATE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass  # 保存失敗しても動作継続


def clear_saved_state():
    """保存ファイルを削除。"""
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
    except Exception:
        pass


def can_take_night(nurse_df, n):
    """看護師 n が夜勤を担当できるか (役割が「パート」でなく、かつ「夜勤可」がON)。"""
    return nurse_df.loc[n, "役割"] != "パート" and bool(nurse_df.loc[n, "夜勤可"])


def get_weekend_days():
    """その月の土曜・日曜の日インデックス (0-based) を返す。"""
    return [d for d in range(num_days) if date(year, month, d + 1).weekday() >= 5]


def get_weekend_or_holiday_days():
    """土日＋祝日の日インデックス (0-based)。「土日休」スタッフの固定休日用。"""
    return [
        d for d in range(num_days)
        if date(year, month, d + 1).weekday() >= 5
        or date(year, month, d + 1) in JP_HOLIDAYS
    ]


def is_holiday(d):
    """その月の日インデックス d (0-based) が祝日かどうか。"""
    return date(year, month, d + 1) in JP_HOLIDAYS


def get_holiday_name(d):
    """その月の日インデックス d の祝日名 (祝日でなければ None)。"""
    return JP_HOLIDAYS.get(date(year, month, d + 1))


@dataclass
class RelaxOptions:
    """INFEASIBLE 診断や別パターン生成で個別制約を緩和するためのオプション。"""
    omit_off_requests: bool = False           # 希望休を全て無視
    omit_weekend_off: bool = False            # 土日休を全て無視
    override_min_nights: Optional[int] = None  # 月間夜勤下限の差替え
    override_min_off: Optional[int] = None     # 月間休日下限の差替え
    override_max_off: Optional[int] = None     # 月間休日上限の差替え
    override_min_workdays: Optional[int] = None  # 最低勤務日数の差替え
    override_max_consecutive: Optional[int] = None  # 連続勤務上限の差替え
    override_max_ake_to_night: Optional[int] = None  # 明け→夜勤回数上限の差替え

# ==========================================================
# サイドバー: 設定 (両タブ共通で表示)
# ==========================================================
# サイドバー初期値を保存済み state から一度だけ復元
if not st.session_state.get("sidebar_loaded"):
    saved_settings = load_saved_state().get("settings", {})
    for k, v in saved_settings.items():
        if k in SIDEBAR_KEYS and k not in st.session_state:
            st.session_state[k] = v
    st.session_state.sidebar_loaded = True

with st.sidebar:
    st.markdown("### 🌷 設定パネル")
    st.caption("ここをいじって、シフトの条件を決めてね")

    st.header("📅 いつのシフト？")
    today = date.today()
    year = st.number_input("年", 2024, 2035, today.year, key="year")
    month = st.number_input("月", 1, 12, today.month, key="month")
    _, num_days = calendar.monthrange(year, month)
    st.caption(f"🌸 → {num_days}日間")

    st.header("👩‍⚕️ スタッフ人数")
    num_nurses = st.number_input("看護師さんの人数", 3, 15, 8, key="num_nurses")

    st.header("💉 1日あたりの人員")
    min_day = st.number_input("☀️ 日勤 最低人数", 1, 10, 3, key="min_day")
    max_day = st.number_input("☀️ 日勤 上限人数", 1, 15, 6, key="max_day",
                              help="1日あたり日勤に入れる最大人数。最低人数以上にしてください。")
    min_night = st.number_input("🌙 夜勤 最低人数", 1, 5, 1, key="min_night")
    max_night = st.number_input("🌙 夜勤 上限人数", 1, 5, 2, key="max_night",
                                help="1日あたり夜勤に入れる最大人数。最低人数以上にしてください。")

    st.header("💖 労務条件")
    max_consecutive = st.number_input("📌 連続勤務 上限(日)", 3, 7, 5, key="max_consecutive")
    max_nights = st.number_input("🌙 月間夜勤 上限(回)", 2, 12, 8, key="max_nights")
    min_nights = st.number_input("🌙 月間夜勤 下限(回)", 0, 8, 2, key="min_nights")
    min_off = st.number_input("🌸 月間休日 下限（休のみ）", 4, 14, 8, key="min_off")
    max_off = st.number_input("🌸 月間休日 上限（休のみ）", 8, 20, 12, key="max_off",
                              help="この日数より多くの「休」を持てない。夜勤しない人の休過剰を防ぐ。")
    min_workdays = st.number_input("📋 月間 最低勤務日数（日勤+夜勤）", 0, 25, 12, key="min_workdays",
                                   help="1人あたり月の勤務日数(日+夜)の最低ライン。")
    max_ake_to_night = st.number_input("🌙 明け後夜勤 上限（月間・該当者のみ）", 0, 15, 3, key="max_ake_to_night",
                                       help="「明け後夜勤OK」がONのスタッフが、月のうち何回まで「明け→夜勤」パターンを取れるか。0にすると実質的に特例OFF。")

    st.header("⏱️ 計算スピード")
    time_limit = st.slider("最大計算時間(秒)", 5, 60, 15, key="time_limit")

# ==========================================================
# 最適化ロジック
# ==========================================================
def build_and_solve(nurse_df, off_requests, *,
                    relax=None,
                    feasibility_only=False,
                    time_limit_s=None,
                    forbidden_solution=None,
                    min_diff_cells=None):
    r = relax or RelaxOptions()
    N, D = num_nurses, num_days
    eff_min_nights = r.override_min_nights if r.override_min_nights is not None else min_nights
    eff_min_off = r.override_min_off if r.override_min_off is not None else min_off
    eff_max_off = r.override_max_off if r.override_max_off is not None else max_off
    eff_min_workdays = r.override_min_workdays if r.override_min_workdays is not None else min_workdays
    eff_max_consec = r.override_max_consecutive if r.override_max_consecutive is not None else max_consecutive
    eff_max_ake_to_night = r.override_max_ake_to_night if r.override_max_ake_to_night is not None else max_ake_to_night
    model = cp_model.CpModel()

    # 変数: x[n,d,s] = nurse n が day d に shift s を担当するか
    x = {(n, d, s): model.NewBoolVar(f"x_{n}_{d}_{s}")
         for n in range(N) for d in range(D) for s in SHIFTS}

    # 各人各日 ちょうど1シフト
    for n in range(N):
        for d in range(D):
            model.AddExactlyOne([x[n, d, s] for s in SHIFTS])

    # 1日ごとの人数制約 (下限・上限)
    for d in range(D):
        day_count = sum(x[n, d, SHIFT_DAY] for n in range(N))
        night_count = sum(x[n, d, SHIFT_NIGHT] for n in range(N))
        model.Add(day_count >= min_day)
        model.Add(day_count <= max_day)
        model.Add(night_count >= min_night)
        model.Add(night_count <= max_night)

    # 夜勤 → 翌日は必ず明け
    for n in range(N):
        for d in range(D - 1):
            model.Add(x[n, d + 1, SHIFT_AKE] >= x[n, d, SHIFT_NIGHT])

    # 明けは夜勤の翌日のみ発生
    for n in range(N):
        model.Add(x[n, 0, SHIFT_AKE] == 0)
        for d in range(1, D):
            model.Add(x[n, d, SHIFT_AKE] <= x[n, d - 1, SHIFT_NIGHT])

    # 夜勤 → 明け → 休 パターン: 明けの翌日は必ず休
    # ただし「明け後夜勤OK」がONのスタッフは特例として除外 (明けの翌日に夜勤可)
    for n in range(N):
        if bool(nurse_df.loc[n, "明け後夜勤OK"]):
            continue
        for d in range(D - 1):
            model.Add(x[n, d + 1, SHIFT_REST] >= x[n, d, SHIFT_AKE])

    # 明け後夜勤OK スタッフの「明け→夜勤」パターン回数制限
    # aux[d] = 1 iff 明(d) AND 夜(d+1) の両方が成立
    for n in range(N):
        if not bool(nurse_df.loc[n, "明け後夜勤OK"]):
            continue
        ake_to_night_vars = []
        for d in range(D - 1):
            aux = model.NewBoolVar(f"ake_to_night_{n}_{d}")
            model.Add(aux <= x[n, d, SHIFT_AKE])
            model.Add(aux <= x[n, d + 1, SHIFT_NIGHT])
            model.Add(aux >= x[n, d, SHIFT_AKE] + x[n, d + 1, SHIFT_NIGHT] - 1)
            ake_to_night_vars.append(aux)
        model.Add(sum(ake_to_night_vars) <= eff_max_ake_to_night)

    # 役割ごとの制約 (夜勤不可の人は夜勤シフトを禁止)
    for n in range(N):
        if not can_take_night(nurse_df, n):
            for d in range(D):
                model.Add(x[n, d, SHIFT_NIGHT] == 0)

    # 土日・祝日 固定休 (該当スタッフは全ての土曜・日曜・祝日が必ず休)
    if not r.omit_weekend_off:
        off_days = get_weekend_or_holiday_days()
        for n in range(N):
            if bool(nurse_df.loc[n, "土日休"]):
                for d in off_days:
                    model.Add(x[n, d, SHIFT_REST] == 1)

    # 希望休
    if not r.omit_off_requests:
        for n, days in off_requests.items():
            for day in days:
                if 1 <= day <= D:
                    model.Add(x[n, day - 1, SHIFT_REST] == 1)

    # 月間夜勤 上下限
    for n in range(N):
        nights_n = sum(x[n, d, SHIFT_NIGHT] for d in range(D))
        model.Add(nights_n <= max_nights)
        if can_take_night(nurse_df, n):
            model.Add(nights_n >= eff_min_nights)

    # 月間休日 下限・上限 (純粋な「休」のみ。明けは夜勤と1:1で付与されるためカウントしない)
    for n in range(N):
        rest_n = sum(x[n, d, SHIFT_REST] for d in range(D))
        model.Add(rest_n >= eff_min_off)
        model.Add(rest_n <= eff_max_off)

    # 月間 最低勤務日数 (日勤 + 夜勤)
    for n in range(N):
        work_n = sum(x[n, d, SHIFT_DAY] + x[n, d, SHIFT_NIGHT] for d in range(D))
        model.Add(work_n >= eff_min_workdays)

    # 連続勤務制限: 任意の (eff_max_consec + 1) 日窓に 1日以上「休 or 明」
    for n in range(N):
        for d in range(D - eff_max_consec):
            window = [x[n, d + k, SHIFT_REST] + x[n, d + k, SHIFT_AKE]
                     for k in range(eff_max_consec + 1)]
            model.Add(sum(window) >= 1)

    # 別パターン生成用: 既存解と最低 K セル異なる解を要求
    if forbidden_solution is not None:
        diff_terms = []
        for (n, d), s in forbidden_solution.items():
            diff_terms.append(1 - x[n, d, s])
        K = min_diff_cells if min_diff_cells is not None else max(N * 4, 12)
        model.Add(sum(diff_terms) >= K)

    if not feasibility_only:
        # 公平性: 勤務日数・夜勤回数・純粋な休の3軸でばらつきを最小化
        workdays = [sum(x[n, d, SHIFT_DAY] + x[n, d, SHIFT_NIGHT] for d in range(D)) for n in range(N)]
        nights = [sum(x[n, d, SHIFT_NIGHT] for d in range(D)) for n in range(N)]
        rests = [sum(x[n, d, SHIFT_REST] for d in range(D)) for n in range(N)]
        max_wd = model.NewIntVar(0, D, "max_wd")
        min_wd = model.NewIntVar(0, D, "min_wd")
        max_ng = model.NewIntVar(0, D, "max_ng")
        min_ng = model.NewIntVar(0, D, "min_ng")
        max_rt = model.NewIntVar(0, D, "max_rt")
        min_rt = model.NewIntVar(0, D, "min_rt")
        model.AddMaxEquality(max_wd, workdays)
        model.AddMinEquality(min_wd, workdays)
        model.AddMaxEquality(max_ng, nights)
        model.AddMinEquality(min_ng, nights)
        model.AddMaxEquality(max_rt, rests)
        model.AddMinEquality(min_rt, rests)
        model.Minimize(
            (max_wd - min_wd) * 3
            + (max_ng - min_ng) * 2
            + (max_rt - min_rt) * 2
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s if time_limit_s is not None else time_limit)
    # Python 3.14 + ortools 9.15 では並列ソルバがハングするため単一ワーカーに固定
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    return solver, status, x


def deep_diagnose(nurse_df, off_requests):
    """各制約を1つずつ緩めてみて、どれが原因かを特定する。"""
    weekend_off_n = sum(1 for i in range(num_nurses) if bool(nurse_df.loc[i, "土日休"]))
    has_off_req = any(len(v) > 0 for v in off_requests.values())

    tests = []
    if has_off_req:
        tests.append(("希望休を全て無視したら", RelaxOptions(omit_off_requests=True)))
    if weekend_off_n > 0:
        tests.append(("土日休を全て無視したら", RelaxOptions(omit_weekend_off=True)))
    tests.append((f"月間夜勤の下限を 0 にしたら（現在 {min_nights}）",
                  RelaxOptions(override_min_nights=0)))
    tests.append((f"月間休日の下限を {max(4, min_off-3)} にしたら（現在 {min_off}）",
                  RelaxOptions(override_min_off=max(4, min_off - 3))))
    tests.append((f"月間休日の上限を {min(20, max_off+3)} にしたら（現在 {max_off}）",
                  RelaxOptions(override_max_off=min(20, max_off + 3))))
    tests.append((f"月間最低勤務日数を {max(0, min_workdays-3)} にしたら（現在 {min_workdays}）",
                  RelaxOptions(override_min_workdays=max(0, min_workdays - 3))))
    tests.append((f"連続勤務上限を {max_consecutive + 2} にしたら（現在 {max_consecutive}）",
                  RelaxOptions(override_max_consecutive=max_consecutive + 2)))
    ake_to_night_flagged = any(bool(nurse_df.loc[i, "明け後夜勤OK"]) for i in range(num_nurses))
    if ake_to_night_flagged:
        tests.append((f"明け後夜勤の上限を {min(15, max_ake_to_night + 3)} にしたら（現在 {max_ake_to_night}）",
                      RelaxOptions(override_max_ake_to_night=min(15, max_ake_to_night + 3))))

    results = []
    for label, relax_opt in tests:
        try:
            _, st_, _ = build_and_solve(
                nurse_df, off_requests,
                relax=relax_opt, feasibility_only=True, time_limit_s=4.0,
            )
            feasible = st_ in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        except Exception as e:
            feasible = False
            st_ = str(e)
        results.append((label, feasible, st_))
    return results


def build_schedule_df(solver, x, nurse_df):
    rows = []
    for n in range(num_nurses):
        row = {"氏名": nurse_df.loc[n, "氏名"]}
        for d in range(num_days):
            wkd = WEEKDAY_JP[date(year, month, d + 1).weekday()]
            col_name = f"{d + 1}({wkd}・祝)" if is_holiday(d) else f"{d + 1}({wkd})"
            for s in SHIFTS:
                if solver.Value(x[n, d, s]) == 1:
                    row[col_name] = SHIFT_LABEL[s]
                    break
        rows.append(row)
    return pd.DataFrame(rows)


def build_summary_df(solver, x, nurse_df):
    data = {
        "氏名": nurse_df["氏名"].tolist(),
        "日勤": [sum(solver.Value(x[n, d, SHIFT_DAY]) for d in range(num_days)) for n in range(num_nurses)],
        "夜勤": [sum(solver.Value(x[n, d, SHIFT_NIGHT]) for d in range(num_days)) for n in range(num_nurses)],
        "明け": [sum(solver.Value(x[n, d, SHIFT_AKE]) for d in range(num_days)) for n in range(num_nurses)],
        "休": [sum(solver.Value(x[n, d, SHIFT_REST]) for d in range(num_days)) for n in range(num_nurses)],
    }
    df = pd.DataFrame(data)
    df["勤務計"] = df["日勤"] + df["夜勤"]
    df["休日計"] = df["休"] + df["明け"]
    return df


def diagnose_infeasibility(nurse_df, off_requests):
    """INFEASIBLE になった時に、よくある原因を事前チェックで具体的に指摘する。"""
    issues = []
    N, D = num_nurses, num_days

    # 夜勤可能な人
    can_night_idx = [i for i in range(N) if can_take_night(nurse_df, i)]
    n_can_night = len(can_night_idx)

    # 土日休
    weekend_off_idx = [i for i in range(N) if bool(nurse_df.loc[i, "土日休"])]
    weekend_days = get_weekend_days()

    # その日ごとの希望休カウント
    off_per_day = [0] * D
    for n, days in off_requests.items():
        for d in days:
            if 1 <= d <= D:
                off_per_day[d - 1] += 1

    # ---- ① 夜勤の人手不足 ----
    night_demand = min_night * D
    night_capacity = n_can_night * max_nights
    if n_can_night == 0:
        issues.append(
            f"❌ **夜勤できる人がいません**: 役割「一般」かつ「夜勤可」のスタッフが0名です。"
            f"必要夜勤 {night_demand}回 を誰も担えません。\n\n"
            f"→ 看護師リストで「夜勤可」をONにする、または「パート」を解除してください。"
        )
    elif night_demand > night_capacity:
        need = -(-night_demand // n_can_night)  # ceil division
        issues.append(
            f"❌ **夜勤の人手不足**: 月の必要夜勤は **{min_night}人/日 × {D}日 = {night_demand}回** ですが、"
            f"夜勤可能な {n_can_night}名 × 月間夜勤上限 {max_nights}回 = **{night_capacity}回** しか確保できません。\n\n"
            f"→ 夜勤可能なスタッフを増やす、または月間夜勤上限を **{need}回以上** に増やしてください。"
        )

    # ---- ② 月間夜勤の下限と上限の矛盾 ----
    if n_can_night > 0 and min_nights > max_nights:
        issues.append(
            f"❌ **月間夜勤の下限({min_nights})が上限({max_nights})を超えています**\n\n"
            f"→ サイドバーで「月間夜勤 下限」を「上限」以下に下げてください。"
        )

    # ---- ②b 1日あたり 最低/上限 の矛盾 ----
    if min_day > max_day:
        issues.append(
            f"❌ **日勤の最低人数({min_day})が上限({max_day})を超えています**\n\n"
            f"→ サイドバーで「日勤 最低人数」を「上限人数」以下にしてください。"
        )
    if min_night > max_night:
        issues.append(
            f"❌ **夜勤の最低人数({min_night})が上限({max_night})を超えています**\n\n"
            f"→ サイドバーで「夜勤 最低人数」を「上限人数」以下にしてください。"
        )

    # ---- ③ 全体の勤務量過多 ----
    max_work_per_nurse = D - min_off
    total_capacity = N * max_work_per_nurse
    work_demand = (min_day + min_night) * D
    if work_demand > total_capacity:
        issues.append(
            f"❌ **全体の勤務量が多すぎます**: 必要勤務 (日勤{min_day} + 夜勤{min_night}) × {D}日 = **{work_demand}日分** "
            f"に対し、{N}名 ×（{D}日 - 月間休日下限 {min_off}）= **{total_capacity}日分** しか勤務余力がありません。\n\n"
            f"→ 看護師を増やす / 月間休日下限を下げる / 必要人員(日勤・夜勤)を減らす"
        )

    # ---- ④ ある特定の日に希望休＋土日休が集中して人員不足 ----
    daily_demand = min_day + min_night
    for d in range(D):
        weekend_off_today = len(weekend_off_idx) if d in weekend_days else 0
        available = N - off_per_day[d] - weekend_off_today
        if available < daily_demand:
            wkd = WEEKDAY_JP[date(year, month, d + 1).weekday()]
            details = []
            if off_per_day[d]:
                details.append(f"希望休 {off_per_day[d]}名")
            if weekend_off_today:
                details.append(f"土日休 {weekend_off_today}名")
            detail_str = "・".join(details) if details else "0名"
            issues.append(
                f"❌ **{d+1}日({wkd})の人員不足**: {detail_str} で、稼働可能 **{available}名** だが、"
                f"必要 **{daily_demand}名**（日勤{min_day}+夜勤{min_night}）に届きません。\n\n"
                f"→ {d+1}日の希望休を分散する、または看護師を増やす"
            )

    # ---- ⑤ 土日全般の人員不足 ----
    if weekend_off_idx and weekend_days:
        weekend_capacity = N - len(weekend_off_idx)
        if weekend_capacity < daily_demand:
            issues.append(
                f"❌ **土日の人員不足**: 土日休スタッフが {len(weekend_off_idx)}名いるため、"
                f"土日の出勤可能人数は **{weekend_capacity}名** のみ。必要 **{daily_demand}名** に届きません。\n\n"
                f"→ 土日休のスタッフを減らすか、土日の最低人員を別途設定（要追加機能）"
            )

    return issues


SHIFT_COLORS = {
    # 看護師さん向けに、ふんわりパステルでまとめた配色
    "日": "background-color:#B2DFDB; color:#00695C; font-weight:bold; border-radius:8px",      # ミント (爽やかな日中)
    "夜": "background-color:#7E57C2; color:#FFFFFF; font-weight:bold; border-radius:8px",      # ラベンダー (落ち着いた夜)
    "明": "background-color:#FFE0B2; color:#E65100; font-weight:bold; border-radius:8px",      # ピーチ (朝日)
    "休": "background-color:#F8BBD0; color:#AD1457; font-weight:bold; border-radius:8px",      # ピンク (お休み)
}


def style_shift(val):
    return SHIFT_COLORS.get(val, "")


def render_schedule_html(schedule_df):
    """シフト表を横スクロール不要のコンパクトHTMLテーブルとして出力。"""
    css = """
    <style>
    .shift-table { border-collapse: separate; border-spacing: 3px; font-family: inherit;
                   width: 100%; table-layout: fixed; }
    .shift-table th, .shift-table td {
        text-align: center; padding: 8px 2px; font-size: 1em;
        border-radius: 8px;
        overflow: hidden; white-space: nowrap;
    }
    .shift-table thead th {
        background: #FCE4EC; color: #AD1457; font-weight: 700; font-size: 0.85em;
        padding: 6px 2px; line-height: 1.25;
    }
    .shift-table th.name-col, .shift-table td.name-col {
        text-align: left; padding: 8px 10px; background: #FFFFFF;
        color: #5C4856; font-weight: 600; width: 90px;
        border-left: 3px solid #F48FB1;
        font-size: 0.95em;
    }
    .shift-table th.wkd-sat { color: #1565C0; background: #E3F2FD; }
    .shift-table th.wkd-sun, .shift-table th.holiday { color: #C62828; background: #FFEBEE; }
    </style>
    """

    html = css + '<div style="overflow-x:auto;"><table class="shift-table"><thead><tr>'
    for col in schedule_df.columns:
        if col == "氏名":
            html += '<th class="name-col">氏名</th>'
            continue
        cls = []
        if "(土" in col:
            cls.append("wkd-sat")
        if "(日" in col:
            cls.append("wkd-sun")
        if "祝" in col:
            cls.append("holiday")
        # "1(金)" → "1<br>金" で2行化 (祝日は "祝" を付ける)
        num, paren = col.split("(", 1)
        paren = paren.rstrip(")")
        if "・祝" in paren:
            wkd_label = paren.replace("・祝", "") + "祝"
        else:
            wkd_label = paren
        label = f"{num}<br>{wkd_label}"
        html += f'<th class="{" ".join(cls)}">{label}</th>'
    html += '</tr></thead><tbody>'

    for _, row in schedule_df.iterrows():
        html += '<tr>'
        for col in schedule_df.columns:
            val = row[col]
            if col == "氏名":
                html += f'<td class="name-col">{val}</td>'
            else:
                style = SHIFT_COLORS.get(val, "")
                html += f'<td style="{style}">{val}</td>'
        html += '</tr>'
    html += '</tbody></table></div>'
    return html


def render_pattern(solver_, status_, x_, label, nurse_df):
    """1パターン分のシフト表・集計・CSVダウンロードを画面に出力。"""
    kind = "最適解" if status_ == cp_model.OPTIMAL else "実行可能解"
    st.success(f"✅ {label} 生成完了 ({kind} / 目的関数値 = {solver_.ObjectiveValue():.0f})")
    schedule_df = build_schedule_df(solver_, x_, nurse_df)
    summary_df = build_summary_df(solver_, x_, nurse_df)
    st.subheader(f"📊 シフト表 — {label}")
    st.markdown(render_schedule_html(schedule_df), unsafe_allow_html=True)
    st.subheader(f"📈 集計 — {label}")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
    csv = schedule_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        f"📥 {label} CSVダウンロード",
        csv,
        file_name=f"shift_{year}_{month:02d}_{label.replace(' ', '_')}.csv",
        mime="text/csv",
        key=f"dl_{label}",
    )


# ==========================================================
# タブ構成
# ==========================================================
tab_main, tab_rules = st.tabs(["💖 シフトを作る", "📖 ルール・使い方"])

# ----------------------------------------------------------
# タブ1: シフト作成
# ----------------------------------------------------------
with tab_main:
    st.subheader("👩‍⚕️ 看護師さんリスト")
    st.caption("役割: `一般` は日勤・夜勤どちらも可 / `パート` は夜勤なし 🌸 土日休は育児中スタッフなど向け（祝日も自動で休み）／ 明け後夜勤OK は夜勤→明け→夜勤 の特例パターンを許容")

    # 看護師リストの DataFrame は schema_version で管理。
    # 起動時: 保存済み状態があれば復元、無ければデフォルト
    if st.session_state.get("nurse_df_schema") != NURSE_DF_SCHEMA_VERSION:
        saved = load_saved_state()
        if (
            saved.get("schema_version") == NURSE_DF_SCHEMA_VERSION
            and "nurses" in saved
            and len(saved["nurses"]) == num_nurses
        ):
            df = pd.DataFrame(saved["nurses"])
            for col in ["夜勤可", "土日休", "明け後夜勤OK"]:
                if col in df.columns:
                    df[col] = df[col].astype(bool)
            st.session_state.nurse_df = df
        else:
            st.session_state.nurse_df = pd.DataFrame({
                "氏名": [f"看護師{i+1}" for i in range(num_nurses)],
                "役割": ["一般"] * num_nurses,
                "夜勤可": [True] * num_nurses,
                "土日休": [False] * num_nurses,
                "明け後夜勤OK": [False] * num_nurses,
            })
        st.session_state.nurse_df_schema = NURSE_DF_SCHEMA_VERSION
    elif len(st.session_state.nurse_df) != num_nurses:
        # 看護師数が変わった時はデフォルトで埋め直す
        st.session_state.nurse_df = pd.DataFrame({
            "氏名": [f"看護師{i+1}" for i in range(num_nurses)],
            "役割": ["一般"] * num_nurses,
            "夜勤可": [True] * num_nurses,
            "土日休": [False] * num_nurses,
            "明け後夜勤OK": [False] * num_nurses,
        })

    nurse_df = st.data_editor(
        st.session_state.nurse_df,
        num_rows="fixed",
        column_config={
            "役割": st.column_config.SelectboxColumn(options=["一般", "パート"]),
            "夜勤可": st.column_config.CheckboxColumn(),
            "土日休": st.column_config.CheckboxColumn(help="ON にすると、その月の全ての土曜・日曜・祝日が必ず休みになります"),
            "明け後夜勤OK": st.column_config.CheckboxColumn(help="ON にすると、夜勤明けの翌日に夜勤を入れることが可能になります（特例）"),
        },
        use_container_width=True,
        hide_index=True,
        key="nurse_editor",
    )

    st.subheader("🌸 希望休の入力")
    st.caption("休みたい日をカンマ区切りで入力してね（例: `3,10,22`）")

    # 保存済み希望休テキストを初回のみ session_state に流し込む
    if not st.session_state.get("off_requests_loaded"):
        saved_off_text = load_saved_state().get("off_requests_text", {})
        for i in range(num_nurses):
            key = f"off_{i}"
            if key not in st.session_state:
                st.session_state[key] = saved_off_text.get(str(i), "")
        st.session_state.off_requests_loaded = True

    off_requests = {}
    off_requests_text = {}
    cols = st.columns(min(4, num_nurses))
    for i, name in enumerate(nurse_df["氏名"]):
        with cols[i % len(cols)]:
            s = st.text_input(f"{name}", key=f"off_{i}", placeholder="例: 5,12,19")
            off_requests_text[str(i)] = s
            try:
                off_requests[i] = [int(x.strip()) for x in s.split(",") if x.strip()]
            except ValueError:
                st.error(f"{name}: 数字のみ入力してください")
                off_requests[i] = []

    # 看護師リスト・希望休・サイドバー設定を自動保存 (再読込で復元される)
    current_settings = {k: st.session_state[k] for k in SIDEBAR_KEYS if k in st.session_state}
    save_state(nurse_df, off_requests_text, current_settings)

    st.divider()
    gen_two = st.checkbox("別パターン（パターンB）も同時に生成する", value=True,
                          help="同じ条件でもう1つ別の組み合わせを並べて見られます。生成時間が約1.5倍になります。")

    if st.button("✨ シフトを自動で作る ✨", type="primary", use_container_width=True):
        with st.spinner("最適化中..."):
            solver, status, x = build_and_solve(nurse_df, off_requests)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # パターンA の割当を辞書化（パターンB の制約用）
            first_assignment = {
                (n, d): s
                for n in range(num_nurses) for d in range(num_days) for s in SHIFTS
                if solver.Value(x[n, d, s]) == 1
            }

            solver_b = status_b = x_b = None
            if gen_two:
                with st.spinner("別パターン (B) を生成中..."):
                    solver_b, status_b, x_b = build_and_solve(
                        nurse_df, off_requests,
                        forbidden_solution=first_assignment,
                        time_limit_s=8.0,
                    )

            if gen_two and status_b in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                tab_a, tab_b = st.tabs(["🌸 パターン A", "🌷 パターン B（別案）"])
                with tab_a:
                    render_pattern(solver, status, x, "パターン A", nurse_df)
                with tab_b:
                    render_pattern(solver_b, status_b, x_b, "パターン B", nurse_df)
                    # 差分セル数を参考表示
                    diff = sum(
                        1
                        for n in range(num_nurses) for d in range(num_days)
                        if not any(
                            solver.Value(x[n, d, s]) == 1 and solver_b.Value(x_b[n, d, s]) == 1
                            for s in SHIFTS
                        )
                    )
                    total_cells = num_nurses * num_days
                    st.caption(f"※ パターンA との差分: {diff} / {total_cells} セル ({diff / total_cells:.0%})")
            else:
                render_pattern(solver, status, x, "パターン A", nurse_df)
                if gen_two:
                    st.info("別パターン (B) は時間内に見つかりませんでした。条件が厳しすぎて代替解が無いか、計算時間が不足しています。")

        elif status == cp_model.INFEASIBLE:
            st.error("❌ 実行不可能 (INFEASIBLE) — 制約が厳しすぎて解がありません")
            issues = diagnose_infeasibility(nurse_df, off_requests)
            if issues:
                st.markdown("### 🔍 検出された原因（数値で見える矛盾）")
                for issue in issues:
                    st.warning(issue)
            else:
                st.info("事前チェックでは明らかな数値矛盾は見つかりませんでした。複数制約の組み合わせの可能性があるため、各制約を1つずつ緩めて検証します（数十秒かかります）...")
                with st.spinner("制約を1つずつ緩めて原因を絞り込み中..."):
                    diag_results = deep_diagnose(nurse_df, off_requests)

                st.markdown("### 🔬 詳細診断: 制約を1つずつ緩めて検証")
                st.caption("「✅解けた」と出た制約を緩めれば、シフトが組めるようになります。「❌解けず」が並ぶ場合、複数の制約を同時に緩める必要あり。")

                feasible_found = False
                for label, feasible, _ in diag_results:
                    if feasible:
                        st.success(f"✅ **{label}** → 解けました（→ ここを緩めれば動きます）")
                        feasible_found = True
                    else:
                        st.error(f"❌ {label} → それでも解けず")

                if not feasible_found:
                    st.warning(
                        "**1つの緩和では解けませんでした**。次の組み合わせを試してください:\n\n"
                        "- 看護師数を1名増やす\n"
                        "- サイドバーの「日勤 最低人数」「夜勤 最低人数」を1減らす\n"
                        "- 月間休日下限と月間夜勤下限を同時に下げる\n"
                        "- 希望休 ＋ 土日休を見直す"
                    )
        else:
            st.warning(f"⚠️ 時間内に解が見つかりませんでした (status={solver.StatusName(status)}) — 計算時間を延ばすか制約を緩めてください")

# ----------------------------------------------------------
# タブ2: ルール・使い方
# ----------------------------------------------------------
with tab_rules:
    st.markdown("## 📖 はじめての方へ 🌸")
    st.markdown(
        """
このツールは、**看護師さんのシフト表（日勤・夜勤・明け・休み）を自動で作るツール** です 💖

人が手で組むと半日〜1日かかる作業を、コンピューターが **全ルールを守りつつ、なるべく公平に** 振り分けて、数秒〜十数秒で出してくれます。
        """
    )

    st.markdown("### ✨ かんたん4ステップ")
    st.markdown(
        """
1. **左サイドバー** 🌷 で「年・月・人数・必要人員・労務上限」を入力
2. **シフトを作るタブ** 💖 で「看護師さんの名前・役割・夜勤可否」を編集
3. 各人の**希望休** 🌸（日付カンマ区切り）を入力
4. ✨ **「シフトを自動で作る」ボタン** を押す → シフト表が完成（CSV保存もOK）
        """
    )

    st.divider()

    # ---- シフトの種類 ----
    st.markdown("## 🎨 シフトの種類と色分け")
    legend = pd.DataFrame({
        "シフト": ["日", "夜", "明", "休"],
        "意味": [
            "日勤（日中の出勤）",
            "夜勤（夜の出勤・翌朝まで）",
            "明け（夜勤の翌日。基本休み）",
            "休（完全休日）",
        ],
    })
    styled_legend = legend.style.map(style_shift, subset=["シフト"])
    st.dataframe(styled_legend, hide_index=True, use_container_width=True)
    st.caption("※ 夜勤の翌日は必ず「明」、その翌日は必ず「休」になります（2連休が確保される設計）")

    st.divider()

    # ---- 絶対守るルール ----
    st.markdown("## ✅ 絶対守るルール（ハード制約・15種類）")
    st.caption("これらは1つでも崩れると「実行不可」となり、シフトが出ません。")

    hard_rules = [
        ("①  各人 各日 ちょうど1シフト",
         "1人の人が同じ日に「日勤と夜勤」を両方もつことはない。必ず日・夜・明・休のどれか1つ。"),
        ("②  1日あたりの最低人員（日勤・夜勤）",
         "毎日、サイドバーで決めた最低人数以上が配置される。例: 日勤3人以上 / 夜勤1人以上。"),
        ("②b 1日あたりの上限人員（日勤・夜勤）",
         "毎日、サイドバーで決めた上限人数以下に抑える。例: 日勤6人まで / 夜勤2人まで。人を入れすぎないため。"),
        ("③  夜勤の翌日は必ず「明け」",
         "夜勤明けの人は翌日勤務にならない。引き継ぎ業務などで疲れている前提。"),
        ("④  「明け」は夜勤の翌日のみ",
         "前日が夜勤でないのに「明け」になることはない。"),
        ("⑤  夜→明→休 パターン（2連休保証・特例あり）",
         "夜勤→明け→次の日は必ず「休」。連続して3日休めるイメージで身体を休める。ただし看護師リストで「明け後夜勤OK」を ON にした人は、明けの翌日に夜勤を入れる特例が許される（ただし月間上限回数あり）。"),
        ("⑤b 明け後夜勤の回数上限",
         "「明け後夜勤OK」ONのスタッフでも、月のうち「明け→夜勤」パターンを取れる回数はサイドバーで決めた上限まで（既定: 3回）。働きすぎ防止のため。"),
        ("⑥  「パート」「夜勤不可」の人は夜勤なし",
         "役割が「パート」または「夜勤可」のチェックを外した人には、夜勤を一切割り当てない。"),
        ("⑦  「土日休」ONのスタッフは土日・祝日が固定で休み",
         "看護師リストの「土日休」をONにすると、その月の全ての土曜・日曜・祝日（日本の国民の祝日）が必ず「休」になる（パートさん・育児中スタッフ向け）。金曜夜勤も自動で回避される（土曜が「明け」になり休と矛盾するため）。"),
        ("⑧  希望休は必ず「休」",
         "各人が入力した希望休の日は、必ず休みになる。第1希望のみ対応（第2・第3希望は今後追加予定）。"),
        ("⑨  月間 夜勤 上限",
         "1人あたり月の夜勤回数が上限以下になる（既定: 8回まで）。働きすぎを防ぐ。"),
        ("⑩  月間 夜勤 下限（夜勤可の人のみ）",
         "夜勤可の人は最低◯回は夜勤に入る（既定: 2回以上）。一部に偏らないようにするため。"),
        ("⑪  月間 休日 下限（休のみ）",
         "1人あたり月の純粋な休日（「休」のみ）が下限以上（既定: 8日以上）。明けは夜勤に付随する強制休なので別カウントです。"),
        ("⑫  月間 休日 上限（休のみ）",
         "1人あたり月の純粋な休日（「休」のみ）が上限以下（既定: 12日まで）。夜勤しないスタッフが休過剰になるのを防ぐ。"),
        ("⑬  月間 最低勤務日数（日勤+夜勤）",
         "1人あたり月の勤務日数（日勤＋夜勤）が最低◯日以上（既定: 12日以上）。「働かなさすぎる人」を防ぐ。"),
        ("⑭  連続勤務 上限",
         "連続◯日働いたら必ず1日は休む（既定: 5連勤まで → 6日目には休 or 明け）。"),
    ]
    for title, desc in hard_rules:
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.markdown(desc)

    st.divider()

    # ---- なるべく良くするルール ----
    st.markdown("## 🎯 なるべく良くするルール（ソフト制約）")
    st.caption("守れなくてもエラーにはならないが、コンピューターは「守った方が良い」として優先する。")

    soft_rules = [
        ("勤務日数の公平性（重み3）",
         "全員の勤務日数（日勤＋夜勤）の差をできるだけ小さくする。「あの人ばかり多い」を防ぐ。"),
        ("夜勤回数の公平性（重み2）",
         "全員の夜勤回数の差をできるだけ小さくする。"),
        ("純粋な休（休日）の公平性（重み2）",
         "全員の「休」（明けを除く真の休日）の差をできるだけ小さくする。夜勤を取らない人だけ休が極端に多くなるのを防ぐ。"),
    ]
    for title, desc in soft_rules:
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.markdown(desc)

    st.markdown(
        """
**目的関数（コンピューターが最小化したい数値）:**

`Z = 3 × 勤務日数の差 + 2 × 夜勤回数の差 + 2 × 休の差`

→ Z が小さいほど「公平で望ましいシフト」。
        """
    )

    st.divider()

    # ---- 用語集 ----
    st.markdown("## 📚 用語集")
    glossary = pd.DataFrame({
        "用語": ["一般", "パート", "夜勤可", "土日休", "明け後夜勤OK", "明け", "祝日",
                 "ハード制約", "ソフト制約",
                 "目的関数", "最適解 / OPTIMAL", "実行可能解 / FEASIBLE", "実行不可能 / INFEASIBLE"],
        "意味": [
            "日勤・夜勤の両方ができる通常スタッフ。",
            "パート勤務スタッフ。夜勤を一切しない（日勤のみ）扱いになる。",
            "夜勤OKかどうかのチェック。外すと夜勤に入らない。",
            "ONにすると、その月の全土曜・日曜・祝日が固定で休みになる（パートさん・育児中など）。金曜夜勤も自動で除外される。",
            "ONにすると、夜勤明けの翌日に夜勤を入れる特例が許される。通常は「夜→明→休」で固定だが、これを解除するフラグ。月間の回数はサイドバー「明け後夜勤 上限」で制限される。",
            "夜勤の翌日。出勤扱いではなく休み。",
            "日本の国民の祝日。シフト表の列名に「・祝」と表示される。「土日休」ONスタッフは祝日も自動で休みになる。",
            "絶対に守るルール。1つでも破れない場合は「実行不可」。",
            "なるべく守りたいルール。守れなくてもエラーにはならない。",
            "コンピューターが「小さくしたい」数値。公平性を表す。",
            "全候補の中で目的関数が最も小さい完璧な解。",
            "ルールは満たすが、最善か断定できない解（時間切れ等）。実用上は問題なく使える。",
            "ルールが厳しすぎて解が存在しない状態。設定を緩める必要あり。",
        ],
    })
    st.dataframe(glossary, hide_index=True, use_container_width=True)

    st.divider()

    # ---- 困った時 ----
    st.markdown("## 🆘 うまく作れない時のヒント")
    st.markdown(
        """
**「実行不可能 (INFEASIBLE)」と出る場合**、以下の組み合わせがよくある原因です。
        """
    )
    troubleshoot = [
        ("人手が足りない", "日勤最低 + 夜勤最低 × 2 (夜+明) > 看護師数 になっていないか確認。"),
        ("希望休が同じ日に集中", "全員が同じ日を希望休にすると、その日の最低人員を満たせない。"),
        ("月間休日下限が高すぎ", "下限が高いと、必要な勤務日数を確保できなくなる。月の必要勤務 (日勤+夜勤) と バランスが取れているか確認。"),
        ("月間休日上限が低すぎ", "上限を厳しくすると、夜勤しないスタッフが日勤を多めに取らされ、他の人員配置と衝突して詰むことがある。"),
        ("月間夜勤下限が高すぎ", "夜勤可メンバーが少ないのに下限を高くすると、上限と矛盾する。"),
        ("最低勤務日数が高すぎ", "全員に多くの勤務を要求すると、休日下限を満たせなくなることがある。"),
        ("連続勤務上限が短すぎ", "3連勤までに設定すると、必要人員を満たすシフトが組めないことが多い。"),
        ("日勤/夜勤 上限が低すぎ", "1日あたり上限が低いと、必要人員と矛盾する。最低 ≤ 上限になっているか確認。"),
        ("土日休スタッフが多すぎ", "土日休のスタッフを多くすると、土日に必要人員（特に夜勤）を満たせなくなる。土日のみ最低人員を緩めるか、人数を再検討。"),
    ]
    for cause, hint in troubleshoot:
        with st.container(border=True):
            st.markdown(f"**▶ {cause}**")
            st.markdown(hint)

    st.divider()

    # ---- 現在の設定 ----
    st.markdown("## ⚙️ 現在の設定値（サイドバーで変更）")
    settings = pd.DataFrame({
        "項目": ["対象月", "日数", "看護師数",
                 "日勤 最低/上限", "夜勤 最低/上限",
                 "連続勤務 上限", "月間夜勤 上限", "月間夜勤 下限",
                 "月間休日 下限（休のみ）", "月間休日 上限（休のみ）", "月間 最低勤務日数",
                 "明け後夜勤 上限（月間）",
                 "最大計算時間"],
        "値": [f"{year}年{month}月", f"{num_days}日", f"{num_nurses}名",
               f"{min_day}〜{max_day}人", f"{min_night}〜{max_night}人",
               f"{max_consecutive}日",
               f"{max_nights}回", f"{min_nights}回",
               f"{min_off}日", f"{max_off}日", f"{min_workdays}日",
               f"{max_ake_to_night}回",
               f"{time_limit}秒"],
    })
    st.dataframe(settings, hide_index=True, use_container_width=True)

    st.divider()

    # ---- 数学的詳細 ----
    with st.expander("🔢 数式で見る詳細仕様（上級者向け）"):
        st.markdown(
            r"""
**変数:** `x[n, d, s] ∈ {0, 1}`  （看護師 n が 日 d に シフト s を担当）

**シフト記号:** 0=休, 1=日, 2=夜, 3=明

**ハード制約:**

```
H1.  ∀n,d:   Σ_s x[n,d,s] = 1
H2.  ∀d:     min_day ≤ Σ_n x[n,d,日] ≤ max_day
             min_night ≤ Σ_n x[n,d,夜] ≤ max_night
H3.  ∀n,d:   x[n,d+1,明] ≥ x[n,d,夜]
H4.  ∀n:     x[n,0,明] = 0
     ∀n,d≥1: x[n,d,明] ≤ x[n,d-1,夜]
H5.  ∀n where not 明け後夜勤OK(n), ∀d:
             x[n,d+1,休] ≥ x[n,d,明]       (明け後夜勤OK はこの制約を除外)
H6.  夜勤不可の n: x[n,d,夜] = 0
H7.  希望休の n,d: x[n,d,休] = 1
H8.  ∀n:     Σ_d x[n,d,夜] ≤ max_nights
H9.  夜勤可の n: Σ_d x[n,d,夜] ≥ min_nights
H10. ∀n:     Σ_d x[n,d,休] ≥ min_off       (休のみカウント、明けは別)
H10b.∀n:     Σ_d x[n,d,休] ≤ max_off       (休の上限)
H10c.∀n:     Σ_d (x[n,d,日] + x[n,d,夜]) ≥ min_workdays  (最低勤務日数)
H11. 任意の (max_consecutive+1) 日窓に 休 or 明 が 1 日以上
```

**目的関数 (最小化):**

```
Z = 3 × (max_workdays - min_workdays)
  + 2 × (max_nights   - min_nights)
  + 2 × (max_rests    - min_rests)
```

詳細は `SPEC.md` を参照。
            """
        )

# ==========================================================
# フッター
# ==========================================================
st.sidebar.divider()
with st.sidebar.expander("🧹 保存データ管理"):
    st.caption(f"保存先: `{STATE_FILE.name}`")
    if STATE_FILE.exists():
        st.caption(f"✓ 保存済み（最終更新: {datetime.fromtimestamp(STATE_FILE.stat().st_mtime).strftime('%Y-%m-%d %H:%M')}）")
    else:
        st.caption("まだ保存ファイルなし")
    if st.button("🗑️ 保存をリセット", help="看護師リスト・希望休・サイドバー設定を初期状態に戻します"):
        clear_saved_state()
        # セッション状態もクリアして完全初期化
        reset_keys = set(SIDEBAR_KEYS) | {"nurse_df", "nurse_df_schema", "off_requests_loaded", "sidebar_loaded"}
        for key in list(st.session_state.keys()):
            if key.startswith("off_") or key in reset_keys:
                del st.session_state[key]
        st.rerun()

st.sidebar.caption("🌸 v1.3 / 自動保存対応 🌸")
st.sidebar.caption("毎日おつかれさまです 💖")
