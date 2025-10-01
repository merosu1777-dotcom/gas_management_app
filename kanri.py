import streamlit as st
import gspread
import json
import os
import io
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import date, datetime, timedelta
import uuid

# 画像アップロード用
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

# -------------------Google Sheets 認証------------
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/spreadsheets",
         "https://www.googleapis.com/auth/drive.file",
         "https://www.googleapis.com/auth/drive"]


# ---- Cloud かローカルか判定 ----
creds = None

try:
    # ✅ Cloud 環境なら st.secrets を読む
    if "GSPREAD_SERVICE_ACCOUNT" in st.secrets:
        creds_dict = dict(st.secrets["GSPREAD_SERVICE_ACCOUNT"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_dict, scope)
except Exception:
    pass  # ローカルならここはスルー

# ✅ ローカルなら service_account.json を探す
if not creds and os.path.exists("service_account.json"):
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "service_account.json", scope)

if not creds:
    st.error(
        "❌ 認証情報が見つかりません。Streamlit Cloud の secrets か、ローカルの service_account.json を設定してください。")
else:
    client = gspread.authorize(creds)
    sheet = client.open("ガソリン管理").sheet1

# バックアップシートの作成（存在しなければ作成）
try:
    backup_sheet = client.open("ガソリン管理").worksheet("バックアップ")
except gspread.exceptions.WorksheetNotFound:
    backup_sheet = client.open("ガソリン管理").add_worksheet(
        # rowsはテキストエリアの高さを1000行分、colsはテキストエリアの幅（文字数）を20文字
        title="バックアップ", rows=1000, cols=20)
    backup_sheet.append_row(["id", "日付", "利用者", "オドメーター開始", "オドメーター終了",
                             "走行距離", "給油量", "給油金額", "作成時間"])

# -------------------Google Drive 認証-----------------
gauth = GoogleAuth()

# 正しいクライアント情報（Google Cloud からDLしたやつ）
credentials_dict = json.loads(st.secrets["GDRIVE_CREDENTIALS"]["json"])
gauth.LoadClientConfigFile(credentials_dict)


# すでにトークンがあればロード
gauth.LoadCredentialsFile("token.json")

if gauth.credentials is None:
    gauth.LocalWebserverAuth()  # 初回だけブラウザ認証
    gauth.SaveCredentialsFile("token.json")

drive = GoogleDrive(gauth)
print("✅ Google Drive に接続できました")

# -----------UI:利用者選択----------
USER_LIST = ["梅三", "真由美", "悠斗", "淳斗"]

# 初回だけセッションに利用者をセット
if "current_user" not in st.session_state:
    st.session_state.current_user = USER_LIST[0]

# サイドバーで利用者選択
current_user = st.sidebar.selectbox(
    "あなたの名前を選択してください", USER_LIST, index=USER_LIST.index(st.session_state.current_user),
    key="user_select"
)

# 選びなおしたらセッションを更新
st.session_state.current_user = current_user

st.title("🚗 プリウス使用管理")

# ------------------セッションステート（再読み込みが必要かどうか検討）----------------
if "reload_flag" not in st.session_state:
    st.session_state.reload_flag = False

# ボタンを広く見せるCSS
st.markdown("""
            <style>
            div.stButton>button{
                width:100%;
                padding:12px 10px;
                fontsize:16px;
                }
                </style>
                """, unsafe_allow_html=True)

# ------------------入力フォーム----------------
with st.form("fuel_form", clear_on_submit=True):
    # 日付と利用者は横並び（モバイルでは縦積み）
    cdate, cuser = st.columns([1, 1])
    with cdate:
        input_date = st.date_input("日付", value=date.today())
    with cuser:
        name = st.selectbox(
            "利用者", USER_LIST, index=USER_LIST.index(current_user))

    # 主要入力は縦並び（スマホで使いやすい）
    odo_start = st.number_input("オドメーター開始値(km)", value=0, format="%d")
    odo_end = st.number_input("オドメーター終了値(km)", value=0, format="%d")
    fuel = st.number_input("給油量(L)", value=0.0, format="%.2f")
    price = st.number_input("金額(円)", value=0, format="%d")

    # 追加：給油レシートアップロード
    receipt_file = st.file_uploader(
        "給油レシート写真をアップロード", type=["png", "jpg", "jpeg"])
    submitted = st.form_submit_button("✅追加する")

if submitted:
    # 単純チェック：終了＞開始
    if odo_end > odo_start:
        distance = odo_end - odo_start
        row_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat(timespec='seconds')

        receipt_url = ""
        if receipt_file:
            # 一時保存
            tmp_path = f"tmp_{row_id}_{receipt_file.name}"
            with open(tmp_path, "wb") as f:
                f.write(receipt_file.getbuffer())

            # Google Drive にアップロード
            gfile = drive.CreateFile({'title': receipt_file.name})
            gfile.SetContentFile(tmp_path)
            gfile.Upload()
            gfile.InsertPermission(
                {'type': 'anyone', 'value': 'anyone', 'role': 'reader'})
            receipt_url = gfile['webContentLink']

            # BytesIOに読み込んでから閉じる
            with open(tmp_path, "rb") as f:
                img_bytes = io.BytesIO(f.read())

            st.image(img_bytes, width=200)

            # 🔹 try/except で削除
            try:
                os.remove(tmp_path)
            except PermissionError:
                pass  # ファイルがまだ使われていたら無視

        # 日付は文字列で保存（YYYY-MM-DD）
        sheet.append_row([
            row_id,
            input_date.strftime("%Y-%m-%d"),
            name,
            odo_start,
            odo_end,
            distance,
            fuel,
            price,
            timestamp
        ])
        st.success(f"{name}さんのデータを保存しました！（走行距離{distance}km）")
        st.session_state.reload_flag = not st.session_state.get(
            "reload_flag", False)
    else:
        st.error("✖ オドメーター終了は開始より大きい値を入力してください。")

# ------------------データ取得・整理----------------


@st.cache_data(ttl=60)
def load_data(flag):
    all_data = sheet.get_all_records()
    df = pd.DataFrame(all_data)
    return df


df = load_data(st.session_state.reload_flag)

if "receipt_url" not in df.columns:
    df["receipt_url"] = ""

if not df.empty:
    # 列名を日本語に統一
    df.rename(columns={
        "row_id": "id",
        "name": "利用者",
        "odo_start": "オドメーター開始",
        "odo_end": "オドメーター終了",
        "distance": "走行距離",
        "fuel": "給油量",
        "price": "給油金額",
        "timestamp": "作成時間",
    }, inplace=True)

    # データ型変換
    df["日付_dt"] = pd.to_datetime(df["日付"], errors="coerce")
    df["作成時間_dt"] = pd.to_datetime(df["作成時間"], errors="coerce")
    for col in ["オドメーター開始", "オドメーター終了", "走行距離", "給油量", "給油金額"]:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # 日付順・作成時間順でソート
    df.sort_values(["日付_dt", "作成時間_dt"], inplace=True)
    df = df.reset_index(drop=True)

    df["年月"] = df["日付_dt"].dt.to_period("M")
    df["日付"] = df["日付_dt"].dt.date

    # 直近一年分に限定
    one_year_ago = pd.to_datetime(date.today()-timedelta(days=365))
    df_recent = df[df["日付_dt"] >= one_year_ago]

    # ------------------月次精算レポート--------------
    st.header("💰 月次精算レポート")

    sorted_periods = sorted(df["年月"].unique(), reverse=True)
    for period in sorted_periods:
        group = df[df["年月"] == period].copy()
        expanded_flag = (period == sorted_periods[0])

        with st.expander(f"📅 {period} の精算", expanded=expanded_flag):
            # オドメーター不連続チェック
            group["前回オドメーター終了"] = group["オドメーター終了"].shift(1)
            group["オドメーター不連続"] = group["オドメーター開始"] != group["前回オドメーター終了"]
            invalid_rows = group[group["オドメーター不連続"]
                                 & group["前回オドメーター終了"].notna()]
            if not invalid_rows.empty:
                st.warning(f"⚠️ {period} の記録でオドメーターが前回終了値とつながっていない行があります。")

            # 月次精算レポート内の写真サムネ表示（横並びグリッド）
            photos = [row["receipt_url"]
                      for _, row in group.iterrows() if row.get("receipt_url")]
            if photos:
                st.markdown("**📸 今月アップロードされたレシート写真**")
                cols_per_row = 4  # 横に並べる枚数
                for i in range(0, len(photos), cols_per_row):
                    cols = st.columns(cols_per_row)
                    for j, photo_url in enumerate(photos[i:i+cols_per_row]):
                        with cols[j]:
                            st.image(photo_url, width=150)

            # 月内データ表示（テーブル）
            group_display = group.sort_values("日付_dt").copy()
            group_display.insert(0, "No", range(1, len(group_display)+1))
            display_cols = ["No", "日付", "利用者", "オドメーター開始",
                            "オドメーター終了", "走行距離", "給油量", "給油金額"]
            st.dataframe(group_display[display_cols].style.format({
                "オドメーター開始": "{:.0f}", "オドメーター終了": "{:.0f}", "走行距離": "{:.0f}",
                "給油量": "{:.2f}", "給油金額": "{:.0f}"
            }))

            # 精算サマリー計算
            total_dist = group["走行距離"].sum()
            total_price = group["給油金額"].sum()
            cost_per_km = total_price / total_dist if total_dist > 0 else 0

            # サマリー表示（スマホ向け縦並び）
            st.markdown(f"""
                <div style="padding:10px; margin:6px 0; border-radius:8px; background-color:#e2eba3;">
                🚗 <b>合計走行距離:</b> {total_dist} km<br>
                ⛽ <b>合計給油金額:</b> {total_price:,.0f} 円<br>
                📊 <b>1kmあたりの金額:</b> {cost_per_km:.2f} 円/km
                </div>
            """, unsafe_allow_html=True)

            # ユーザーごとの精算
            payment = group.groupby("利用者").agg(
                走行距離=("走行距離", "sum"),
                給油金額=("給油金額", "sum")
            ).reset_index()
            payment["負担額"] = payment["走行距離"] * cost_per_km
            payment["精算額"] = payment["給油金額"] - payment["負担額"]

            # カード風に1ユーザーずつ表示
            for _, row in payment.iterrows():
                color = "green" if row["精算額"] > 0 else "red" if row["精算額"] < 0 else "black"
                st.markdown(f"""
                    <div style="padding:10px; margin:6px 0; border-radius:8px; background-color:#eef7ff;">
                        🙍‍♂️ <b>{row['利用者']}</b><br>
                        🚗 走行距離: {row['走行距離']} km<br>
                        💴 給油金額: {row['給油金額']:.0f} 円<br>
                        📊 負担額: {row['負担額']:.0f} 円<br>
                        💸 <span style="color:{color};"><b>精算額: {row['精算額']:.0f} 円</b></span>
                    </div>
                """, unsafe_allow_html=True)


# ------------------編集・削除フォーム----------------
st.markdown("""
<h3>📝 データ編集・削除<br>
<small style="color:gray;">(見つからない場合、左上で自分の名前を選択し直してください)</small></h3>
""", unsafe_allow_html=True)

editable_rows = df[df["利用者"] == current_user].sort_values(["日付_dt", "作成時間_dt"])
if editable_rows.empty:
    st.info("あなたの記録はまだありません。")
else:
    with st.expander("🐸自分の編集・削除フォームを表示", expanded=False):
        for idx, row in editable_rows.iterrows():
            with st.expander(f"{row['日付']} | 走行:{row['走行距離']}km | 給油:{row['給油量']}L | 金額:{row['給油金額']}円", expanded=False):
                with st.form(f"edit_form_{row['id']}"):
                    # 日付と入力項目は縦並び
                    edit_date = st.date_input("日付", value=row["日付"])
                    edit_odo_start = st.number_input(
                        "オドメーター開始値(km)", value=row["オドメーター開始"])
                    edit_odo_end = st.number_input(
                        "オドメーター終了値(km)", value=row["オドメーター終了"])
                    edit_fuel = st.number_input(
                        "給油量(L)", value=float(row["給油量"]))
                    edit_price = st.number_input("金額(円)", value=row["給油金額"])

                    # ボタンは縦に並べて幅100%
                    st.markdown("""
                        <style>
                        div.stButton>button{
                            width:100%;
                            padding:12px 10px;
                            font-size:16px;
                        }
                        </style>
                    """, unsafe_allow_html=True)

                    if row["receipt_url"]:
                        st.image(row["receipt_url"], width=150)
                    new_file = st.file_uploader(
                        "新しいレシートに差し替え（任意）", type=["png", "jpg", "jpeg"])

                    # フォーム内で更新・削除
                    update_btn = st.form_submit_button("🔄 更新")
                    delete_btn = st.form_submit_button("🗑️ 削除")

                    if update_btn:
                        if edit_odo_end > edit_odo_start:
                            # バックアップ
                            backup_row = [
                                row["id"],
                                row["日付"].strftime("%Y-%m-%d") if isinstance(row["日付"],
                                                                             (date, datetime)) else row["日付"],
                                row["利用者"],
                                row["オドメーター開始"],
                                row["オドメーター終了"],
                                row["走行距離"],
                                row["給油量"],
                                row["給油金額"],
                                row["作成時間"],
                                row.get("receipt_url", "")
                            ]
                            backup_sheet.append_row(backup_row)

                            cell = sheet.find(row['id'])
                            if cell:
                                distance = edit_odo_end - edit_odo_start
                                receipt_url = row.get("receipt_url", "")

                                # 新しいファイルがあれば差し替え
                                if new_file:
                                    tmp_path = f"tmp_{row['id']}_{new_file.name}"
                                    with open(tmp_path, "wb") as f:
                                        f.write(new_file.getbuffer())
                                    gfile = drive.CreateFile(
                                        {'title': new_file.name})
                                    gfile.SetContentFile(tmp_path)
                                    gfile.Upload()
                                    gfile.InsertPermission(
                                        {'type': 'anyone', 'value': 'anyone', 'role': 'reader'})
                                    receipt_url = gfile['webContentLink']
                                    os.remove(tmp_path)

                                # Sheets 更新
                                sheet.update(f'B{cell.row}:H{cell.row}', [[
                                    edit_date.strftime("%Y-%m-%d"),
                                    current_user,
                                    edit_odo_start,
                                    edit_odo_end,
                                    distance,
                                    edit_fuel,
                                    edit_price
                                ]])
                                sheet.update(f'J{cell.row}', receipt_url)
                                st.success("記録を更新しました！")
                                st.session_state.reload_flag = not st.session_state.reload_flag
                            else:
                                st.error("記録が見つかりません。更新できません。")
                        else:
                            st.error("オドメーター終了は開始より大きい値を入力してください。")

                    if delete_btn:
                        # バックアップ
                        backup_row = [
                            row["id"],
                            row["日付"].strftime("%Y-%m-%d") if isinstance(row["日付"],
                                                                         (date, datetime)) else row["日付"],
                            row["利用者"],
                            row["オドメーター開始"],
                            row["オドメーター終了"],
                            row["走行距離"],
                            row["給油量"],
                            row["給油金額"],
                            row["作成時間"],
                            row.get("receipt_url", "")
                        ]
                        backup_sheet.append_row(backup_row)

                        cell = sheet.find(row['id'])
                        sheet.delete_rows(cell.row)
                        st.warning("記録を削除しました。(更新してください)")
                        st.session_state.reload_flag = not st.session_state.reload_flag
